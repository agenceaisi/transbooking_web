"""Taches Celery de l'app trips (cloture automatique des voyages)."""
from celery import shared_task

from utils.tasks import log_task_errors

from .services import close_expired_registrations


@shared_task
@log_task_errors
def close_expired_trip_registrations() -> int:
    """Bascule vers `completed` tout voyage dont la cloture est passee.

    Tourne toutes les 1-2 minutes (cf. requetes agent module §1). Idempotent :
    un voyage deja `completed` n'est plus selectionne au tour suivant.

    Returns:
        The number of trips flipped to `completed`.
    """
    return close_expired_registrations()
