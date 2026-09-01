from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class PaymentMethod(models.TextChoices):
    CASH = "cash", "Especes"
    ORANGE_MONEY = "orange_money", "Orange Money"
    MOOV_MONEY = "moov_money", "Moov Money"
    CORIS_MONEY = "coris_money", "Coris Money"
    TELECEL_MONEY = "telecel_money", "Telecel Money"
    CARD = "card", "Carte bancaire"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    # Etat intermediaire du flux Mobile Money : l'OTP a ete emis, on attend la
    # saisie du payeur (cf. PROMPT_SUP B4).
    OTP_REQUIRED = "otp_required", "Code de confirmation attendu"
    PAID = "paid", "Paye"
    FAILED = "failed", "Echoue"
    REFUNDED = "refunded", "Rembourse"


# Moyens de paiement passant par le flux OTP Mobile Money. Les especes restent
# encaissees en une etape au guichet ; la carte est hors perimetre.
MOBILE_MONEY_METHODS = frozenset(
    {
        PaymentMethod.ORANGE_MONEY,
        PaymentMethod.MOOV_MONEY,
        PaymentMethod.CORIS_MONEY,
        PaymentMethod.TELECEL_MONEY,
    }
)


class Payment(TimeStampedModel):
    """Paiement d'une reservation (et, a terme, d'un colis).

    Mobile Money : flux OTP en deux temps (`otp_required` -> `paid`), delegue a
    un `payments.providers.PaymentProvider`. Especes : encaissement en une etape
    au guichet. La `transaction_ref` renvoyee par l'operateur est conservee pour
    la reconciliation (cf. business_rules.md §2). La confirmation passe la
    reservation a `paid`.
    """

    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )
    # Paiement de colis : exclusif avec `booking` (cf. mcd.md §7).
    parcel = models.ForeignKey(
        "parcels.Parcel",
        on_delete=models.PROTECT,
        related_name="payments",
        null=True,
        blank=True,
    )

    amount = models.DecimalField(max_digits=10, decimal_places=2)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    status = models.CharField(
        max_length=20,
        choices=PaymentStatus.choices,
        default=PaymentStatus.PENDING,
    )

    # Reference de transaction Mobile Money renvoyee par l'operateur (ou saisie
    # par l'agent). Donnee sensible : masquee dans les logs et les reponses API
    # (cf. security.md §« Donnees sensibles »).
    transaction_ref = models.CharField(max_length=100, blank=True)
    # Reference de la transaction ouverte chez le fournisseur (provider.initiate).
    provider_ref = models.CharField(max_length=100, blank=True)
    # Numero du payeur (Mobile Money) — facultatif pour les especes.
    phone = models.CharField(max_length=30, blank=True)

    # Commission plateforme figee au moment de la confirmation (cf. business_rules.md §2).
    commission = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Renseigne apres confirmation du paiement.
    receipt_url = models.CharField(max_length=255, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)

    # Agent guichet ayant encaisse (null pour un paiement initie par le voyageur).
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="collected_payments",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"

    def __str__(self) -> str:
        return f"Paiement {self.pk} - {self.amount} FCFA ({self.status})"


class PaymentOtp(TimeStampedModel):
    """Code de confirmation a usage unique d'un paiement Mobile Money.

    Le code n'est JAMAIS stocke en clair : seul son HMAC (`code_hash`) est
    conserve. Il reste vide lorsque le fournisseur genere et verifie l'OTP
    lui-meme (cf. `providers.PaymentProvider.generates_otp`) : la ligne ne sert
    alors qu'au suivi de l'expiration et des tentatives.
    """

    payment = models.ForeignKey(
        Payment,
        on_delete=models.CASCADE,
        related_name="otps",
    )
    code_hash = models.CharField(max_length=128, blank=True)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    # Passe a True des que le code a servi a confirmer le paiement.
    is_used = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Code de confirmation de paiement"
        verbose_name_plural = "Codes de confirmation de paiement"
        indexes = [models.Index(fields=["payment", "-created_at"])]

    def __str__(self) -> str:
        return f"OTP paiement {self.payment_id} (tentatives {self.attempts})"

    @property
    def attempts_remaining(self) -> int:
        """Return how many attempts are left on this code.

        Returns:
            The remaining attempt count, never negative.
        """
        return max(self.max_attempts - self.attempts, 0)


class PaymentWebhook(TimeStampedModel):
    """Journal brut des notifications d'operateur.

    Ecrit AVANT tout traitement, et conserve meme lorsque la signature est
    invalide. C'est la seule piece qui permet, trois semaines plus tard, de
    repondre a une compagnie qui conteste un versement — ou de rejouer une
    notification qu'un incident avait fait perdre.

    L'unicite sur `(provider, fingerprint)` porte l'idempotence : un operateur
    qui reemet trois fois la meme notification est traite une seule fois. Les
    operateurs reemettent des qu'ils ne voient pas de 200 assez vite ; sans
    cette contrainte, un billet serait emis plusieurs fois.
    """

    provider = models.CharField(max_length=32)
    # SHA-256 du corps brut recu.
    fingerprint = models.CharField(max_length=64)
    payment = models.ForeignKey(
        Payment,
        on_delete=models.SET_NULL,
        related_name="webhooks",
        null=True,
        blank=True,
    )
    body = models.BinaryField()
    signature_valid = models.BooleanField()
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_error = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification de paiement"
        verbose_name_plural = "Notifications de paiement"
        constraints = [
            models.UniqueConstraint(
                fields=["provider", "fingerprint"],
                name="paiement_notification_unique_par_corps",
            )
        ]
        indexes = [models.Index(fields=["provider", "-created_at"])]

    def __str__(self) -> str:
        etat = "valide" if self.signature_valid else "SIGNATURE INVALIDE"
        return f"Notification {self.provider} #{self.pk} ({etat})"
