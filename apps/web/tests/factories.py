"""Un voyage reservable, monte en une ligne pour les tests du site."""
from datetime import timedelta

from django.utils import timezone

from apps.geography.tests.factories import CityFactory, StationFactory
from apps.routes.tests.factories import RouteFactory
from apps.trips.tests.factories import TripFactory
from apps.vehicles.tests.factories import VehicleFactory


def voyage_reservable(*, prix=6500, places=30, depart_dans_heures=26):
    """Build a bookable trip with named cities and stations.

    Args:
        prix: The seat price. Ses deux derniers chiffres choisissent le
            scenario rejoue par l'operateur simule.
        places: Seats still available.
        depart_dans_heures: Hours until departure.

    Returns:
        The trip, ready to be booked.
    """
    depart = CityFactory(name="Ouagadougou")
    arrivee = CityFactory(name="Bobo-Dioulasso")
    route = RouteFactory(
        origin_city=depart,
        destination_city=arrivee,
        origin_station=StationFactory(city=depart, name="Gare Ouaga-Inter"),
        destination_station=StationFactory(city=arrivee, name="Gare de Sarfalao"),
    )
    quand = timezone.now() + timedelta(hours=depart_dans_heures)
    return TripFactory(
        route=route,
        vehicle=VehicleFactory(company=route.company, total_seats=places),
        departure_time=quand,
        arrival_time=quand + timedelta(hours=5, minutes=30),
        registration_closes_at=quand,
        price=prix,
        available_seats=places,
    )
