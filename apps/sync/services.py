from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import ValidationError as DRFValidationError

from apps.bookings.exceptions import (
    BookingNotCancellable,
    SeatTaken,
    TripFull,
    TripUnavailable,
)
from apps.bookings.models import BoardingMethod, BoardingValidation, Booking, BookingStatus
from apps.bookings.services import cancel_booking, check_in, create_booking, register_baggage
from apps.geography.models import City, Station
from apps.parcels.models import (
    NotificationMethod,
    Parcel,
    ParcelNotification,
    ParcelStatus,
)
from apps.parcels.services import notify_recipient, register_parcel
from apps.trips.models import Trip
from apps.vehicles.services import next_available_seat

from .models import SyncConflict, SyncConflictType, SyncEntity, SyncLog


def _active_seats(trip: Trip) -> set[str]:
    """Return seat labels already held by a non-cancelled booking on a trip.

    Args:
        trip: The trip whose taken seats are listed.

    Returns:
        Set of taken seat labels.
    """
    return {
        str(seat)
        for seat in Booking.objects.filter(trip=trip)
        .exclude(status=BookingStatus.CANCELLED)
        .values_list("seat_number", flat=True)
    }


def resolve_seat_conflict(booking_data: dict, trip: Trip) -> tuple[dict, dict | None]:
    """Reassign a taken offline seat to the next free one.

    The requested seat is checked against the trip's active bookings (under the
    caller's row lock). When already taken, the next available seat is assigned
    and a conflict descriptor (plain French) is returned (cf. business_rules.md
    §6). When the seat is free or unspecified, the data is returned untouched.

    Args:
        booking_data: The offline booking dict. Read keys: ``seat_number``,
            ``ticket_number``.
        trip: The locked trip the booking targets.

    Returns:
        A ``(booking_data, conflict)`` tuple. ``conflict`` is ``None`` when no
        reassignment was needed, otherwise a dict with ``original_seat``,
        ``assigned_seat`` and ``message``.

    Raises:
        TripFull: If no seat remains free for the reassignment.
    """
    requested = str(booking_data.get("seat_number") or "").strip()
    if not requested or requested not in _active_seats(trip):
        return booking_data, None

    try:
        new_seat = next_available_seat(trip.vehicle, trip)
    except DjangoValidationError:
        raise TripFull()

    updated = {**booking_data, "seat_number": new_seat}
    conflict = {
        "original_seat": requested,
        "assigned_seat": new_seat,
        "message": (
            f"Siege {requested} deja attribue. "
            f"Nouveau siege attribue : {new_seat}."
        ),
    }
    return updated, conflict


def _sync_bookings(agent, trip_by_id, items, log, conflicts, errors) -> int:
    """Integrate the offline bookings of a sync payload.

    Args:
        agent: The agent owning the payload (multi-tenant scope).
        trip_by_id: Cache mapping trip id to a locked Trip for this company.
        items: The list of offline booking dicts.
        log: The SyncLog the conflicts attach to.
        conflicts: Mutable list collecting resolved conflict descriptors.
        errors: Mutable list collecting rejected record descriptors.

    Returns:
        The number of bookings created.
    """
    synced = 0
    # Ordre chronologique reel d'enregistrement (offline_created_at), pas
    # l'ordre d'arrivee dans le lot reseau : premier enregistre, premier servi
    # pour l'attribution des sieges (cf. requetes agent module §4).
    ordered_items = sorted(items, key=lambda item: item["offline_created_at"])
    for item in ordered_items:
        ticket_number = str(item.get("ticket_number") or "").strip()

        # 1. Idempotence : un billet deja synchronise est ignore silencieusement.
        if ticket_number and Booking.objects.filter(ticket_number=ticket_number).exists():
            continue

        trip = _get_scoped_trip(item.get("trip_id"), trip_by_id, agent)
        if trip is None:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.INVALID,
                    ticket_number,
                    "Voyage introuvable ou hors de la compagnie de l'agent.",
                )
            )
            continue

        if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.TRIP_UNAVAILABLE,
                    ticket_number,
                    "Voyage annule ou termine pendant la deconnexion. "
                    "Reservation rejetee.",
                )
            )
            continue

        # 2. Resolution du conflit de siege avant creation.
        try:
            resolved_data, seat_conflict = resolve_seat_conflict(item, trip)
        except TripFull:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.TRIP_FULL,
                    ticket_number,
                    "Voyage complet. Reservation rejetee.",
                )
            )
            continue

        booking_data = {
            "trip": trip,
            "first_name": resolved_data.get("first_name", ""),
            "last_name": resolved_data.get("last_name", ""),
            "phone": resolved_data.get("phone", ""),
            "seat_number": resolved_data.get("seat_number", ""),
            "amount": resolved_data.get("amount", trip.price),
            "payment_method": resolved_data.get("payment_method", ""),
            "ticket_number": ticket_number or None,
            "status": resolved_data.get("status", BookingStatus.PAID),
            "is_offline": True,
            "offline_created_at": resolved_data.get("offline_created_at"),
        }

        # 3. Creation (verrou de ligne gere par create_booking).
        try:
            booking = create_booking(booking_data, agent=agent)
        except TripFull:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.TRIP_FULL,
                    ticket_number,
                    "Voyage complet. Reservation rejetee.",
                )
            )
            continue
        except TripUnavailable:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.TRIP_UNAVAILABLE,
                    ticket_number,
                    "Voyage annule ou termine. Reservation rejetee.",
                )
            )
            continue
        except SeatTaken:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.SEAT_CONFLICT,
                    ticket_number,
                    "Siege deja attribue, reattribution impossible.",
                )
            )
            continue

        # Bagages peses au guichet hors ligne, joints a la reservation.
        baggage_items = resolved_data.get("baggage") or []
        if baggage_items:
            register_baggage(booking, baggage_items, is_offline=True)

        # La reservation hors ligne est desormais synchronisee.
        booking.synced_at = timezone.now()
        booking.save(update_fields=["synced_at", "updated_at"])
        synced += 1

        if seat_conflict is not None:
            conflicts.append(
                _log_seat_conflict(log, booking.ticket_number, seat_conflict)
            )

    return synced


def _sync_parcels(agent, items, log, errors) -> int:
    """Integrate the offline parcels of a sync payload.

    Args:
        agent: The agent owning the payload.
        items: The list of offline parcel dicts.
        log: The SyncLog the errors attach to.
        errors: Mutable list collecting rejected record descriptors.

    Returns:
        The number of parcels created.
    """
    profile = agent.agent_profile
    synced = 0
    for item in items:
        tracking_number = str(item.get("tracking_number") or "").strip()

        # Idempotence : un colis deja synchronise est ignore.
        if tracking_number and Parcel.objects.filter(
            tracking_number=tracking_number
        ).exists():
            continue

        # Les villes/gares arrivent en IDs : on resout les instances attendues
        # par register_parcel (isolation : la gare de depart vient du profil).
        origin_city = City.objects.filter(pk=item.get("origin_city")).first()
        destination_city = City.objects.filter(
            pk=item.get("destination_city")
        ).first()
        if origin_city is None or destination_city is None:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.PARCEL,
                    SyncConflictType.INVALID,
                    tracking_number,
                    "Ville de depart ou d'arrivee introuvable. Colis rejete.",
                )
            )
            continue

        destination_station = (
            Station.objects.filter(
                pk=item.get("destination_station"),
                company_id=profile.company_id,
            ).first()
            if item.get("destination_station")
            else None
        )
        trip = (
            Trip.objects.filter(
                pk=item.get("trip"), route__company_id=profile.company_id
            ).first()
            if item.get("trip")
            else None
        )

        parcel_data = {
            "company": profile.company,
            "origin_city": origin_city,
            "destination_city": destination_city,
            "origin_station": profile.station,
            "destination_station": destination_station,
            "trip": trip,
            "sender_name": item.get("sender_name", ""),
            "sender_phone": item.get("sender_phone", ""),
            "recipient_name": item.get("recipient_name", ""),
            "recipient_phone": item.get("recipient_phone", ""),
            "description": item.get("description", ""),
            "weight_kg": item.get("weight_kg"),
            "tracking_number": tracking_number or None,
            "is_offline": True,
            "offline_created_at": item.get("offline_created_at"),
        }

        try:
            parcel = register_parcel(parcel_data, agent=agent)
        except (DRFValidationError, DjangoValidationError) as exc:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.PARCEL,
                    SyncConflictType.INVALID,
                    tracking_number,
                    f"Colis rejete : {_first_message(exc)}",
                )
            )
            continue

        parcel.synced_at = timezone.now()
        parcel.save(update_fields=["synced_at", "updated_at"])
        synced += 1

    return synced


def _sync_validations(agent, items, log, errors) -> int:
    """Integrate the offline boarding validations of a sync payload.

    Args:
        agent: The agent owning the payload (multi-tenant scope).
        items: The list of offline boarding validation dicts.
        log: The SyncLog the errors attach to.
        errors: Mutable list collecting rejected record descriptors.

    Returns:
        The number of validations created.
    """
    company_id = agent.agent_profile.company_id
    synced = 0
    for item in items:
        ticket_number = str(item.get("ticket_number") or "").strip()
        try:
            booking = Booking.objects.get(
                ticket_number=ticket_number,
                trip__route__company_id=company_id,
            )
        except Booking.DoesNotExist:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.VALIDATION,
                    SyncConflictType.INVALID,
                    ticket_number,
                    "Billet introuvable pour cette compagnie. "
                    "Embarquement ignore.",
                )
            )
            continue

        # check_in est idempotent : un embarquement deja present est conserve.
        already = BoardingValidation.objects.filter(booking=booking).exists()
        validation = check_in(booking, agent, method=BoardingMethod.MANUAL)
        if already:
            # Re-sync du meme embarquement : aucun nouvel enregistrement.
            continue

        validation.is_offline = True
        validation.offline_created_at = item.get("offline_created_at")
        validation.synced_at = timezone.now()
        validation.save(
            update_fields=["is_offline", "offline_created_at", "synced_at", "updated_at"]
        )
        synced += 1

    return synced


def _sync_parcel_notifications(agent, items, log, errors) -> int:
    """Integrate the offline parcel « marked as called » notifications.

    Only manual calls (`method='call'`) are synchronised: an SMS cannot be sent
    offline. Idempotence relies on the ``(parcel, offline_created_at)`` pair — a
    re-synced notification is skipped.

    Args:
        agent: The agent owning the payload (multi-tenant scope).
        items: The list of offline parcel notification dicts.
        log: The SyncLog the errors attach to.
        errors: Mutable list collecting rejected record descriptors.

    Returns:
        The number of notifications created.
    """
    company_id = agent.agent_profile.company_id
    synced = 0
    for item in items:
        tracking_number = str(item.get("tracking_number") or "").strip()
        offline_created_at = item.get("offline_created_at")

        parcel = Parcel.objects.filter(
            tracking_number=tracking_number, company_id=company_id
        ).first()
        if parcel is None:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.PARCEL,
                    SyncConflictType.INVALID,
                    tracking_number,
                    "Colis introuvable pour cette compagnie. Notification ignoree.",
                )
            )
            continue

        # Idempotence : meme appel deja synchronise (meme colis + meme horodatage).
        already = ParcelNotification.objects.filter(
            parcel=parcel,
            method=NotificationMethod.CALL,
            offline_created_at=offline_created_at,
        ).exists()
        if already:
            continue

        notification = notify_recipient(
            parcel, agent=agent, method=NotificationMethod.CALL
        )
        notification.is_offline = True
        notification.offline_created_at = offline_created_at
        notification.synced_at = timezone.now()
        notification.save(
            update_fields=["is_offline", "offline_created_at", "synced_at", "updated_at"]
        )
        synced += 1

    return synced


def _sync_cancellations(agent, items, log, errors) -> int:
    """Integrate offline counter cancellations of an already-synced booking.

    A booking created offline and never synchronised is cancelled purely on the
    client (outbox entry dropped, no server call) — only cancellations targeting
    a booking the server already knows about reach this path. Idempotent: a
    booking already cancelled is skipped silently (cf. requetes agent module §1).

    Args:
        agent: The agent owning the payload (multi-tenant scope).
        items: The list of offline cancellation dicts.
        log: The SyncLog the errors attach to.
        errors: Mutable list collecting rejected record descriptors.

    Returns:
        The number of bookings cancelled.
    """
    company_id = agent.agent_profile.company_id
    synced = 0
    for item in items:
        ticket_number = str(item.get("ticket_number") or "").strip()
        try:
            booking = Booking.objects.get(
                ticket_number=ticket_number,
                trip__route__company_id=company_id,
            )
        except Booking.DoesNotExist:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.INVALID,
                    ticket_number,
                    "Billet introuvable pour cette compagnie. Annulation ignoree.",
                )
            )
            continue

        if booking.status == BookingStatus.CANCELLED:
            # Re-sync de la meme annulation : deja integree.
            continue

        try:
            cancel_booking(booking, cancelled_by=agent, reason=item.get("reason", ""))
        except BookingNotCancellable:
            errors.append(
                _log_error(
                    log,
                    SyncEntity.BOOKING,
                    SyncConflictType.INVALID,
                    ticket_number,
                    "Billet deja embarque ou rembourse. Annulation ignoree.",
                )
            )
            continue

        synced += 1

    return synced


def sync_agent_data(agent, payload: dict) -> SyncLog:
    """Integrate an agent's offline data in a single atomic transaction.

    Processes bookings, parcels, boarding validations, parcel « marked as
    called » notifications and counter cancellations of already-synced bookings.
    Each record is idempotent (already-synced records are skipped) and seat
    conflicts are resolved automatically by assigning the next free seat (cf.
    business_rules.md §6). Rejected records (full/cancelled trip, invalid data)
    are reported as errors. A `SyncLog` summarising the run is returned with its
    related `SyncConflict` rows.

    Args:
        agent: The authenticated agent user submitting the payload. Must carry
            an ``agent_profile`` with a company.
        payload: Dict with ``bookings``, ``parcels``, ``validations``,
            ``parcel_notifications`` and ``cancellations`` lists.

    Returns:
        The created sync log, with ``conflicts``/``errors`` lists attached on a
        transient ``synced_conflicts`` / ``synced_errors`` attribute.
    """
    conflicts: list[dict] = []
    errors: list[dict] = []

    with transaction.atomic():
        log = SyncLog.objects.create(agent=agent)
        trip_by_id: dict = {}

        bookings_synced = _sync_bookings(
            agent, trip_by_id, payload.get("bookings", []) or [], log, conflicts, errors
        )
        parcels_synced = _sync_parcels(
            agent, payload.get("parcels", []) or [], log, errors
        )
        validations_synced = _sync_validations(
            agent, payload.get("validations", []) or [], log, errors
        )
        parcel_notifications_synced = _sync_parcel_notifications(
            agent, payload.get("parcel_notifications", []) or [], log, errors
        )
        cancellations_synced = _sync_cancellations(
            agent, payload.get("cancellations", []) or [], log, errors
        )

        log.bookings_synced = bookings_synced
        log.parcels_synced = parcels_synced
        log.validations_synced = validations_synced
        log.parcel_notifications_synced = parcel_notifications_synced
        log.cancellations_synced = cancellations_synced
        log.conflicts_count = len(conflicts)
        log.errors_count = len(errors)
        log.save(
            update_fields=[
                "bookings_synced",
                "parcels_synced",
                "validations_synced",
                "parcel_notifications_synced",
                "cancellations_synced",
                "conflicts_count",
                "errors_count",
                "updated_at",
            ]
        )

    # Expose les listes detaillees a la vue sans nouvelle requete.
    log.synced_conflicts = conflicts
    log.synced_errors = errors
    return log


# --------------------------------------------------------------------------- #
# Helpers internes
# --------------------------------------------------------------------------- #


def _get_scoped_trip(trip_id, trip_by_id: dict, agent) -> Trip | None:
    """Fetch and lock a trip belonging to the agent's company (cached).

    Args:
        trip_id: The trip primary key from the payload.
        trip_by_id: Per-sync cache of already-locked trips.
        agent: The agent (carries the company scope).

    Returns:
        The locked trip, or ``None`` if absent or out of the agent's company.
    """
    if trip_id in trip_by_id:
        return trip_by_id[trip_id]
    if trip_id is None:
        return None

    company_id = agent.agent_profile.company_id
    trip = (
        Trip.objects.select_for_update()
        .select_related("vehicle")
        .filter(pk=trip_id, route__company_id=company_id)
        .first()
    )
    trip_by_id[trip_id] = trip
    return trip


def _log_seat_conflict(log: SyncLog, reference: str, conflict: dict) -> dict:
    """Persist a resolved seat conflict and return its response descriptor.

    Args:
        log: The owning sync log.
        reference: The booking ticket number.
        conflict: The descriptor from ``resolve_seat_conflict``.

    Returns:
        The conflict dict shaped for the API response.
    """
    SyncConflict.objects.create(
        sync_log=log,
        entity=SyncEntity.BOOKING,
        conflict_type=SyncConflictType.SEAT_CONFLICT,
        reference=reference,
        original_seat=conflict["original_seat"],
        assigned_seat=conflict["assigned_seat"],
        resolution=conflict["message"],
        resolved=True,
    )
    return {
        "type": SyncConflictType.SEAT_CONFLICT,
        "ticket_number": reference,
        "original_seat": conflict["original_seat"],
        "assigned_seat": conflict["assigned_seat"],
        "message": conflict["message"],
    }


def _log_error(
    log: SyncLog,
    entity: str,
    conflict_type: str,
    reference: str,
    resolution: str,
) -> dict:
    """Persist a rejected record and return its response descriptor.

    Args:
        log: The owning sync log.
        entity: The entity kind (booking/parcel/validation).
        conflict_type: The reason code.
        reference: The functional identifier (ticket/tracking number).
        resolution: The plain-French explanation.

    Returns:
        The error dict shaped for the API response.
    """
    SyncConflict.objects.create(
        sync_log=log,
        entity=entity,
        conflict_type=conflict_type,
        reference=reference,
        resolution=resolution,
        resolved=False,
    )
    return {
        "type": conflict_type,
        "entity": entity,
        "reference": reference,
        "message": resolution,
    }


def _first_message(exc) -> str:
    """Extract a readable first message from a validation error.

    Args:
        exc: A DRF or Django ``ValidationError``.

    Returns:
        The first human-readable error message.
    """
    detail = getattr(exc, "detail", None) or getattr(exc, "messages", None) or [str(exc)]
    if isinstance(detail, dict):
        detail = next(iter(detail.values()), [str(exc)])
    if isinstance(detail, (list, tuple)) and detail:
        return str(detail[0])
    return str(detail)


# --------------------------------------------------------------------------- #
# Telechargement des donnees pour le mode hors ligne
# --------------------------------------------------------------------------- #


def get_offline_data(agent) -> dict:
    """Collect the data an agent needs to work offline today.

    Returns today's trips for the agent's vehicle/station, the active bookings on
    those trips and the parcels awaiting collection at the agent's station — all
    scoped to the agent's company (cf. PROMPT 09 ``GET /agent/offline-data/``).

    Args:
        agent: The authenticated agent user. Must carry an ``agent_profile``.

    Returns:
        Dict with ``trips``, ``bookings`` and ``parcel_arrivals`` querysets.
    """
    profile = agent.agent_profile
    company_id = profile.company_id
    today = timezone.localdate()

    trips = (
        Trip.objects.filter(
            route__company_id=company_id,
            departure_time__date=today,
        )
        .exclude(status=Trip.TripStatus.CANCELLED)
        .select_related("route__origin_city", "route__destination_city", "vehicle")
    )
    # On restreint au perimetre de l'agent : son vehicule et/ou sa gare.
    scope = Q()
    if profile.vehicle_id:
        scope |= Q(vehicle_id=profile.vehicle_id)
    if profile.station_id:
        scope |= Q(route__origin_station_id=profile.station_id)
    if scope:
        trips = trips.filter(scope)
    trips = trips.order_by("departure_time")

    bookings = (
        Booking.objects.filter(trip__in=trips)
        .exclude(status=BookingStatus.CANCELLED)
        .select_related("trip")
        .order_by("trip__departure_time", "seat_number")
    )

    parcels = Parcel.objects.filter(
        company_id=company_id, status=ParcelStatus.ARRIVED
    )
    if profile.station_id:
        parcels = parcels.filter(destination_station_id=profile.station_id)
    parcels = parcels.select_related("origin_city", "destination_city")

    return {
        "trips": trips,
        "bookings": bookings,
        "parcel_arrivals": parcels,
    }
