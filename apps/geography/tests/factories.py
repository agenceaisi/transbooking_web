import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.geography.models import City, Station


class CityFactory(DjangoModelFactory):
    class Meta:
        model = City

    name = factory.Sequence(lambda n: f"Ville {n}")
    region = "Centre"


class StationFactory(DjangoModelFactory):
    class Meta:
        model = Station

    company = factory.SubFactory(CompanyFactory)
    city = factory.SubFactory(CityFactory)
    name = factory.Sequence(lambda n: f"Gare {n}")
    address = "Avenue de la Nation"
