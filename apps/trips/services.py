from datetime import datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Avg, Count, IntegerField, Max, Min, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from apps.routes.models import Route, RouteStop
from apps.vehicles.models import Vehicle
from apps.vehicles.services import ensure_vehicle_assignable, tiers_with_comfort
from utils.sms import send_sms

from .exceptions import TripAlreadyCompleted
from .models import Trip

# Statuts encore ouverts a l'enregistrement, eligibles a la cloture automatique.
_OPEN_STATUSES = {
    Trip.TripStatus.SCHEDULED,
    Trip.TripStatus.IN_PROGRESS,
    Trip.TripStatus.DELAYED,
}


def with_read_annotations(queryset):
    """Annotate a ``Trip`` queryset with the fields ``TripReadSerializer`` needs.

    Adds ``company_rating`` (the trip company's average public review score) and
    ``stops_count`` (number of intermediate stops on the route) as subqueries so
    the read serializer can expose the company rating and the direct/stops badge
    without one aggregation query per row.

    Args:
        queryset: A ``Trip`` queryset (typically already ``select_related``).

    Returns:
        The annotated queryset.
    """
    # Import local pour eviter un cycle trips.services <-> reviews.services.
    from apps.reviews.services import company_rating_subquery

    stops = (
        RouteStop.objects.filter(route_id=OuterRef("route_id"))
        .values("route_id")
        .annotate(count=Count("id"))
        .values("count")[:1]
    )
    return queryset.annotate(
        company_rating=company_rating_subquery("route__company_id"),
        stops_count=Coalesce(Subquery(stops, output_field=IntegerField()), 0),
    )


#: Ordres de tri proposes au voyageur. La duree n'y figure pas : elle se deduit
#: de `arrival_time`, qui est facultatif — trier dessus relegerait en fin de
#: liste tous les voyages dont l'heure d'arrivee n'est pas renseignee.
ORDRES_RECHERCHE = {
    "prix": "price",
    "depart": "departure_time",
    "note": "-company_rating",
}

#: Tranches horaires du filtre « Heure de depart » : code, libelle, bornes
#: [debut, fin[ en heure locale (``None`` = pas de borne sur ce cote).
HEURES_TRANCHES = (
    ("avant-06", "Avant 06:00", None, 6),
    ("06-12", "06:00 – 12:00", 6, 12),
    ("12-18", "12:00 – 18:00", 12, 18),
    ("apres-18", "Après 18:00", 18, None),
)

#: Regroupements du filtre « Trajet », par nombre d'escales.
ESCALES_BUCKETS = (
    ("direct", "Direct, sans escale"),
    ("1", "Une escale"),
    ("2+", "Deux escales ou plus"),
)

#: Sous-ensemble d'équipements propose au filtre « Services à bord ». Les
#: codes viennent de `vehicles.services.COMFORT_BY_TIER` — un service coche
#: qu'aucun palier n'isole (ex. la climatisation, presente partout) laisse
#: simplement le resultat inchange, ce qui est la bonne reponse : elle est
#: bien à bord.
SERVICES_FACETTES = (
    ("clim", "Climatisation"),
    ("wifi", "Wi-Fi"),
    ("prises", "Prise USB"),
    ("toilettes", "Toilettes"),
)

#: Paliers de vehicule proposes au filtre « Type de voyage ».
PALIERS_FACETTES = (
    ("standard", "Standard"),
    ("vip", "VIP"),
    ("vvip", "VVIP"),
)

#: Seuils du filtre « Note des voyageurs » : code, libelle, seuil minimal.
NOTES_SEUILS = (
    ("4.5", "4,5 et plus", Decimal("4.5")),
    ("4.0", "4,0 et plus", Decimal("4.0")),
    ("3.5", "3,5 et plus", Decimal("3.5")),
)


def _dans_tranche_horaire(queryset, debut: int | None, fin: int | None):
    """Restrict a ``Trip`` queryset to a local time-of-day window.

    Args:
        queryset: An already-annotated ``Trip`` queryset.
        debut: Minimum departure hour (inclusive), or ``None``.
        fin: Maximum departure hour (exclusive), or ``None``.

    Returns:
        The filtered queryset.
    """
    if debut is not None:
        queryset = queryset.filter(departure_time__hour__gte=debut)
    if fin is not None:
        queryset = queryset.filter(departure_time__hour__lt=fin)
    return queryset


def _bucket_escales(code: str) -> Q:
    """Translate one ``ESCALES_BUCKETS`` code into a stop-count condition.

    Args:
        code: ``"direct"``, ``"1"`` or ``"2+"``.

    Returns:
        The matching ``Q`` object (an empty, always-true ``Q`` for an
        unrecognised code, so a stray value never hides every result).
    """
    if code == "direct":
        return Q(stops_count=0)
    if code == "1":
        return Q(stops_count=1)
    if code == "2+":
        return Q(stops_count__gte=2)
    return Q()


def search_trips(
    *,
    origin_city_id: int | None = None,
    destination_city_id: int | None = None,
    origin_slug: str = "",
    destination_slug: str = "",
    date=None,
    passengers: int | None = None,
    min_price=None,
    max_price=None,
    company_id: int | None = None,
    company_ids=None,
    min_rating=None,
    direct: bool = False,
    heure: str | None = None,
    escales=None,
    services=None,
    vehicle_types=None,
    order: str = "depart",
):
    """Return the schedulable trips matching a public search.

    Source unique de la recherche : l'API publique et les pages du site
    l'appellent tous les deux. Une regle corrigee ici l'est des deux cotes.

    Les criteres arrivent **deja types** : c'est a l'appelant (vue DRF ou vue
    Django) de valider ce qu'il recoit et de traduire une saisie invalide en
    erreur utilisateur. Le service, lui, ne parle que le langage du domaine.

    Args:
        origin_city_id: Departure city, by identifier.
        destination_city_id: Arrival city, by identifier.
        origin_slug: Departure city, by public slug (used by the web pages).
        destination_slug: Arrival city, by public slug.
        date: Departure date.
        passengers: Minimum number of seats still available.
        min_price: Lower price bound.
        max_price: Upper price bound.
        company_id: Restrict to one company (kept for the public API).
        company_ids: Restrict to any of these companies — the results page's
            multi-select « Compagnie » filter.
        min_rating: Minimum average company rating.
        direct: Keep only trips without any intermediate stop (kept for the
            public API — the results page uses `escales` instead).
        heure: A `HEURES_TRANCHES` code restricting the departure time of day.
        escales: `ESCALES_BUCKETS` codes to accept (union — any match keeps
            the trip).
        services: Comfort codes every kept trip's vehicle must all offer
            (cf. `vehicles.services.tiers_with_comfort`).
        vehicle_types: Vehicle tiers to accept (``standard``/``vip``/``vvip``).
        order: A key of ``ORDRES_RECHERCHE``.

    Returns:
        An annotated, ordered ``Trip`` queryset.
    """
    queryset = with_read_annotations(
        Trip.objects.filter(
            status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
            departure_time__gte=timezone.now(),
        ).select_related(
            "route__company",
            "route__origin_city",
            "route__destination_city",
            "route__origin_station",
            "route__destination_station",
            "vehicle",
        )
    )

    if origin_city_id:
        queryset = queryset.filter(route__origin_city_id=origin_city_id)
    elif origin_slug:
        queryset = queryset.filter(route__origin_city__slug=origin_slug)

    if destination_city_id:
        queryset = queryset.filter(route__destination_city_id=destination_city_id)
    elif destination_slug:
        queryset = queryset.filter(route__destination_city__slug=destination_slug)

    if date:
        queryset = queryset.filter(departure_time__date=date)
    if passengers:
        queryset = queryset.filter(available_seats__gte=passengers)
    if min_price is not None:
        queryset = queryset.filter(price__gte=min_price)
    if max_price is not None:
        queryset = queryset.filter(price__lte=max_price)
    if company_id:
        queryset = queryset.filter(route__company_id=company_id)
    if company_ids:
        queryset = queryset.filter(route__company_id__in=company_ids)
    if min_rating is not None:
        queryset = queryset.filter(company_rating__gte=min_rating)
    if direct:
        queryset = queryset.filter(stops_count=0)
    if heure:
        tranche = next((t for t in HEURES_TRANCHES if t[0] == heure), None)
        if tranche:
            queryset = _dans_tranche_horaire(queryset, tranche[2], tranche[3])
    if escales:
        combinaison = Q()
        for code in escales:
            combinaison |= _bucket_escales(code)
        queryset = queryset.filter(combinaison)
    if services:
        queryset = queryset.filter(vehicle__vehicle_type__in=tiers_with_comfort(services))
    if vehicle_types:
        queryset = queryset.filter(vehicle__vehicle_type__in=vehicle_types)

    tri = ORDRES_RECHERCHE.get(order, "departure_time")
    # Second critere systematique : a prix egal, le depart le plus proche
    # d'abord. Sans lui, l'ordre de deux voyages au meme prix depend du plan
    # d'execution de PostgreSQL et change d'une page a l'autre.
    return queryset.order_by(tri, "departure_time")


def search_facets(
    *,
    origin_slug: str,
    destination_slug: str,
    date,
    passengers: int | None = None,
    company_ids=None,
    heure: str | None = None,
    escales=None,
    services=None,
    vehicle_types=None,
    note: str | None = None,
) -> dict:
    """Build the results-page filter rail: one group per facet, pre-counted.

    Chaque groupe compte sur le **meme jour de base** (origine, destination,
    date, voyageurs) — jamais sur le resultat deja filtre par un autre facet.
    Sinon, cocher « Climatisation » ferait disparaitre les compagnies qui
    n'exploitent que des VVIP, et la case deviendrait impossible a decocher :
    plus aucune ligne ne resterait pour la faire reapparaitre.

    Args:
        origin_slug: Departure city slug.
        destination_slug: Arrival city slug.
        date: Departure date.
        passengers: Minimum seats still available.
        company_ids: Currently selected company ids (as strings — straight
            from the query string), used only to flag each option `actif`.
        heure: Currently selected `HEURES_TRANCHES` code.
        escales: Currently selected `ESCALES_BUCKETS` codes.
        services: Currently selected comfort codes.
        vehicle_types: Currently selected tier codes.
        note: Currently selected `NOTES_SEUILS` code.

    Returns:
        ``{"compagnies", "heures", "escales", "services", "paliers", "notes",
        "prix_plancher", "prix_plafond"}`` — every group a list of
        ``{"code"/"id", "libelle"/"nom", "nombre", "actif"}``, plus the day's
        actual price range for the price filter's slider.
    """
    base = with_read_annotations(
        Trip.objects.filter(
            status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
            departure_time__gte=timezone.now(),
            route__origin_city__slug=origin_slug,
            route__destination_city__slug=destination_slug,
            departure_time__date=date,
        )
    )
    if passengers:
        base = base.filter(available_seats__gte=passengers)

    company_ids = set(company_ids or [])
    compagnies = [
        {
            "id": row["route__company_id"],
            "nom": row["route__company__name"],
            "nombre": row["nombre"],
            "actif": str(row["route__company_id"]) in company_ids,
        }
        for row in base.values("route__company_id", "route__company__name")
        .annotate(nombre=Count("id"))
        .order_by("route__company__name")
    ]

    heures = [
        {
            "code": code,
            "libelle": libelle,
            "nombre": _dans_tranche_horaire(base, debut, fin).count(),
            "actif": code == heure,
        }
        for code, libelle, debut, fin in HEURES_TRANCHES
    ]

    escales = set(escales or [])
    escales_options = [
        {
            "code": code,
            "libelle": libelle,
            "nombre": base.filter(_bucket_escales(code)).count(),
            "actif": code in escales,
        }
        for code, libelle in ESCALES_BUCKETS
    ]

    services = set(services or [])
    services_options = [
        {
            "code": code,
            "libelle": libelle,
            "nombre": base.filter(vehicle__vehicle_type__in=tiers_with_comfort([code])).count(),
            "actif": code in services,
        }
        for code, libelle in SERVICES_FACETTES
    ]

    vehicle_types = set(vehicle_types or [])
    paliers = [
        {
            "code": code,
            "libelle": libelle,
            "nombre": base.filter(vehicle__vehicle_type=code).count(),
            "actif": code in vehicle_types,
        }
        for code, libelle in PALIERS_FACETTES
    ]

    notes = [
        {
            "code": code,
            "libelle": libelle,
            "nombre": base.filter(company_rating__gte=seuil).count(),
            "actif": code == note,
        }
        for code, libelle, seuil in NOTES_SEUILS
    ]

    bornes = base.aggregate(plancher=Min("price"), plafond=Max("price"))

    return {
        "compagnies": compagnies,
        "heures": heures,
        "escales": escales_options,
        "services": services_options,
        "paliers": paliers,
        "notes": notes,
        "prix_plancher": bornes["plancher"],
        "prix_plafond": bornes["plafond"],
    }


def axis_overview(
    *, origin_slug: str = "", days: int = 7, limit: int = 8
) -> list[dict]:
    """Summarise the busiest origin-destination pairs over the coming days.

    Utilise par la page d'accueil pour les blocs « Destinations » et « Combien
    coute un trajet ? » : la meme agregation sert les deux, l'un restreint a une
    ville de depart, l'autre non. Sans table de recherches, l'affluence des
    departs planifies est le meilleur indicateur disponible de ce qui interesse
    les voyageurs (cf. audit backend accueil).

    Args:
        origin_slug: Restrict to axes departing from this city. Empty for all.
        days: Size of the forward-looking window, in days.
        limit: Maximum number of axes returned.

    Returns:
        Dicts ordered by trip volume (busiest first), each with
        ``origin_city``/``destination_city`` (id, name, slug), ``min_price``,
        ``avg_price``, ``min_duration``/``max_duration`` (minutes, possibly
        ``None``), ``trips_per_day`` (rounded, at least 1) and ``trip_count``.
    """
    now = timezone.now()
    queryset = Trip.objects.filter(
        status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
        departure_time__gte=now,
        departure_time__lte=now + timedelta(days=days),
    )
    if origin_slug:
        queryset = queryset.filter(route__origin_city__slug=origin_slug)

    rows = (
        queryset.values(
            "route__origin_city_id",
            "route__origin_city__name",
            "route__origin_city__slug",
            "route__destination_city_id",
            "route__destination_city__name",
            "route__destination_city__slug",
        )
        .annotate(
            min_price=Min("price"),
            avg_price=Avg("price"),
            min_duration=Min("route__duration_minutes"),
            max_duration=Max("route__duration_minutes"),
            trip_count=Count("id"),
        )
        .order_by("-trip_count", "min_price")[:limit]
    )

    return [
        {
            "origin_city": {
                "id": row["route__origin_city_id"],
                "name": row["route__origin_city__name"],
                "slug": row["route__origin_city__slug"],
            },
            "destination_city": {
                "id": row["route__destination_city_id"],
                "name": row["route__destination_city__name"],
                "slug": row["route__destination_city__slug"],
            },
            "min_price": row["min_price"],
            "avg_price": row["avg_price"],
            "min_duration": row["min_duration"],
            "max_duration": row["max_duration"],
            "trips_per_day": max(1, round(row["trip_count"] / days)),
            "trip_count": row["trip_count"],
        }
        for row in rows
    ]


def axis_summary(*, origin_slug: str, destination_slug: str, days: int = 7) -> dict | None:
    """Summarise one specific origin-destination pair for its results page.

    Alimente le bloc editorial en bas de la page de resultats (prix,
    duree, frequence, escales habituelles) : `axis_overview` classe
    plusieurs axes par frequentation, celui-ci en decrit un seul — le
    trajet que le voyageur regarde, pas sa position dans un classement.

    Args:
        origin_slug: Departure city slug.
        destination_slug: Arrival city slug.
        days: Size of the forward-looking window, in days.

    Returns:
        ``None`` when no trip is scheduled on this axis within the window.
        Otherwise ``min_price``, ``max_price``, ``avg_price``, ``min_duration``,
        ``max_duration`` (minutes), ``trip_count``, ``trips_per_day``,
        ``companies_count``, ``distance_km``, ``premier_depart`` and
        ``dernier_depart`` (the earliest/latest departure time still to come
        today, ``None`` when nothing remains today) and ``escales_frequentes``
        (up to 3 intermediate stop names, most common first).
    """
    now = timezone.now()
    queryset = Trip.objects.filter(
        status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
        departure_time__gte=now,
        departure_time__lte=now + timedelta(days=days),
        route__origin_city__slug=origin_slug,
        route__destination_city__slug=destination_slug,
    )
    aggregat = queryset.aggregate(
        min_price=Min("price"),
        max_price=Max("price"),
        avg_price=Avg("price"),
        min_duration=Min("route__duration_minutes"),
        max_duration=Max("route__duration_minutes"),
        distance_km=Max("route__distance_km"),
        trip_count=Count("id"),
        companies_count=Count("route__company_id", distinct=True),
    )
    if not aggregat["trip_count"]:
        return None

    aujourdhui = queryset.filter(departure_time__date=timezone.localdate())
    horaires_jour = aujourdhui.aggregate(
        premier_depart=Min("departure_time"), dernier_depart=Max("departure_time")
    )

    escales_frequentes = list(
        RouteStop.objects.filter(
            route__origin_city__slug=origin_slug,
            route__destination_city__slug=destination_slug,
        )
        .values("city__name")
        .annotate(nombre=Count("id"))
        .order_by("-nombre", "city__name")
        .values_list("city__name", flat=True)[:3]
    )

    return {
        **aggregat,
        "trips_per_day": max(1, round(aggregat["trip_count"] / days)),
        "premier_depart": horaires_jour["premier_depart"],
        "dernier_depart": horaires_jour["dernier_depart"],
        "escales_frequentes": escales_frequentes,
    }


def _parse_time(value: str) -> time:
    """Parse an ``HH:MM`` string into a ``time`` object.

    Args:
        value: Time string such as ``"06:00"``.

    Returns:
        The parsed ``time``.

    Raises:
        ValidationError: If the format is invalid.
    """
    try:
        hour, minute = (int(part) for part in value.split(":"))
        return time(hour=hour, minute=minute)
    except (ValueError, AttributeError):
        raise ValidationError(f"Heure invalide : {value!r} (format attendu HH:MM).")


@transaction.atomic
def generate_trips(route_id: int, schedule_config: list[dict], days: int) -> list[Trip]:
    """Generate trips for a route over a rolling window of days.

    Args:
        route_id: Primary key of the route to schedule.
        schedule_config: List of slots, each as
            ``{"time": "06:00", "days": [0, 1, 2, 3, 4, 5, 6], "vehicle_id": 3}``
            where ``days`` are weekday indexes (Monday=0).
        days: Number of days from today (inclusive) to generate.

    Returns:
        The list of created trips.

    Raises:
        ValidationError: If the route or a vehicle is missing/unassignable, or
            the schedule config is malformed.
    """
    try:
        route = Route.objects.get(pk=route_id)
    except Route.DoesNotExist:
        raise ValidationError("Trajet introuvable.")

    if days <= 0:
        raise ValidationError("Le nombre de jours doit etre positif.")

    # Cache des vehicules pour eviter des requetes repetees.
    vehicle_cache: dict[int, Vehicle] = {}

    def _vehicle(vehicle_id: int) -> Vehicle:
        if vehicle_id not in vehicle_cache:
            try:
                vehicle = Vehicle.objects.get(pk=vehicle_id, company=route.company)
            except Vehicle.DoesNotExist:
                raise ValidationError(f"Vehicule {vehicle_id} introuvable.")
            ensure_vehicle_assignable(vehicle)
            vehicle_cache[vehicle_id] = vehicle
        return vehicle_cache[vehicle_id]

    created: list[Trip] = []
    today = timezone.localdate()
    current_tz = timezone.get_current_timezone()

    for offset in range(days):
        day = today + timedelta(days=offset)
        for slot in schedule_config:
            weekdays = slot.get("days") or []
            if day.weekday() not in weekdays:
                continue

            vehicle = _vehicle(slot["vehicle_id"])
            slot_time = _parse_time(slot["time"])
            departure = timezone.make_aware(
                datetime.combine(day, slot_time), current_tz
            )
            trip = Trip.objects.create(
                route=route,
                vehicle=vehicle,
                departure_time=departure,
                price=route.base_price,
                available_seats=vehicle.total_seats,
            )
            created.append(trip)

    return created


def _passenger_phones(trip: Trip) -> list[str]:
    """Collect distinct passenger phone numbers for a trip's active bookings.

    Resilient to the bookings app not being wired yet (PROMPT 05): if the
    ``bookings`` reverse relation is absent, an empty list is returned.

    Args:
        trip: The trip whose passengers are listed.

    Returns:
        Ordered list of unique phone numbers.
    """
    bookings = getattr(trip, "bookings", None)
    if bookings is None:
        return []

    phones = (
        bookings.exclude(status="cancelled")
        .values_list("phone", flat=True)
        .distinct()
    )
    return [phone for phone in phones if phone]


@transaction.atomic
def cancel_trip(trip: Trip, reason: str) -> Trip:
    """Cancel a trip and notify every booked passenger by SMS.

    Args:
        trip: The trip to cancel.
        reason: Plain-text reason stored on the trip and sent to passengers.

    Returns:
        The updated trip.

    Raises:
        ValidationError: If the trip is already cancelled or completed.
    """
    if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
        raise ValidationError(
            "Un voyage annule ou termine ne peut pas etre annule."
        )

    trip.status = Trip.TripStatus.CANCELLED
    trip.cancellation_reason = reason
    trip.save(update_fields=["status", "cancellation_reason", "updated_at"])

    message = (
        f"Votre voyage {trip.route} du "
        f"{timezone.localtime(trip.departure_time):%d/%m/%Y a %Hh%M} "
        f"est annule. Motif : {reason}"
    )
    for phone in _passenger_phones(trip):
        send_sms(phone, message)

    return trip


def close_expired_registrations() -> int:
    """Bascule vers `completed` tout voyage dont la cloture est passee.

    Cible les voyages `scheduled`/`in_progress`/`delayed` dont
    `registration_closes_at` est deja passe (bascule pile a l'heure, sans
    marge de grace ; cf. requetes agent module §1). Concu pour tourner en
    tache planifiee (toutes les 1-2 min) : simple `update()` en masse, sans
    notification (une cloture n'est pas une annulation).

    Returns:
        Le nombre de voyages bascules vers `completed`.
    """
    return Trip.objects.filter(
        status__in=_OPEN_STATUSES,
        registration_closes_at__lte=timezone.now(),
    ).update(status=Trip.TripStatus.COMPLETED, updated_at=timezone.now())


def delay_trip(trip: Trip, minutes: int) -> Trip:
    """Reporter un voyage de `minutes`, cumulables (cf. requetes agent §2).

    Decale `departure_time` et `registration_closes_at` de `+minutes` et bascule
    le voyage en `delayed`. Le trip doit deja etre verrouille par l'appelant
    (`select_for_update()`) pour rester coherent avec la cloture automatique.

    Args:
        trip: Le voyage a retarder (deja charge/verrouille par l'appelant).
        minutes: Nombre de minutes a ajouter (positif).

    Returns:
        Le voyage mis a jour.

    Raises:
        TripAlreadyCompleted: Si le voyage est deja termine.
    """
    if trip.status == Trip.TripStatus.COMPLETED:
        raise TripAlreadyCompleted()

    delta = timedelta(minutes=minutes)
    trip.departure_time += delta
    trip.registration_closes_at += delta
    trip.delay_minutes += minutes
    trip.status = Trip.TripStatus.DELAYED
    trip.save(
        update_fields=[
            "departure_time",
            "registration_closes_at",
            "delay_minutes",
            "status",
            "updated_at",
        ]
    )
    return trip
