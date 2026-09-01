import pytest
from django.db import IntegrityError

from apps.bookings.models import Booking, BookingStatus

from .factories import BookingFactory


@pytest.mark.django_db
def test_ticket_number_is_unique():
    BookingFactory(ticket_number="BF2026999999")
    with pytest.raises(IntegrityError):
        BookingFactory(ticket_number="BF2026999999")


@pytest.mark.django_db
def test_active_seat_is_unique_per_trip():
    booking = BookingFactory(seat_number="A3")
    with pytest.raises(IntegrityError):
        BookingFactory(trip=booking.trip, seat_number="A3")


@pytest.mark.django_db
def test_cancelled_seat_can_be_reused():
    booking = BookingFactory(seat_number="A3", status=BookingStatus.CANCELLED)
    # Le siege d'une reservation annulee redevient attribuable.
    reused = BookingFactory(trip=booking.trip, seat_number="A3")
    assert reused.pk != booking.pk


@pytest.mark.django_db
def test_passenger_name_property():
    booking = BookingFactory(first_name="Aminata", last_name="TRAORE")
    assert booking.passenger_name == "Aminata TRAORE"
