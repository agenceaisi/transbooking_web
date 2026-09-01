import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.vehicles.models import Vehicle


class VehicleFactory(DjangoModelFactory):
    class Meta:
        model = Vehicle

    company = factory.SubFactory(CompanyFactory)
    registration = factory.Sequence(lambda n: f"11-AA-{n:04d}")
    brand = "Toyota"
    model = "Coaster"
    vehicle_type = "bus"
    total_seats = 30
    status = Vehicle.VehicleStatus.ACTIVE
