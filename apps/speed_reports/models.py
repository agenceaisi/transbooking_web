from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class SpeedReportStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    REVIEWED = "reviewed", "Examine"
    CLOSED = "closed", "Cloture"


class SpeedReportSeverity(models.TextChoices):
    LOW = "low", "Faible"
    MEDIUM = "medium", "Moyenne"
    HIGH = "high", "Grave"


class SpeedReport(TimeStampedModel):
    """Signalement d'un exces de vitesse par un voyageur.

    Horodate automatiquement a la creation. La position GPS est facultative
    (l'agent peut etre hors couverture). Cible une compagnie, eventuellement un
    voyage precis.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="speed_reports",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="speed_reports",
    )
    # Voyage concerne : facultatif (le voyageur peut ne pas savoir l'identifier).
    trip = models.ForeignKey(
        "trips.Trip",
        on_delete=models.SET_NULL,
        related_name="speed_reports",
        null=True,
        blank=True,
    )

    # Vitesse estimee en km/h (facultative).
    estimated_speed = models.PositiveIntegerField(null=True, blank=True)
    # Gravite estimee par le voyageur (Faible / Moyenne / Grave), facultative :
    # le voyageur ne connait pas la vitesse exacte mais peut juger la gravite.
    severity = models.CharField(
        max_length=10,
        choices=SpeedReportSeverity.choices,
        null=True,
        blank=True,
    )
    description = models.TextField(blank=True)

    # Position GPS facultative au moment du signalement.
    latitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )
    longitude = models.DecimalField(
        max_digits=9, decimal_places=6, null=True, blank=True
    )

    # Horodatage de l'evenement signale (defaut : maintenant, cf. PROMPT 08).
    reported_at = models.DateTimeField()

    status = models.CharField(
        max_length=20,
        choices=SpeedReportStatus.choices,
        default=SpeedReportStatus.PENDING,
    )

    class Meta:
        ordering = ["-reported_at"]
        verbose_name = "Signalement exces de vitesse"
        verbose_name_plural = "Signalements exces de vitesse"

    def __str__(self) -> str:
        return f"{self.company.name} - {self.reported_at:%Y-%m-%d %H:%M}"
