import factory
from factory.django import DjangoModelFactory

from apps.bookings.models import Baggage, BaggageLocation, Booking, BookingStatus
from apps.trips.tests.factories import TripFactory
from apps.users.tests.factories import UserFactory


class BookingFactory(DjangoModelFactory):
    class Meta:
        model = Booking

    trip = factory.SubFactory(TripFactory)
    user = factory.SubFactory(UserFactory)
    first_name = "Aminata"
    last_name = "TRAORE"
    phone = factory.Sequence(lambda n: f"+2267{n:07d}")
    seat_number = factory.Sequence(lambda n: str(n + 1))
    amount = 5000
    payment_method = "cash"
    ticket_number = factory.Sequence(lambda n: f"BF2026{n:06d}")
    status = BookingStatus.PAID


class BaggageFactory(DjangoModelFactory):
    class Meta:
        model = Baggage

    booking = factory.SubFactory(BookingFactory)
    label = "Valise rigide"
    tag = factory.Sequence(lambda n: f"TB-B-{n + 1:04d}")
    weight_kg = 12.0
    location = BaggageLocation.HOLD
