from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class NotificationType(models.TextChoices):
    BOOKING = "booking", "Reservation"
    PAYMENT = "payment", "Paiement"
    PARCEL = "parcel", "Colis"
    CLAIM = "claim", "Reclamation"
    REVIEW = "review", "Avis"
    TRIP = "trip", "Voyage"
    MESSAGE = "message", "Message"
    SYSTEM = "system", "Systeme"


class Notification(TimeStampedModel):
    """Notification in-app destinee a un utilisateur.

    Creee exclusivement via `services.notify()` depuis les autres apps
    (bookings, parcels, claims...) plutot qu'en ligne, afin de centraliser
    la logique de notification.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    type = models.CharField(
        max_length=20,
        choices=NotificationType.choices,
        default=NotificationType.SYSTEM,
    )
    title = models.CharField(max_length=200)
    body = models.TextField(blank=True)
    is_read = models.BooleanField(default=False)

    # Lien polymorphe leger vers l'objet concerne (sans GenericForeignKey) :
    # permet au front d'ouvrir la bonne page (ex: reference_type="booking", reference_id=42).
    reference_id = models.PositiveIntegerField(null=True, blank=True)
    reference_type = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        indexes = [
            models.Index(fields=["user", "is_read"]),
        ]

    def __str__(self) -> str:
        return f"{self.title} -> {self.user_id}"
