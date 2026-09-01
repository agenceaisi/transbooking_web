"""Celery application configuration."""
import os

from celery import Celery
from celery.schedules import crontab


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.dev")

app = Celery("transbooking")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

# Planification des taches periodiques (Celery beat). Les heures sont
# interpretees dans CELERY_TIMEZONE (= Africa/Ouagadougou, soit l'heure locale BF).
app.conf.beat_schedule = {
    # Verifie chaque jour a 08h00 les abonnements (rappel J-7, expiration).
    "check-expiring-subscriptions-daily": {
        "task": "apps.subscriptions.tasks.check_expiring_subscriptions",
        "schedule": crontab(hour=8, minute=0),
    },
    # Purge hebdomadaire des journaux de sync, le dimanche a 02h00.
    "cleanup-old-sync-logs-weekly": {
        "task": "apps.sync.tasks.cleanup_old_sync_logs",
        "schedule": crontab(hour=2, minute=0, day_of_week="sunday"),
    },
    # Cloture les voyages dont l'enregistrement est ferme (registration_closes_at
    # passe), toutes les 2 minutes (cf. requetes agent module §1).
    "close-expired-trip-registrations": {
        "task": "apps.trips.tasks.close_expired_trip_registrations",
        "schedule": crontab(minute="*/2"),
    },
}
