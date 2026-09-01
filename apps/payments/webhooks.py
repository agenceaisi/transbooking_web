"""Reception des notifications d'operateur (parcours par redirection).

Trois regles, chacune payee par une panne reelle chez quelqu'un d'autre :

1. **Journaliser le corps brut avant de le comprendre.** Une notification qu'on
   n'a pas su traiter doit rester rejouable ; sinon un incident d'une heure fait
   perdre definitivement les paiements de cette heure-la.
2. **Repondre 200 vite.** Les operateurs reemettent quand la reponse tarde. Un
   traitement lent se transforme en tempete de doublons.
3. **Ne jamais croire le montant sur parole.** Une notification annoncant un
   montant different de celui demande ne confirme pas le paiement : elle leve
   une alerte.

Le retour du navigateur (`return_url`) n'accorde jamais le paiement : il se
falsifie en modifiant une URL. Seule cette notification signee fait foi.
"""
import hashlib
import logging

from django.db import IntegrityError, transaction
from django.http import HttpRequest, HttpResponse, HttpResponseBadRequest
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from .exceptions import PaymentAlreadyConfirmed, PaymentWebhookSignatureInvalid
from .models import Payment, PaymentStatus, PaymentWebhook
from .providers import PROVIDER_REGISTRY, WebhookEvent
from .services import confirm_payment

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def payment_webhook(request: HttpRequest, provider: str) -> HttpResponse:
    """Public entry point for operator notifications.

    ``csrf_exempt`` est ici legitime : l'authenticite n'est pas portee par un
    jeton de session mais par la signature HMAC du corps, que seul l'operateur
    peut produire.

    Args:
        request: The incoming request.
        provider: The provider name, as embedded in the notify URL.

    Returns:
        A short 200 acknowledgement, or 400 when the signature is invalid.
    """
    classe = PROVIDER_REGISTRY.get(provider)
    if classe is None:
        logger.warning("Notification pour un fournisseur inconnu : %r", provider)
        return HttpResponseBadRequest("fournisseur")

    corps = request.body
    empreinte = hashlib.sha256(corps).hexdigest()

    try:
        evenement = classe().parse_webhook(dict(request.headers), corps)
    except PaymentWebhookSignatureInvalid:
        # Journalisee quand meme : une signature invalide est soit une erreur de
        # configuration apres rotation de cle, soit une tentative d'injection.
        PaymentWebhook.objects.get_or_create(
            provider=provider,
            fingerprint=empreinte,
            defaults={"body": corps, "signature_valid": False},
        )
        logger.warning("Notification a signature invalide (%s)", provider)
        return HttpResponseBadRequest("signature")

    try:
        with transaction.atomic():
            journal = PaymentWebhook.objects.create(
                provider=provider,
                fingerprint=empreinte,
                body=corps,
                signature_valid=True,
            )
    except IntegrityError:
        # Deja recue et traitee. L'operateur reemet parce qu'il n'a pas vu notre
        # 200 : on le lui redonne, sans rien refaire.
        return HttpResponse("deja traitee")

    try:
        paiement = appliquer_evenement(evenement)
    except Exception as erreur:  # noqa: BLE001
        # Un 500 declencherait une reemission qui echouerait pareil. On accuse
        # reception et on laisse la reconciliation reprendre la main.
        journal.processing_error = repr(erreur)
        journal.save(update_fields=["processing_error", "updated_at"])
        logger.exception("Notification recue mais non appliquee")
        return HttpResponse("recue")

    journal.payment = paiement
    journal.processed_at = timezone.now()
    journal.save(update_fields=["payment", "processed_at", "updated_at"])
    return HttpResponse("ok")


def appliquer_evenement(evenement: WebhookEvent) -> Payment | None:
    """Apply a verified operator event to the matching payment.

    Args:
        evenement: The verified notification.

    Returns:
        The updated payment, or None when no payment matches.
    """
    paiement = _retrouver_paiement(evenement)
    if paiement is None:
        logger.error(
            "Notification sans paiement connu (ref %s)", evenement.reference
        )
        return None

    if paiement.status == PaymentStatus.PAID:
        return paiement  # Etat final : plus rien a appliquer.

    if evenement.amount is not None and evenement.amount != paiement.amount:
        # Ne pas confirmer, ne pas emettre le billet, alerter. Un ecart de
        # montant est soit une erreur d'integration, soit une manipulation.
        logger.critical(
            "Ecart de montant sur le paiement %s : demande %s, confirme %s",
            paiement.pk,
            paiement.amount,
            evenement.amount,
        )
        return paiement

    if evenement.status == PaymentStatus.PAID:
        try:
            return confirm_payment(
                paiement,
                transaction_ref=evenement.transaction_ref or evenement.provider_ref,
            )
        except PaymentAlreadyConfirmed:
            # La reconciliation a pu confirmer entre-temps : c'est un succes,
            # pas une erreur. `confirm_payment` leve plutot que d'etre
            # idempotent, on absorbe donc ici.
            return paiement

    if evenement.status == PaymentStatus.FAILED:
        paiement.status = PaymentStatus.FAILED
        paiement.save(update_fields=["status", "updated_at"])

    return paiement


def _retrouver_paiement(evenement: WebhookEvent) -> Payment | None:
    """Locate the payment a notification refers to.

    Deux chemins : notre propre reference (transmise en `order_id`), puis la
    reference du fournisseur. Le second sert de filet quand un operateur ne
    renvoie pas notre identifiant.

    Args:
        evenement: The verified notification.

    Returns:
        The matching payment, locked for update, or None.
    """
    if evenement.reference.isdigit():
        paiement = (
            Payment.objects.select_for_update()
            .filter(pk=int(evenement.reference))
            .first()
        )
        if paiement is not None:
            return paiement

    if evenement.provider_ref:
        return (
            Payment.objects.select_for_update()
            .filter(provider_ref=evenement.provider_ref)
            .first()
        )
    return None
