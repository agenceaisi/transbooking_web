"""Taches Celery de l'app bookings (SMS billet et rappel de depart)."""
from celery import shared_task
from django.utils import timezone

from utils.sms import send_sms
from utils.tasks import log_task_errors

from .models import Booking, BookingStatus


def _company_setting(booking: Booking, attr: str, default: bool = True) -> bool:
    """Return a company notification flag, defaulting when unconfigured.

    Args:
        booking: The booking whose company settings are read.
        attr: The boolean flag name on ``CompanyNotificationSettings``.
        default: Value returned when the company has no settings row.

    Returns:
        The configured flag, or ``default`` when no settings exist.
    """
    settings_obj = getattr(booking.trip.route.company, "notification_settings", None)
    if settings_obj is None:
        return default
    return getattr(settings_obj, attr, default)


@shared_task
@log_task_errors
def send_booking_confirmation_sms(booking_id: int) -> None:
    """Send the booking confirmation SMS once a payment is confirmed.

    Idempotent: rebuilds the same message from the booking each run and performs
    no state change, so a retry is harmless.

    Args:
        booking_id: Primary key of the paid booking.
    """
    booking = (
        Booking.objects.select_related("trip__route__company")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        return

    message = (
        f"Reservation confirmee. Billet {booking.ticket_number}, "
        f"siege {booking.seat_number}. Voyage du "
        f"{timezone.localtime(booking.trip.departure_time):%d/%m/%Y a %Hh%M}."
    )
    send_sms(booking.phone, message)


@shared_task
@log_task_errors
def send_departure_reminder_sms(booking_id: int) -> None:
    """Remind a passenger of an upcoming departure (~3h before).

    Scheduled with ``apply_async(eta=trip.departure_time - 3h)`` at payment
    confirmation. Skips silently when the company disabled the reminder, when the
    booking is no longer active, or when the trip is cancelled, so a stale ETA
    never sends a misleading SMS.

    Args:
        booking_id: Primary key of the booking to remind.
    """
    booking = (
        Booking.objects.select_related("trip__route__company")
        .filter(pk=booking_id)
        .first()
    )
    if booking is None:
        return

    if booking.status != BookingStatus.PAID:
        return
    if not _company_setting(booking, "sms_departure_reminder"):
        return

    trip = booking.trip
    from apps.trips.models import Trip

    if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
        return

    message = (
        f"Rappel : votre voyage (billet {booking.ticket_number}, "
        f"siege {booking.seat_number}) part le "
        f"{timezone.localtime(trip.departure_time):%d/%m/%Y a %Hh%M}. "
        f"Merci d'arriver 30 min avant."
    )
    send_sms(booking.phone, message)
