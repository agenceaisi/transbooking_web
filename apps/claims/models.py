from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class ClaimType(models.TextChoices):
    RETARD = "retard", "Retard"
    PERTE_BAGAGE = "perte_bagage", "Perte de bagage"
    BAGAGE_ENDOMMAGE = "bagage_endommage", "Bagage endommage"
    COMPORTEMENT = "comportement", "Comportement"
    SURCHARGE = "surcharge", "Surcharge"
    REMBOURSEMENT = "remboursement", "Remboursement"
    AUTRE = "autre", "Autre"


class ClaimStatus(models.TextChoices):
    SUBMITTED = "submitted", "Soumise"
    IN_PROGRESS = "in_progress", "En traitement"
    RESOLVED = "resolved", "Resolue"
    CLOSED = "closed", "Cloturee"
    ESCALATED = "escalated", "Escaladee"


# Statuts consideres comme « non traites » (pour le tri et les statistiques).
UNRESOLVED_STATUSES = (
    ClaimStatus.SUBMITTED,
    ClaimStatus.IN_PROGRESS,
    ClaimStatus.ESCALATED,
)


class Claim(TimeStampedModel):
    """Reclamation deposee par un voyageur a l'encontre d'une compagnie.

    Le flag `is_overdue` (reponse non fournie sous 48h, cf. business_rules.md §5)
    est annote a la requete dans `services.annotated_claims()`, jamais stocke.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="claims",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="claims",
    )
    # Reservation concernee : facultative (la reclamation peut etre generale).
    booking = models.ForeignKey(
        "bookings.Booking",
        on_delete=models.SET_NULL,
        related_name="claims",
        null=True,
        blank=True,
    )

    # Numero de billet saisi manuellement si le plaignant n'a pas de compte
    # (booking non rattache). Cf. mcd.md §9.
    ticket_number = models.CharField(max_length=20, blank=True)

    claim_type = models.CharField(max_length=20, choices=ClaimType.choices)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    travel_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=ClaimStatus.choices,
        default=ClaimStatus.SUBMITTED,
    )
    response = models.TextField(blank=True)
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="claim_responses",
        null=True,
        blank=True,
    )
    responded_at = models.DateTimeField(null=True, blank=True)
    # Rempli quand le voyageur accepte la proposition de la compagnie
    # (cf. services.accept_claim_response) — distinct de responded_at, qui trace
    # la reponse de la compagnie.
    traveler_accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Reclamation"
        verbose_name_plural = "Reclamations"

    def __str__(self) -> str:
        return f"{self.get_claim_type_display()} - {self.subject}"


class ClaimAttachment(TimeStampedModel):
    """Piece jointe d'une reclamation (photo, recu ou PDF, 10 Mo max).

    Plusieurs pieces peuvent etayer une meme reclamation. La validation du type
    et de la taille est faite au serialiseur ; les metadonnees (`original_name`,
    `content_type`, `size`) sont figees a l'upload par `services`.
    """

    claim = models.ForeignKey(
        Claim,
        on_delete=models.CASCADE,
        related_name="attachments",
    )
    file = models.FileField(upload_to="claims/attachments/")
    original_name = models.CharField(max_length=255, blank=True)
    content_type = models.CharField(max_length=100, blank=True)
    size = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["id"]
        verbose_name = "Piece jointe de reclamation"
        verbose_name_plural = "Pieces jointes de reclamation"

    def __str__(self) -> str:
        return self.original_name or self.file.name
