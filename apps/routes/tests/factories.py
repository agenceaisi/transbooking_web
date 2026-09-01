import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import CityFactory
from apps.routes.models import Route, RouteStop


class RouteFactory(DjangoModelFactory):
    class Meta:
        model = Route

    company = factory.SubFactory(CompanyFactory)
    origin_city = factory.SubFactory(CityFactory)
    destination_city = factory.SubFactory(CityFactory)
    distance_km = 350
    base_price = 5000
    duration_minutes = 300
    is_active = True


class RouteStopFactory(DjangoModelFactory):
    class Meta:
        model = RouteStop

    route = factory.SubFactory(RouteFactory)
    city = factory.SubFactory(CityFactory)
    stop_order = factory.Sequence(lambda n: n + 1)
    stop_price = 3000
