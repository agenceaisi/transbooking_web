"""Taches Celery de l'app sync (entretien des journaux de synchronisation)."""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from utils.tasks import log_task_errors

from .models import SyncLog

# Duree de retention des journaux de synchronisation hors ligne.
SYNC_LOG_RETENTION_DAYS = 30


@shared_task
@log_task_errors
def cleanup_old_sync_logs() -> int:
    """Delete sync logs older than 30 days (weekly maintenance).

    Idempotent: re-running simply finds nothing left to delete. Related
    ``SyncConflict`` rows cascade with their ``SyncLog``.

    Returns:
        The number of ``SyncLog`` rows deleted.
    """
    cutoff = timezone.now() - timedelta(days=SYNC_LOG_RETENTION_DAYS)
    deleted, _ = SyncLog.objects.filter(created_at__lt=cutoff).delete()
    return deleted
