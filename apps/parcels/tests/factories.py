import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import CityFactory, StationFactory
from apps.parcels.models import Parcel, ParcelStatus


class ParcelFactory(DjangoModelFactory):
    class Meta:
        model = Parcel

    company = factory.SubFactory(CompanyFactory)
    origin_city = factory.SubFactory(CityFactory)
    destination_city = factory.SubFactory(CityFactory)
    destination_station = factory.SubFactory(StationFactory)
    sender_name = "Issa KABORE"
    sender_phone = factory.Sequence(lambda n: f"+2267{n:07d}")
    recipient_name = "Fatou DIALLO"
    recipient_phone = factory.Sequence(lambda n: f"+2266{n:07d}")
    description = "Carton de pieces detachees"
    weight_kg = 5
    tariff = 2000
    tracking_number = factory.Sequence(lambda n: f"COL2026{n:06d}")
    status = ParcelStatus.REGISTERED
