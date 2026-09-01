from django.core.exceptions import ValidationError

from .models import Vehicle

#: Confort par palier de vehicule (`Vehicle.vehicle_type`), du moins au plus
#: equipe — chaque palier reprend les codes du precedent et en ajoute.
#: `Vehicle` ne porte aucun champ d'equipements : c'est l'unique source de
#: verite pour en deriver le confort, a la fois a l'affichage (cf.
#: `web.templatetags.transbooking.confort`) et au filtrage (cf.
#: `trips.services.search_trips`/`search_facets`) — les deux doivent
#: toujours s'accorder sur ce qu'un palier offre.
COMFORT_BY_TIER: dict[str, tuple[str, ...]] = {
    "standard": ("sieges", "bagages", "clim"),
    "vip": ("sieges", "bagages", "clim", "prises", "wifi"),
    "vvip": (
        "sieges", "bagages", "clim", "prises", "wifi",
        "toilettes", "collation", "divertissement",
    ),
}

#: Paliers connus, du plus modeste au plus equipe.
TIERS: tuple[str, ...] = tuple(COMFORT_BY_TIER)


def tiers_with_comfort(codes) -> list[str]:
    """List the vehicle tiers whose amenities cover every code requested.

    Args:
        codes: Comfort codes to require (e.g. ``["wifi", "toilettes"]``).
            An empty or falsy value matches every tier.

    Returns:
        The subset of `TIERS` offering all of `codes`, tiers order preserved.
    """
    requis = {c for c in (codes or []) if c}
    if not requis:
        return list(TIERS)
    return [tier for tier in TIERS if requis.issubset(COMFORT_BY_TIER[tier])]


def _all_seat_numbers(vehicle: Vehicle) -> list[str]:
    """Return every commercialisable seat label for a vehicle.

    Seats come from ``vehicle.seat_plan["layout"]`` when a plan is configured,
    otherwise they are generated sequentially from ``total_seats``. Seats listed
    in ``seat_plan["reserved"]`` (driver, crew...) are excluded.

    Args:
        vehicle: The vehicle whose seats are listed.

    Returns:
        Ordered list of seat labels as strings.
    """
    plan = vehicle.seat_plan or {}
    layout = plan.get("layout")
    if layout:
        seats = [str(seat) for row in layout for seat in row]
    else:
        seats = [str(i) for i in range(1, vehicle.total_seats + 1)]

    reserved = {str(seat) for seat in plan.get("reserved", [])}
    return [seat for seat in seats if seat not in reserved]


def _booked_seat_numbers(trip) -> set[str]:
    """Return seat labels already taken on a trip.

    Resilient to the bookings app not being wired yet (PROMPT 05): if the
    ``bookings`` reverse relation is absent, no seat is considered taken.

    Args:
        trip: The trip to inspect, or ``None``.

    Returns:
        Set of taken seat labels (cancelled bookings excluded).
    """
    if trip is None:
        return set()

    bookings = getattr(trip, "bookings", None)
    if bookings is None:
        return set()

    # Les reservations annulees liberent leur siege.
    queryset = bookings.exclude(status="cancelled")
    return {str(seat) for seat in queryset.values_list("seat_number", flat=True)}


def get_available_seats(vehicle: Vehicle, trip=None) -> list[str]:
    """List the seat labels still bookable on a trip.

    Args:
        vehicle: The vehicle assigned to the trip.
        trip: The trip whose taken seats are removed. ``None`` returns the
            full commercialisable plan.

    Returns:
        Ordered list of free seat labels.
    """
    taken = _booked_seat_numbers(trip)
    return [seat for seat in _all_seat_numbers(vehicle) if seat not in taken]


def next_available_seat(vehicle: Vehicle, trip=None) -> str:
    """Return the smallest free seat on a trip (used for auto-assignment).

    Enregistrement (guichet et dernière minute confondus) attribue toujours le
    plus petit numéro de siège encore libre, sur l'échelle ``1..total_seats``
    (cf. requetes agent module §4). Pour un véhicule sans plan de sièges
    personnalisé, les étiquettes sont des entiers : le minimum numérique est
    calculé explicitement plutôt que de dépendre de l'ordre d'itération. Pour
    un plan personnalisé (étiquettes alphanumériques, ex. ``"A3"``), l'ordre du
    plan fait foi (pas d'échelle numérique à comparer).

    Args:
        vehicle: The vehicle assigned to the trip.
        trip: The trip to assign a seat on.

    Returns:
        The smallest free seat label.

    Raises:
        ValidationError: If no seat is available.
    """
    seats = get_available_seats(vehicle, trip)
    if not seats:
        raise ValidationError("Aucun siege disponible sur ce vehicule.")
    if not (vehicle.seat_plan or {}).get("layout") and all(
        seat.isdigit() for seat in seats
    ):
        return str(min(int(seat) for seat in seats))
    return seats[0]


def ensure_vehicle_assignable(vehicle: Vehicle) -> None:
    """Guard that a vehicle may be assigned to a new trip.

    Args:
        vehicle: The vehicle to check.

    Raises:
        ValidationError: If the vehicle is not in the ``active`` status.
    """
    if vehicle.status != Vehicle.VehicleStatus.ACTIVE:
        raise ValidationError(
            f"Le vehicule {vehicle.registration} n'est pas disponible "
            f"(statut : {vehicle.get_status_display()})."
        )


def set_maintenance(vehicle: Vehicle) -> Vehicle:
    """Move a vehicle to the maintenance status.

    Args:
        vehicle: The vehicle to update.

    Returns:
        The updated vehicle.
    """
    vehicle.status = Vehicle.VehicleStatus.MAINTENANCE
    vehicle.save(update_fields=["status", "updated_at"])
    return vehicle


def set_active(vehicle: Vehicle) -> Vehicle:
    """Return a vehicle to service (active status).

    Args:
        vehicle: The vehicle to update.

    Returns:
        The updated vehicle.
    """
    vehicle.status = Vehicle.VehicleStatus.ACTIVE
    vehicle.save(update_fields=["status", "updated_at"])
    return vehicle
