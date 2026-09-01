"""Abstraction fournisseur pour les paiements Mobile Money par OTP.

Le flux est identique quel que soit l'operateur :

1. ``initiate(payment)``      — ouvre la transaction chez le fournisseur.
2. ``send_otp(payment, code)``— declenche l'envoi du code au payeur.
3. ``confirm_otp(payment, otp)`` — valide le code et debite le compte.

Deux familles d'implementations coexistent, distinguees par l'attribut de classe
``generates_otp`` :

- ``generates_otp = False`` (sandbox) : la **plateforme** tire le code, n'en
  stocke que le hash (`payments.PaymentOtp`) et gere expiration / tentatives.
- ``generates_otp = True`` (operateurs reels) : le code est tire et verifie
  **cote operateur** ; la plateforme ne fait que suivre l'etat de la
  transaction et relaie la saisie de l'utilisateur a ``confirm_otp``.

Aucun identifiant d'agregateur n'est code en dur : tout provient de
``settings.PAYMENT_API_*``, alimente par l'environnement.
"""
import hashlib
import hmac
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from decimal import Decimal

from django.conf import settings
from django.utils.crypto import get_random_string

from .exceptions import (
    PaymentFlowNotSupported,
    PaymentProviderNotConfigured,
    PaymentWebhookSignatureInvalid,
)

logger = logging.getLogger(__name__)


def mask_phone(phone: str) -> str:
    """Mask a phone number for safe logging and API responses.

    Args:
        phone: The raw phone number.

    Returns:
        The masked number (e.g. ``****0001``), or an empty string.
    """
    if not phone:
        return ""
    return f"****{phone[-4:]}" if len(phone) > 4 else "****"


@dataclass
class OtpConfirmation:
    """Result of an OTP confirmation attempt at the provider.

    Attributes:
        success: Whether the provider accepted the code and debited the payer.
        transaction_ref: The operator transaction reference (reconciliation).
        message: Optional human-readable reason, in French, on failure.
    """

    success: bool
    transaction_ref: str = ""
    message: str = ""


#: Parcours de paiement. Deux formes coexistent au Burkina Faso et un
#: fournisseur en implemente une seule.
#:
#: - ``otp`` : le payeur obtient un code (envoye par la plateforme, ou genere
#:   par lui via un code court) et le saisit sur le site, qui ne le quitte
#:   jamais. C'est le parcours des agregateurs locaux.
#: - ``redirect`` : le payeur part sur la page de l'operateur, valide avec son
#:   code PIN, revient. La confirmation arrive par notification serveur. C'est
#:   le parcours d'un compte marchand Orange Money direct.
PAYMENT_FLOW_OTP = "otp"
PAYMENT_FLOW_REDIRECT = "redirect"


@dataclass
class Redirection:
    """Transaction ouverte chez un operateur a parcours par redirection.

    Attributes:
        provider_ref: La reference de la transaction chez l'operateur, a
            enregistrer AVANT de repondre au navigateur : sans elle, une
            transaction dont la notification se perd est introuvable.
        redirect_url: La page de l'operateur ou envoyer le payeur.
    """

    provider_ref: str
    redirect_url: str


@dataclass
class WebhookEvent:
    """Notification d'operateur, une fois sa signature verifiee.

    Attributes:
        provider_ref: Reference de la transaction chez l'operateur.
        reference: Notre propre reference (identifiant du paiement).
        status: Valeur de ``PaymentStatus`` deduite du statut operateur.
        amount: Montant annonce par l'operateur, a comparer au notre.
        transaction_ref: Reference a conserver pour la reconciliation.
        raw: Charge utile brute, journalisee pour le support.
    """

    provider_ref: str
    reference: str
    status: str
    amount: Decimal | None = None
    transaction_ref: str = ""
    raw: dict = field(default_factory=dict)


class PaymentProvider:
    """Interface commune a tous les fournisseurs Mobile Money."""

    #: Cle de selection via ``settings.PAYMENT_PROVIDER``.
    name = ""
    #: True lorsque l'OTP est genere et verifie par l'operateur lui-meme.
    generates_otp = False
    #: Parcours implemente : ``PAYMENT_FLOW_OTP`` ou ``PAYMENT_FLOW_REDIRECT``.
    #: Les trois methodes OTP ne sont appelees que sur un fournisseur ``otp`` ;
    #: les trois methodes de redirection que sur un fournisseur ``redirect``.
    flow = PAYMENT_FLOW_OTP

    def build_otp_code(self) -> str:
        """Generate the OTP code the platform will store (hashed) and track.

        Only meaningful when ``generates_otp`` is False.

        Returns:
            A numeric code of ``settings.OTP_CODE_LENGTH`` digits.
        """
        return get_random_string(settings.OTP_CODE_LENGTH, allowed_chars="0123456789")

    def initiate(self, payment) -> str:
        """Open a transaction at the provider.

        Args:
            payment: The payment to initiate.

        Returns:
            The provider transaction reference (``provider_ref``).
        """
        raise NotImplementedError

    def send_otp(self, payment, code: str = "") -> None:
        """Trigger the delivery of the OTP to the payer.

        Args:
            payment: The payment awaiting confirmation.
            code: The platform-generated code, when ``generates_otp`` is False.
                Ignored by providers that generate their own code.
        """
        raise NotImplementedError

    def confirm_otp(self, payment, otp: str) -> OtpConfirmation:
        """Confirm the payment with the code entered by the payer.

        Args:
            payment: The payment to confirm.
            otp: The code entered by the payer.

        Returns:
            The confirmation result.
        """
        raise NotImplementedError

    # -- Parcours par redirection ------------------------------------------

    def start_redirect(
        self,
        payment,
        *,
        return_url: str,
        cancel_url: str,
        notify_url: str,
    ) -> Redirection:
        """Open a transaction and return where to send the payer.

        Args:
            payment: The payment to open.
            return_url: Where the operator sends the browser back on success.
                This page NEVER grants the payment: it displays a wait and
                polls our own status. A browser return is forgeable.
            cancel_url: Where the operator sends the browser back on abort.
            notify_url: Public webhook URL. The only source of truth.

        Returns:
            The provider reference and the operator page URL.

        Raises:
            PaymentFlowNotSupported: If this provider uses the OTP flow.
        """
        raise PaymentFlowNotSupported(
            f"Le fournisseur {self.name} n'utilise pas le parcours par redirection."
        )

    def fetch_status(self, payment) -> str:
        """Read the current transaction status at the operator.

        Called by the waiting page and by the reconciliation task: this is the
        net that catches lost notifications.

        Args:
            payment: The payment to refresh.

        Returns:
            A ``PaymentStatus`` value.
        """
        raise NotImplementedError

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Verify an operator notification and translate it.

        Receives the RAW body, not a decoded dict: a signature is computed on
        the bytes received, and Django re-encodes JSON differently from the
        sender.

        Args:
            headers: The request headers.
            body: The raw request body.

        Returns:
            The translated event.

        Raises:
            PaymentWebhookSignatureInvalid: If the signature does not match.
            PaymentFlowNotSupported: If this provider sends no notification.
        """
        raise PaymentFlowNotSupported(
            f"Le fournisseur {self.name} n'emet pas de notification."
        )


def _header(headers: dict, name: str) -> str:
    """Read an HTTP header regardless of case.

    Args:
        headers: The header mapping.
        name: The header name to look up.

    Returns:
        The header value, or an empty string.
    """
    cible = name.lower()
    for cle, valeur in headers.items():
        if cle.lower() == cible:
            return valeur
    return ""


class MockPaymentProvider(PaymentProvider):
    """Fournisseur de test (sandbox) : aucun appel reseau, aucun debit reel.

    L'OTP n'est jamais transmis ni journalise : en sandbox il vaut toujours
    ``settings.PAYMENT_SANDBOX_OTP``, connu du testeur par configuration.
    ``settings.PAYMENT_SANDBOX_FORCE_FAILURE`` simule un refus operateur.
    """

    name = "mock"
    generates_otp = False

    def build_otp_code(self) -> str:
        """Return the configurable sandbox test code.

        Returns:
            The value of ``settings.PAYMENT_SANDBOX_OTP``.
        """
        return str(settings.PAYMENT_SANDBOX_OTP)

    def initiate(self, payment) -> str:
        """Open a fake transaction.

        Args:
            payment: The payment to initiate.

        Returns:
            A deterministic sandbox reference.
        """
        return f"SANDBOX{payment.pk:08d}"

    def send_otp(self, payment, code: str = "") -> None:
        """Simulate the OTP delivery.

        Args:
            payment: The payment awaiting confirmation.
            code: Ignored — never logged nor sent (cf. security.md).
        """
        # On ne journalise que le numero masque : jamais le code.
        logger.info(
            "OTP sandbox emis pour le paiement %s (%s)",
            payment.pk,
            mask_phone(payment.phone),
        )

    def confirm_otp(self, payment, otp: str) -> OtpConfirmation:
        """Simulate the operator confirmation.

        The code itself is already checked by the service against the stored
        hash; this only simulates the debit outcome.

        Args:
            payment: The payment to confirm.
            otp: The code entered by the payer (unused in sandbox).

        Returns:
            A successful confirmation, or a refusal when
            ``PAYMENT_SANDBOX_FORCE_FAILURE`` is on.
        """
        if settings.PAYMENT_SANDBOX_FORCE_FAILURE:
            return OtpConfirmation(
                success=False,
                message="Paiement refuse par l'operateur (simulation sandbox).",
            )
        return OtpConfirmation(
            success=True,
            transaction_ref=f"SANDBOX{payment.pk:08d}REF",
        )


class BaseOperatorProvider(PaymentProvider):
    """Squelette commun aux operateurs reels (Orange, Moov, Coris, Telecel).

    Les trois methodes restent volontairement non implementees : l'API exacte
    (endpoints, format de signature, codes d'erreur) depend de l'agregateur
    retenu, qui n'est pas encore contractualise.

    # TODO(agregateur): brancher l'API reelle des que les specs et les
    # identifiants seront fournis. Ne rien inventer : endpoints, schema de
    # signature et mapping des codes d'erreur doivent venir de la doc operateur.
    """

    generates_otp = True

    def _credentials(self) -> dict:
        """Return the aggregator credentials read from the environment.

        Returns:
            The credentials dict.

        Raises:
            PaymentProviderNotConfigured: If any credential is missing.
        """
        credentials = {
            "base_url": settings.PAYMENT_API_BASE_URL,
            "api_key": settings.PAYMENT_API_KEY,
            "api_secret": settings.PAYMENT_API_SECRET,
            "merchant_id": settings.PAYMENT_API_MERCHANT_ID,
        }
        missing = [key for key, value in credentials.items() if not value]
        if missing:
            raise PaymentProviderNotConfigured(
                f"Fournisseur {self.name} non configure : "
                f"parametres manquants ({', '.join(sorted(missing))})."
            )
        return credentials

    def initiate(self, payment) -> str:
        self._credentials()
        raise NotImplementedError(
            f"Integration {self.name} non disponible : specs agregateur requises."
        )

    def send_otp(self, payment, code: str = "") -> None:
        self._credentials()
        raise NotImplementedError(
            f"Integration {self.name} non disponible : specs agregateur requises."
        )

    def confirm_otp(self, payment, otp: str) -> OtpConfirmation:
        self._credentials()
        raise NotImplementedError(
            f"Integration {self.name} non disponible : specs agregateur requises."
        )


class OrangeMoneyProvider(PaymentProvider):
    """Orange Money Burkina Faso — compte marchand direct, par redirection.

    Le payeur part sur la page Orange, valide avec son code PIN a quatre
    chiffres, revient sur ``return_url``. Orange notifie en parallele le
    serveur : **seule la notification fait foi**.

    Ecrit avant reception des identifiants marchands. Tant que
    ``PAYMENT_SANDBOX`` vaut True, cette classe n'est jamais instanciee.

    # TODO(orange): confirmer sur le portail Orange Developer, a reception des
    # identifiants, les trois constantes de classe ci-dessous (chemins d'API,
    # noms de champs, en-tete de signature). Elles sont isolees pour qu'une
    # divergence de contrat se corrige a un seul endroit, sans toucher a la
    # logique.

    Note: la couche HTTP s'appuie sur ``urllib`` de la bibliotheque standard,
    pour ne pas introduire de dependance supplementaire. Si le projet adopte
    ``requests`` ou ``httpx`` par ailleurs, ces trois appels s'y porteront
    sans changement de structure.
    """

    name = "orange_money"
    generates_otp = False
    flow = PAYMENT_FLOW_REDIRECT

    #: Chemins d'API — a confirmer.
    CHEMIN_JETON = "/oauth/v3/token"
    CHEMIN_PAIEMENT = "/orange-money-webpay/bf/v1/webpayment"
    CHEMIN_STATUT = "/orange-money-webpay/bf/v1/transactionstatus"

    #: Noms de champs — a confirmer.
    CHAMP_URL = "payment_url"
    CHAMP_JETON_PAIEMENT = "pay_token"
    CHAMP_COMMANDE = "order_id"
    CHAMP_STATUT = "status"
    ENTETE_SIGNATURE = "X-Orange-Signature"

    #: Correspondance statut operateur -> statut du domaine. Toute valeur
    #: inconnue reste « en attente » plutot que de basculer en echec :
    #: declarer echouee une transaction qu'on n'a pas comprise, c'est liberer
    #: une place peut-etre deja payee.
    CORRESPONDANCE_STATUTS = {
        "INITIATED": "otp_required",
        "PENDING": "otp_required",
        "SUCCESS": "paid",
        "SUCCESSFUL": "paid",
        "SUCCESSFULL": "paid",
        "FAILED": "failed",
        "FAILURE": "failed",
        "CANCELLED": "failed",
        "EXPIRED": "failed",
        "REFUNDED": "refunded",
    }

    _jeton = ""
    _jeton_expire_le = 0.0

    # -- Parcours OTP : non applicable ---------------------------------------
    #
    # Un compte marchand Orange direct valide par code PIN sur la page de
    # l'operateur, pas par un code saisi chez nous. Les trois methodes du
    # parcours OTP verifient malgre tout les identifiants avant de refuser :
    # une configuration incomplete doit se signaler comme telle, pas se
    # deguiser en incompatibilite de parcours.

    def initiate(self, payment) -> str:
        self._credentials()
        raise PaymentFlowNotSupported(
            "Orange Money direct utilise le parcours par redirection : "
            "appelez start_redirect()."
        )

    def send_otp(self, payment, code: str = "") -> None:
        self._credentials()
        raise PaymentFlowNotSupported(
            "Orange Money direct n'emet pas de code de confirmation."
        )

    def confirm_otp(self, payment, otp: str) -> OtpConfirmation:
        self._credentials()
        raise PaymentFlowNotSupported(
            "Orange Money direct se confirme par notification, pas par code."
        )

    # -- HTTP ---------------------------------------------------------------

    def _appel(self, chemin: str, charge: dict, jeton: str = "") -> dict:
        """POST a JSON payload to the Orange API.

        Args:
            chemin: The API path.
            charge: The JSON body.
            jeton: The bearer token, when required.

        Returns:
            The decoded JSON response.

        Raises:
            PaymentProviderError: On any non-2xx response or transport error.
        """
        from .exceptions import PaymentProviderError

        identifiants = self._credentials()
        url = identifiants["base_url"].rstrip("/") + chemin
        entetes = {"Content-Type": "application/json", "Accept": "application/json"}
        if jeton:
            entetes["Authorization"] = f"Bearer {jeton}"

        requete = urllib.request.Request(
            url,
            data=json.dumps(charge).encode("utf-8"),
            headers=entetes,
            method="POST",
        )
        try:
            with urllib.request.urlopen(requete, timeout=20) as reponse:
                return json.loads(reponse.read().decode("utf-8"))
        except urllib.error.HTTPError as erreur:
            # Le corps est journalise, jamais renvoye : il porte des
            # identifiants marchands.
            logger.error(
                "Orange refuse l'appel %s (HTTP %s)", chemin, erreur.code
            )
            raise PaymentProviderError() from erreur
        except (urllib.error.URLError, TimeoutError, ValueError) as erreur:
            logger.error("Orange injoignable sur %s : %s", chemin, erreur)
            raise PaymentProviderError() from erreur

    def _credentials(self) -> dict:
        """Return the merchant credentials read from the environment.

        Returns:
            The credentials dict.

        Raises:
            PaymentProviderNotConfigured: If any credential is missing.
        """
        identifiants = {
            "base_url": settings.PAYMENT_API_BASE_URL,
            "api_key": settings.PAYMENT_API_KEY,
            "api_secret": settings.PAYMENT_API_SECRET,
            "merchant_id": settings.PAYMENT_API_MERCHANT_ID,
        }
        manquants = [cle for cle, valeur in identifiants.items() if not valeur]
        if manquants:
            raise PaymentProviderNotConfigured(
                f"Fournisseur {self.name} non configure : "
                f"parametres manquants ({', '.join(sorted(manquants))})."
            )
        return identifiants

    def _jeton_acces(self) -> str:
        """Return a valid OAuth token, from cache when still fresh.

        Returns:
            The bearer token.
        """
        import time

        if self._jeton and time.time() < self._jeton_expire_le:
            return self._jeton

        identifiants = self._credentials()
        url = identifiants["base_url"].rstrip("/") + self.CHEMIN_JETON
        donnees = urllib.parse.urlencode({"grant_type": "client_credentials"})
        requete = urllib.request.Request(
            url, data=donnees.encode("utf-8"), method="POST"
        )
        import base64

        secret = f"{identifiants['api_key']}:{identifiants['api_secret']}"
        requete.add_header(
            "Authorization",
            "Basic " + base64.b64encode(secret.encode("utf-8")).decode("ascii"),
        )
        requete.add_header("Content-Type", "application/x-www-form-urlencoded")

        from .exceptions import PaymentProviderError

        try:
            with urllib.request.urlopen(requete, timeout=20) as reponse:
                charge = json.loads(reponse.read().decode("utf-8"))
        except Exception as erreur:  # noqa: BLE001
            logger.error("Jeton Orange refuse : %s", erreur)
            raise PaymentProviderError() from erreur

        type(self)._jeton = charge["access_token"]
        # Une minute de marge : un jeton qui expire pendant l'appel produit un
        # 401 juste apres le clic sur « Payer ».
        duree = max(int(charge.get("expires_in", 3600)) - 60, 60)
        type(self)._jeton_expire_le = time.time() + duree
        return type(self)._jeton

    # -- Parcours par redirection -------------------------------------------

    def start_redirect(
        self, payment, *, return_url: str, cancel_url: str, notify_url: str
    ) -> Redirection:
        """Open an Orange WebPay transaction.

        Args:
            payment: The payment to open.
            return_url: Success return URL.
            cancel_url: Abort return URL.
            notify_url: Public webhook URL.

        Returns:
            The provider reference and the Orange payment page URL.

        Raises:
            PaymentProviderError: If Orange refuses or answers incompletely.
        """
        from .exceptions import PaymentProviderError

        identifiants = self._credentials()
        charge = self._appel(
            self.CHEMIN_PAIEMENT,
            {
                "merchant_key": identifiants["merchant_id"],
                "currency": "XOF",
                # Le franc CFA n'a pas de subdivision : on transmet un entier.
                "amount": int(payment.amount),
                self.CHAMP_COMMANDE: str(payment.pk),
                "reference": f"TransBooking {payment.pk}"[:64],
                "return_url": return_url,
                "cancel_url": cancel_url,
                "notif_url": notify_url,
                "lang": "fr",
            },
            jeton=self._jeton_acces(),
        )

        url = charge.get(self.CHAMP_URL)
        jeton_paiement = charge.get(self.CHAMP_JETON_PAIEMENT)
        if not url or not jeton_paiement:
            logger.error("Reponse Orange incomplete pour le paiement %s", payment.pk)
            raise PaymentProviderError()

        return Redirection(provider_ref=str(jeton_paiement), redirect_url=str(url))

    def fetch_status(self, payment) -> str:
        """Read the current status of an Orange transaction.

        Args:
            payment: The payment to refresh.

        Returns:
            A ``PaymentStatus`` value.
        """
        identifiants = self._credentials()
        charge = self._appel(
            self.CHEMIN_STATUT,
            {
                "merchant_key": identifiants["merchant_id"],
                self.CHAMP_JETON_PAIEMENT: payment.provider_ref,
            },
            jeton=self._jeton_acces(),
        )
        brut = str(charge.get(self.CHAMP_STATUT, "")).upper()
        statut = self.CORRESPONDANCE_STATUTS.get(brut)
        if statut is None:
            logger.warning("Statut Orange inconnu : %r", brut)
            return "otp_required"
        return statut

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Verify and translate an Orange notification.

        Args:
            headers: The request headers.
            body: The raw request body.

        Returns:
            The translated event.

        Raises:
            PaymentWebhookSignatureInvalid: If the HMAC does not match.
        """
        recue = _header(headers, self.ENTETE_SIGNATURE)
        secret = (settings.PAYMENT_WEBHOOK_SECRET or "").encode("utf-8")
        if not recue or not secret:
            raise PaymentWebhookSignatureInvalid()

        attendue = hmac.new(secret, body, hashlib.sha256).hexdigest()
        # `compare_digest` et non `==` : une comparaison qui s'arrete au premier
        # octet different laisse deviner la signature en mesurant le temps.
        if not hmac.compare_digest(recue.strip().lower(), attendue):
            raise PaymentWebhookSignatureInvalid()

        charge = json.loads(body.decode("utf-8"))
        brut = str(charge.get(self.CHAMP_STATUT, "")).upper()
        montant = charge.get("amount")

        return WebhookEvent(
            provider_ref=str(charge.get(self.CHAMP_JETON_PAIEMENT, "")),
            reference=str(charge.get(self.CHAMP_COMMANDE, "")),
            status=self.CORRESPONDANCE_STATUTS.get(brut, "otp_required"),
            amount=Decimal(str(montant)) if montant is not None else None,
            transaction_ref=str(charge.get("txnid", "") or charge.get("txn_id", "")),
            raw=charge,
        )


class MoovMoneyProvider(BaseOperatorProvider):
    """Moov Africa Money — squelette."""

    name = "moov_money"


class CorisMoneyProvider(BaseOperatorProvider):
    """Coris Money — squelette."""

    name = "coris_money"


class TelecelMoneyProvider(BaseOperatorProvider):
    """Telecel Money — squelette."""

    name = "telecel_money"


class MockRedirectProvider(PaymentProvider):
    """Simulateur du parcours par redirection — developpement uniquement.

    Reproduit la **forme** exacte du parcours Orange : ouverture de
    transaction, page operateur, notification signee. Le tunnel peut donc etre
    ecrit et eprouve avant reception des identifiants marchands, sans prendre
    de mauvaise habitude.

    Et il rejoue ce qu'aucun bac a sable d'operateur ne laisse jouer : les
    quatre pannes qui coutent de l'argent. Le scenario se deduit des deux
    derniers chiffres du montant, ce qui rend les essais manuels
    reproductibles sans configuration :

    ===========  ========================================================
    Montant      Scenario
    ===========  ========================================================
    ``...01``    le payeur annule
    ``...02``    la transaction expire
    ``...03``    payeur debite, **notification jamais emise**
    ``...04``    notification emise **deux fois**
    ``...05``    notification annoncant un **montant different**
    autre        succes
    ===========  ========================================================
    """

    name = "mock_redirect"
    generates_otp = False
    flow = PAYMENT_FLOW_REDIRECT

    SCENARIOS = {
        1: "annulation",
        2: "expiration",
        3: "notification_perdue",
        4: "notification_doublee",
        5: "montant_divergent",
    }

    @classmethod
    def scenario(cls, payment) -> str:
        """Return the scenario replayed for this payment.

        Args:
            payment: The payment whose amount selects the scenario.

        Returns:
            The scenario key.
        """
        return cls.SCENARIOS.get(int(payment.amount) % 100, "succes")

    def start_redirect(
        self, payment, *, return_url: str, cancel_url: str, notify_url: str
    ) -> Redirection:
        """Open a simulated transaction.

        Args:
            payment: The payment to open.
            return_url: Success return URL.
            cancel_url: Abort return URL.
            notify_url: Public webhook URL.

        Returns:
            The reference and the simulated operator page URL.
        """
        base = (getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")
        logger.info(
            "Transaction simulee ouverte pour le paiement %s (scenario %s)",
            payment.pk,
            self.scenario(payment),
        )
        return Redirection(
            provider_ref=f"SANDBOX{payment.pk:08d}",
            redirect_url=f"{base}/_dev/operateur/{payment.pk}/",
        )

    def fetch_status(self, payment) -> str:
        """Return the status the scenario dictates.

        Args:
            payment: The payment to refresh.

        Returns:
            A ``PaymentStatus`` value.
        """
        scenario = self.scenario(payment)
        if scenario == "annulation":
            return "failed"
        if scenario == "expiration":
            return "failed"
        # « notification_perdue » repond bien « paye » : c'est precisement ce
        # que la reconciliation doit decouvrir toute seule.
        return "paid"

    def parse_webhook(self, headers: dict, body: bytes) -> WebhookEvent:
        """Verify and translate a simulated notification.

        Args:
            headers: The request headers.
            body: The raw request body.

        Returns:
            The translated event.

        Raises:
            PaymentWebhookSignatureInvalid: If the HMAC does not match.
        """
        recue = _header(headers, "X-Sandbox-Signature")
        secret = (settings.PAYMENT_WEBHOOK_SECRET or "").encode("utf-8")
        attendue = hmac.new(secret, body, hashlib.sha256).hexdigest()
        if not recue or not hmac.compare_digest(recue.strip().lower(), attendue):
            raise PaymentWebhookSignatureInvalid()

        charge = json.loads(body.decode("utf-8"))
        montant = charge.get("amount")
        return WebhookEvent(
            provider_ref=str(charge.get("pay_token", "")),
            reference=str(charge.get("order_id", "")),
            status=str(charge.get("status", "paid")),
            amount=Decimal(str(montant)) if montant is not None else None,
            transaction_ref=str(charge.get("txnid", "")),
            raw=charge,
        )


PROVIDER_REGISTRY = {
    MockPaymentProvider.name: MockPaymentProvider,
    MockRedirectProvider.name: MockRedirectProvider,
    OrangeMoneyProvider.name: OrangeMoneyProvider,
    MoovMoneyProvider.name: MoovMoneyProvider,
    CorisMoneyProvider.name: CorisMoneyProvider,
    TelecelMoneyProvider.name: TelecelMoneyProvider,
}


def get_payment_provider(method: str) -> PaymentProvider:
    """Return the provider handling a payment method.

    In sandbox mode (``settings.PAYMENT_SANDBOX``) every method is routed to
    ``MockPaymentProvider``: no operator call, no real debit. Otherwise the
    provider is resolved from ``settings.PAYMENT_PROVIDER`` when it is pinned to
    a specific implementation, else from the payment method itself.

    Args:
        method: One of ``PaymentMethod`` values.

    Returns:
        The provider instance.

    Raises:
        PaymentProviderNotConfigured: If no provider matches the method.
    """
    if settings.PAYMENT_SANDBOX:
        # Deux bacs a sable, un par parcours. `PAYMENT_SANDBOX_FLOW` permet de
        # developper le tunnel par redirection (Orange direct) sans casser les
        # tests et les ecrans du parcours OTP, qui restent le defaut.
        if getattr(settings, "PAYMENT_SANDBOX_FLOW", PAYMENT_FLOW_OTP) == (
            PAYMENT_FLOW_REDIRECT
        ):
            return MockRedirectProvider()
        return MockPaymentProvider()

    configured = (settings.PAYMENT_PROVIDER or "").strip()
    key = configured if configured and configured != MockPaymentProvider.name else method

    provider_class = PROVIDER_REGISTRY.get(key)
    if provider_class is None:
        raise PaymentProviderNotConfigured(
            f"Aucun fournisseur de paiement configure pour « {method} »."
        )
    return provider_class()
