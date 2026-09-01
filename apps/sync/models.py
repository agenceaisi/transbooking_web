from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class SyncStatus(models.TextChoices):
    SUCCESS = "success", "Succes"
    PARTIAL = "partial", "Partiel"
    ERROR = "error", "Erreur"


class SyncEntity(models.TextChoices):
    BOOKING = "booking", "Reservation"
    PARCEL = "parcel", "Colis"
    VALIDATION = "validation", "Embarquement"


class SyncConflictType(models.TextChoices):
    SEAT_CONFLICT = "seat_conflict", "Conflit de siege"
    TRIP_FULL = "trip_full", "Voyage complet"
    TRIP_UNAVAILABLE = "trip_unavailable", "Voyage indisponible"
    DUPLICATE = "duplicate", "Doublon ignore"
    INVALID = "invalid", "Donnee invalide"


class SyncLog(TimeStampedModel):
    """Journal d'une synchronisation des donnees hors ligne d'un agent.

    Chaque appel a `POST /api/v1/agent/sync/` cree un `SyncLog` resumant les
    enregistrements integres et les conflits rencontres. Sert d'historique et de
    base au nettoyage periodique (cf. PROMPT 12 `cleanup_old_sync_logs`).
    """

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sync_logs",
    )
    bookings_synced = models.PositiveIntegerField(default=0)
    parcels_synced = models.PositiveIntegerField(default=0)
    validations_synced = models.PositiveIntegerField(default=0)
    parcel_notifications_synced = models.PositiveIntegerField(default=0)
    cancellations_synced = models.PositiveIntegerField(default=0)
    # Conflits resolus automatiquement (siege reattribue).
    conflicts_count = models.PositiveIntegerField(default=0)
    # Enregistrements rejetes (voyage complet, annule, donnee invalide).
    errors_count = models.PositiveIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=SyncStatus.choices,
        default=SyncStatus.SUCCESS,
    )
    error_details = models.TextField(blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Journal de synchronisation"
        verbose_name_plural = "Journaux de synchronisation"

    def __str__(self) -> str:
        return f"Sync {self.agent_id} - {self.created_at:%Y-%m-%d %H:%M}"


class SyncConflict(TimeStampedModel):
    """Anomalie rencontree lors d'une synchronisation hors ligne.

    Un conflit de siege est resolu automatiquement (`resolved=True`, prochain
    siege libre attribue) ; les autres anomalies sont rejetees (`resolved=False`)
    et retournees a l'agent. La `resolution` decrit l'action en francais clair
    (cf. business_rules.md §6).
    """

    sync_log = models.ForeignKey(
        SyncLog,
        on_delete=models.CASCADE,
        related_name="conflicts",
    )
    entity = models.CharField(
        max_length=20,
        choices=SyncEntity.choices,
        default=SyncEntity.BOOKING,
    )
    conflict_type = models.CharField(
        max_length=20,
        choices=SyncConflictType.choices,
    )
    # Identifiant fonctionnel de l'enregistrement (ticket_number / tracking_number).
    reference = models.CharField(max_length=30, blank=True)
    original_seat = models.CharField(max_length=10, blank=True)
    assigned_seat = models.CharField(max_length=10, blank=True)
    # Description en francais de la resolution (jamais l'id DB).
    resolution = models.TextField()
    # True : anomalie resolue automatiquement. False : enregistrement rejete.
    resolved = models.BooleanField(default=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Conflit de synchronisation"
        verbose_name_plural = "Conflits de synchronisation"

    def __str__(self) -> str:
        return f"{self.get_conflict_type_display()} - {self.reference}"
