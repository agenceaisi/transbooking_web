import factory
from factory.django import DjangoModelFactory

from apps.bookings.tests.factories import BookingFactory
from apps.payments.models import Payment, PaymentMethod, PaymentStatus


class PaymentFactory(DjangoModelFactory):
    class Meta:
        model = Payment

    booking = factory.SubFactory(BookingFactory)
    amount = 5000
    method = PaymentMethod.CASH
    status = PaymentStatus.PENDING
