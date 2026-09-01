from django.db import transaction

from .models import Route, RouteStop


@transaction.atomic
def duplicate_reverse_route(route: Route) -> Route:
    """Create the reverse route of an existing one (same parameters).

    The new route swaps origin/destination cities and stations, keeps the same
    pricing and distance, and rebuilds the stops in reverse order so the partial
    prices still grow with the travelled distance.

    Args:
        route: The route to mirror.

    Returns:
        The newly created reverse route.
    """
    reverse = Route.objects.create(
        company=route.company,
        origin_city=route.destination_city,
        destination_city=route.origin_city,
        origin_station=route.destination_station,
        destination_station=route.origin_station,
        distance_km=route.distance_km,
        base_price=route.base_price,
        duration_minutes=route.duration_minutes,
        is_active=route.is_active,
    )

    # On inverse l'ordre des escales : la derniere escale aller devient la
    # premiere escale retour.
    for new_order, stop in enumerate(reversed(list(route.stops.all())), start=1):
        RouteStop.objects.create(
            route=reverse,
            city=stop.city,
            stop_order=new_order,
            stop_price=stop.stop_price,
        )
    return reverse
