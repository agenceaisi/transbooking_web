"""Taches Celery de l'app parcels (SMS d'enregistrement et d'arrivee)."""
from celery import shared_task

from utils.sms import send_sms
from utils.tasks import log_task_errors

from .models import NotificationMethod, Parcel, ParcelNotification, ParcelStatus


def _parcel_setting(parcel: Parcel, attr: str, default: bool = True) -> bool:
    """Return a company notification flag, defaulting when unconfigured.

    Args:
        parcel: The parcel whose company settings are read.
        attr: The boolean flag name on ``CompanyNotificationSettings``.
        default: Value returned when the company has no settings row.

    Returns:
        The configured flag, or ``default`` when no settings exist.
    """
    settings_obj = getattr(parcel.company, "notification_settings", None)
    if settings_obj is None:
        return default
    return getattr(settings_obj, attr, default)


@shared_task
@log_task_errors
def send_parcel_dispatch_sms(parcel_id: int) -> None:
    """Tell the recipient a parcel has been registered for them.

    Idempotent: rebuilds the same message and changes no state, so a retry only
    resends the dispatch notice. This is not a ``ParcelNotification`` and never
    consumes the single-arrival-SMS rule (cf. business_rules.md §3).

    Args:
        parcel_id: Primary key of the registered parcel.
    """
    parcel = (
        Parcel.objects.select_related("destination_city", "company")
        .filter(pk=parcel_id)
        .first()
    )
    if parcel is None:
        return

    message = (
        f"Un colis vous est destine (suivi {parcel.tracking_number}). "
        f"Vous serez prevenu a son arrivee a {parcel.destination_city.name}."
    )
    send_sms(parcel.recipient_phone, message)


@shared_task
@log_task_errors
def send_parcel_arrival_sms(parcel_id: int) -> None:
    """Notify the recipient that a parcel has arrived, once.

    Triggered when a parcel status becomes ``arrived``. Idempotent and aligned
    with the anti-duplicate rule: skips when an arrival SMS already exists or
    when the company disabled arrival SMS. On success it records a
    ``ParcelNotification`` and moves the parcel to ``notified``.

    Args:
        parcel_id: Primary key of the arrived parcel.
    """
    parcel = (
        Parcel.objects.select_related("destination_city", "company")
        .filter(pk=parcel_id)
        .first()
    )
    if parcel is None:
        return

    if not _parcel_setting(parcel, "sms_parcel_arrival"):
        return

    # Garde-fou anti-doublon (cf. business_rules.md §3) : un seul SMS d'arrivee.
    already_sent = ParcelNotification.objects.filter(
        parcel=parcel, method=NotificationMethod.SMS
    ).exists()
    if already_sent:
        return

    message = (
        f"Votre colis {parcel.tracking_number} est arrive a "
        f"{parcel.destination_city.name}. Veuillez venir le retirer."
    )
    send_sms(parcel.recipient_phone, message)

    ParcelNotification.objects.create(
        parcel=parcel,
        method=NotificationMethod.SMS,
        message=message,
        sent_by=None,
    )

    if parcel.status != ParcelStatus.COLLECTED:
        parcel.status = ParcelStatus.NOTIFIED
        parcel.save(update_fields=["status", "updated_at"])
