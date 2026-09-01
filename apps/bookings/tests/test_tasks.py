from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.tasks import (
    send_booking_confirmation_sms,
    send_departure_reminder_sms,
)
from apps.companies.tests.factories import CompanyNotificationSettingsFactory
from apps.trips.models import Trip
from apps.trips.tests.factories import TripFactory

from .factories import BookingFactory


@pytest.fixture
def sent(monkeypatch):
    """Capture (phone, message) tuples sent through the SMS gateway."""
    calls = []
    monkeypatch.setattr(
        "apps.bookings.tasks.send_sms",
        lambda phone, message: calls.append((phone, message)),
    )
    return calls


@pytest.mark.django_db
def test_confirmation_sms_sent_with_ticket_details(sent):
    booking = BookingFactory(status=BookingStatus.PAID)

    send_booking_confirmation_sms(booking.pk)

    assert len(sent) == 1
    phone, message = sent[0]
    assert phone == booking.phone
    assert booking.ticket_number in message


@pytest.mark.django_db
def test_confirmation_sms_missing_booking_is_noop(sent):
    send_booking_confirmation_sms(999999)
    assert sent == []


@pytest.mark.django_db
def test_departure_reminder_sent_when_enabled(sent):
    trip = TripFactory(departure_time=timezone.now() + timedelta(hours=3))
    CompanyNotificationSettingsFactory(
        company=trip.route.company, sms_departure_reminder=True
    )
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)

    send_departure_reminder_sms(booking.pk)

    assert len(sent) == 1
    assert booking.ticket_number in sent[0][1]


@pytest.mark.django_db
def test_departure_reminder_skipped_when_company_disabled(sent):
    trip = TripFactory(departure_time=timezone.now() + timedelta(hours=3))
    CompanyNotificationSettingsFactory(
        company=trip.route.company, sms_departure_reminder=False
    )
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)

    send_departure_reminder_sms(booking.pk)

    assert sent == []


@pytest.mark.django_db
def test_departure_reminder_skipped_for_unpaid_booking(sent):
    booking = BookingFactory(status=BookingStatus.PENDING)
    send_departure_reminder_sms(booking.pk)
    assert sent == []


@pytest.mark.django_db
def test_departure_reminder_skipped_for_cancelled_trip(sent):
    trip = TripFactory(status=Trip.TripStatus.CANCELLED)
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    send_departure_reminder_sms(booking.pk)
    assert sent == []
