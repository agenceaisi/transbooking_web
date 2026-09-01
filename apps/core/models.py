from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class GlobalSetting(TimeStampedModel):
    """Parametre de configuration global de la plateforme (paire cle/valeur).

    Gere par le super admin. Cles prevues (cf. mcd.md §15) :
    `global_commission_rate`, `sms_provider`, `sms_api_key`,
    `platform_maintenance_mode`. La valeur est stockee en texte et interpretee
    par l'appelant (ex: Decimal pour le taux de commission).
    """

    key = models.CharField(max_length=100, unique=True)
    value = models.TextField()
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["key"]
        verbose_name = "Parametre global"
        verbose_name_plural = "Parametres globaux"

    def __str__(self) -> str:
        return self.key


class ActivityLog(TimeStampedModel):
    """Journal d'audit des actions sensibles de la plateforme.

    `user` NULL = action systeme (tache Celery, cron). `details` conserve un
    instantane avant/apres en JSON. Cf. mcd.md §15.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="activity_logs",
        null=True,
        blank=True,
    )
    action = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=50, blank=True)
    entity_id = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Journal d'activite"
        verbose_name_plural = "Journaux d'activite"
        indexes = [
            models.Index(fields=["entity_type", "entity_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.action} ({self.user_id or 'systeme'})"
