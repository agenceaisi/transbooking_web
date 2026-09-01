import pytest

from apps.routes.models import Route, RouteStop
from apps.routes.services import duplicate_reverse_route

from .factories import RouteFactory, RouteStopFactory


@pytest.mark.django_db
def test_duplicate_reverse_route_swaps_cities_and_reverses_stops():
    route = RouteFactory()
    RouteStopFactory(route=route, stop_order=1, stop_price=2000)
    RouteStopFactory(route=route, stop_order=2, stop_price=4000)

    reverse = duplicate_reverse_route(route)

    assert reverse.pk != route.pk
    assert reverse.origin_city == route.destination_city
    assert reverse.destination_city == route.origin_city
    assert reverse.base_price == route.base_price

    stops = list(reverse.stops.order_by("stop_order"))
    assert [s.stop_order for s in stops] == [1, 2]
    # L'ordre des escales est inverse : la derniere escale aller (4000) passe en premiere.
    assert [s.stop_price for s in stops] == [4000, 2000]


@pytest.mark.django_db
def test_duplicate_reverse_route_without_stops():
    route = RouteFactory()

    reverse = duplicate_reverse_route(route)

    assert reverse.stops.count() == 0
    assert Route.objects.count() == 2
    assert RouteStop.objects.count() == 0
