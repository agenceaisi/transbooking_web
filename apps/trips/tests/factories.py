from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.routes.tests.factories import RouteFactory
from apps.trips.models import Trip
from apps.vehicles.tests.factories import VehicleFactory


class TripFactory(DjangoModelFactory):
    class Meta:
        model = Trip

    route = factory.SubFactory(RouteFactory)
    vehicle = factory.SubFactory(VehicleFactory)
    departure_time = factory.LazyFunction(
        lambda: timezone.now() + timedelta(days=1)
    )
    price = 5000
    available_seats = 30
    status = Trip.TripStatus.SCHEDULED
