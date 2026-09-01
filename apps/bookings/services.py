from datetime import timedelta
from io import BytesIO

from django.db import IntegrityError, transaction
from django.db.models import Max
from django.utils import timezone

from apps.trips.models import Trip
from apps.vehicles.services import next_available_seat
from utils.qr import generate_qr
from utils.sms import send_sms

from .exceptions import (
    BookingNotCancellable,
    CancellationTooLate,
    SeatTaken,
    TripFull,
    TripUnavailable,
)
from .models import (
    Baggage,
    BaggageLocation,
    BoardingMethod,
    BoardingValidation,
    Booking,
    BookingStatus,
    IdType,
    ScanLog,
    ScanResult,
)

# Roles autorises a annuler une reservation sans contrainte de delai : les admins,
# et l'agent guichet qui corrige une saisie ou repond au renoncement d'un client au
# comptoir (annulation initiee par le staff, pas en libre-service).
_ADMIN_ROLES = {"company_admin", "super_admin"}
_STAFF_CANCEL_ROLES = _ADMIN_ROLES | {"agent_guichet"}
# Delai minimal entre l'annulation par un voyageur et le depart.
CANCELLATION_DEADLINE = timedelta(hours=2)


def generate_ticket_number() -> str:
    """Build the next ticket number: ``BF`` + year + 6-digit sequence.

    The sequence is scoped to the current calendar year (e.g. ``BF2026001234``).
    Call inside the booking transaction so the read of the last number and the
    insert are serialized by the trip row lock.

    Returns:
        The next available ticket number for the current year.
    """
    prefix = f"BF{timezone.now().year}"
    last = (
        Booking.objects.filter(ticket_number__startswith=prefix)
        .aggregate(last=Max("ticket_number"))
        .get("last")
    )
    sequence = int(last[len(prefix):]) + 1 if last else 1
    return f"{prefix}{sequence:06d}"


def _next_baggage_tag() -> str:
    """Build the next baggage tag: ``TB-B-`` + 4-digit sequence.

    The zero-padded sequence keeps lexicographic order aligned with numeric
    order (safe up to 9999 baggage items). Rows created earlier in the same
    transaction are visible here, so consecutive tags stay unique.

    Returns:
        The next available baggage tag (e.g. ``TB-B-0043``).
    """
    last = (
        Baggage.objects.filter(tag__startswith="TB-B-")
        .aggregate(last=Max("tag"))
        .get("last")
    )
    sequence = int(last.split("-")[-1]) + 1 if last else 1
    return f"TB-B-{sequence:04d}"


def register_baggage(booking: Booking, items: list[dict], is_offline: bool = False):
    """Register weighed baggage against a booking, assigning printed tags.

    Args:
        booking: The booking the baggage belongs to.
        items: Cleaned baggage entries. Each recognises ``label`` (str),
            ``weight_kg`` (Decimal) and optional ``location`` (a
            ``BaggageLocation`` value, defaults to ``hold``).
        is_offline: Whether the baggage was registered offline at the counter.

    Returns:
        The list of created ``Baggage`` rows.
    """
    created = []
    with transaction.atomic():
        for item in items:
            bag = Baggage.objects.create(
                booking=booking,
                label=item["label"],
                tag=_next_baggage_tag(),
                weight_kg=item["weight_kg"],
                location=item.get("location", BaggageLocation.HOLD),
                is_offline=is_offline,
                synced_at=None if is_offline else timezone.now(),
            )
            created.append(bag)
    return created


def _auto_close_if_expired(trip_id: int) -> None:
    """Flip a single trip to `completed` if its registration deadline passed.

    Runs as its own committed transaction, *before* the caller opens the
    booking-creation lock: a status flip written inside that later transaction
    would be rolled back along with everything else the moment it raises
    `TripUnavailable`, so the self-heal has to land and commit first (cf.
    requetes agent module §1, "aucune marge de grace apres").

    Args:
        trip_id: The trip to check.
    """
    with transaction.atomic():
        Trip.objects.filter(
            pk=trip_id, registration_closes_at__lte=timezone.now()
        ).exclude(
            status__in={Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}
        ).update(status=Trip.TripStatus.COMPLETED, updated_at=timezone.now())


def create_booking(validated_data: dict, agent=None) -> Booking:
    """Create a booking, reserving a seat under a row-level trip lock.

    The trip row is locked with ``select_for_update()`` so concurrent requests
    cannot oversell seats. The seat is auto-assigned when none is supplied, the
    ticket number and QR code are generated, and a confirmation SMS is sent.

    Args:
        validated_data: Cleaned fields. Recognised keys: ``trip`` (Trip),
            ``first_name``, ``last_name``, ``phone``, ``amount``, ``status``,
            ``seat_number`` (optional), ``payment_method``, ``user`` (optional),
            ``gender``, ``id_type``, ``id_number``, ``discount_code``,
            ``origin_city``, ``destination_city`` (boarding/alighting city,
            when they differ from the route's own endpoints — e.g. a partial-fare
            booking to an intermediate stop), ``has_luggage``, ``luggage_qty``
            (all optional), ``is_offline``, ``offline_created_at``,
            ``ticket_number`` (offline).
        agent: The agent user registering the booking, or ``None`` online.

    Returns:
        The created booking.

    Raises:
        TripUnavailable: If the trip is cancelled, completed, or its
            registration has closed (HTTP 410).
        TripFull: If no seat is available (HTTP 409).
        SeatTaken: If the requested seat is already booked (HTTP 409).
    """
    trip_arg = validated_data["trip"]
    trip_id = trip_arg.id if isinstance(trip_arg, Trip) else trip_arg
    is_offline = validated_data.get("is_offline", False)

    # Auto-cloture si la tache planifiee (toutes les 1-2 min) n'est pas encore
    # repassee : pas de marge de grace apres registration_closes_at.
    _auto_close_if_expired(trip_id)

    with transaction.atomic():
        # Verrou ligne : serialise l'attribution des sieges (cf. business_rules §1).
        trip = Trip.objects.select_for_update().select_related("vehicle").get(pk=trip_id)

        if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
            raise TripUnavailable()
        if trip.available_seats <= 0:
            raise TripFull()

        seat_number = validated_data.get("seat_number")
        if not seat_number:
            # next_available_seat leve ValidationError si plus aucun siege libre.
            try:
                seat_number = next_available_seat(trip.vehicle, trip)
            except Exception:
                raise TripFull()

        ticket_number = validated_data.get("ticket_number") or generate_ticket_number()

        try:
            with transaction.atomic():
                booking = Booking.objects.create(
                    trip=trip,
                    user=validated_data.get("user"),
                    agent=agent,
                    first_name=validated_data["first_name"],
                    last_name=validated_data["last_name"],
                    phone=validated_data["phone"],
                    gender=validated_data.get("gender", ""),
                    id_type=validated_data.get("id_type") or IdType.NONE,
                    id_number=validated_data.get("id_number", ""),
                    discount_code=validated_data.get("discount_code", ""),
                    origin_city=validated_data.get("origin_city"),
                    destination_city=validated_data.get("destination_city"),
                    has_luggage=validated_data.get("has_luggage", False),
                    luggage_qty=validated_data.get("luggage_qty"),
                    seat_number=seat_number,
                    amount=validated_data["amount"],
                    payment_method=validated_data.get("payment_method", ""),
                    ticket_number=ticket_number,
                    qr_code=generate_qr(ticket_number),
                    status=validated_data.get("status", BookingStatus.PENDING),
                    is_offline=is_offline,
                    offline_created_at=validated_data.get("offline_created_at"),
                    synced_at=None if is_offline else timezone.now(),
                )
        except IntegrityError:
            # Course sur un siege precis demande simultanement.
            raise SeatTaken()

        trip.available_seats -= 1
        trip.save(update_fields=["available_seats", "updated_at"])

    # La confirmation part une fois la reservation payee. Une reservation creee
    # directement comme payee (guichet) est confirmee tout de suite ; sinon c'est
    # le paiement qui declenche le SMS (cf. payments.services.confirm_payment).
    if not is_offline and booking.status == BookingStatus.PAID:
        _send_confirmation_sms(booking)
    return booking


def _send_confirmation_sms(booking: Booking) -> None:
    """Send the booking confirmation SMS to the passenger.

    Args:
        booking: The booking to confirm.
    """
    message = (
        f"Reservation confirmee. Billet {booking.ticket_number}, "
        f"siege {booking.seat_number}. Voyage du "
        f"{timezone.localtime(booking.trip.departure_time):%d/%m/%Y a %Hh%M}."
    )
    send_sms(booking.phone, message)


def cancel_booking(booking: Booking, cancelled_by, reason: str = "") -> Booking:
    """Cancel a booking and free its seat.

    Voyageurs may only cancel until 2h before departure; company/super admins and
    the agent guichet cancelling at the counter cancel without restriction (cf.
    business_rules.md §1, requetes agent module §1).

    Args:
        booking: The booking to cancel.
        cancelled_by: The user requesting the cancellation.
        reason: Optional plain-text reason.

    Returns:
        The updated booking.

    Raises:
        CancellationTooLate: If a voyageur cancels within 2h of departure.
        BookingNotCancellable: If the booking is already boarded or refunded.
    """
    if booking.status == BookingStatus.CANCELLED:
        return booking
    if booking.status == BookingStatus.REFUNDED or hasattr(booking, "boarding_validation"):
        raise BookingNotCancellable()

    role = getattr(getattr(cancelled_by, "role", None), "name", None)
    is_staff_cancel = role in _STAFF_CANCEL_ROLES
    if not is_staff_cancel:
        deadline = booking.trip.departure_time - CANCELLATION_DEADLINE
        if timezone.now() >= deadline:
            raise CancellationTooLate()

    with transaction.atomic():
        trip = Trip.objects.select_for_update().get(pk=booking.trip_id)
        booking.status = BookingStatus.CANCELLED
        booking.cancellation_reason = reason
        booking.cancelled_by = cancelled_by
        booking.save(
            update_fields=[
                "status",
                "cancellation_reason",
                "cancelled_by",
                "updated_at",
            ]
        )
        # Le siege est libere et redevient reservable.
        trip.available_seats += 1
        trip.save(update_fields=["available_seats", "updated_at"])

    return booking


# Codes couleur renvoyes au controleur lors d'un scan (UI feu tricolore).
_SCAN_RESULTS = {
    BookingStatus.PAID: ("valid", "green", "Billet valide."),
    BookingStatus.PENDING: ("unpaid", "orange", "Paiement non confirme."),
    BookingStatus.CANCELLED: ("cancelled", "red", "Reservation annulee."),
    BookingStatus.REFUNDED: ("refunded", "red", "Reservation remboursee."),
}


def scan_qr(qr_data: str, agent) -> dict:
    """Resolve a scanned QR code to a colour-coded boarding status.

    Every scan is traced in ``ScanLog`` — including fruitless ones — so the
    controleur can review their last scans (cf. ``GET /agent/scan/history/``).

    Args:
        qr_data: The decoded QR payload (the ticket number).
        agent: The controleur scanning the ticket (multi-tenant scope).

    Returns:
        A dict with ``status``, ``color``, ``message`` and ``booking`` info.

    Raises:
        Booking.DoesNotExist: If no booking matches within the agent's company.
    """
    ticket_number = (qr_data or "").strip()
    queryset = Booking.objects.select_related(
        "trip__route__origin_city", "trip__route__destination_city"
    )
    profile = getattr(agent, "agent_profile", None)
    if profile is not None and profile.company_id is not None:
        # Isolation multi-tenant : un controleur ne scanne que sa compagnie.
        queryset = queryset.filter(trip__route__company_id=profile.company_id)

    try:
        booking = queryset.get(ticket_number=ticket_number)
    except Booking.DoesNotExist:
        # Le scan infructueux est trace puis remonte (404 cote vue).
        ScanLog.objects.create(
            agent=agent,
            booking=None,
            ticket_number=ticket_number[:20],
            result=ScanResult.NOT_FOUND,
        )
        raise

    already_boarded = BoardingValidation.objects.filter(booking=booking).exists()
    if already_boarded and booking.status == BookingStatus.PAID:
        status_code, color, message = (
            "already_boarded",
            "orange",
            "Passager deja embarque.",
        )
    else:
        status_code, color, message = _SCAN_RESULTS.get(
            booking.status, ("invalid", "red", "Billet invalide.")
        )

    ScanLog.objects.create(
        agent=agent,
        booking=booking,
        ticket_number=booking.ticket_number,
        result=status_code,
    )

    return {
        "status": status_code,
        "color": color,
        "message": message,
        "booking": {
            "ticket_number": booking.ticket_number,
            "passenger_name": booking.passenger_name,
            "seat_number": booking.seat_number,
            "status": booking.status,
            "trip": {
                "id": booking.trip_id,
                "origin_city": booking.trip.route.origin_city.name,
                "destination_city": booking.trip.route.destination_city.name,
                "departure_time": booking.trip.departure_time,
            },
        },
    }


def check_in(booking: Booking, agent, method: str = BoardingMethod.MANUAL) -> BoardingValidation:
    """Record (or return) the boarding validation for a booking.

    Idempotent: a booking already boarded returns its existing validation.

    Args:
        booking: The booking to board.
        agent: The controleur performing the check-in.
        method: ``scan`` or ``manual``.

    Returns:
        The boarding validation.
    """
    validation, _ = BoardingValidation.objects.get_or_create(
        booking=booking,
        defaults={
            "validated_by": agent,
            "method": method,
            "boarded_at": timezone.now(),
        },
    )
    return validation


def mark_ticket_printed(booking: Booking, agent=None) -> dict:
    """Flag a ticket as printed and return its print payload.

    Idempotent-friendly: each call bumps ``print_count`` and refreshes
    ``printed_at`` (a re-print is legitimate: paper jam, lost ticket...).

    Args:
        booking: The booking whose ticket is printed.
        agent: The agent printing the ticket (unused today, kept for audit).

    Returns:
        The payload the counter printer needs (ticket, passenger, trip, QR).
    """
    booking.printed_at = timezone.now()
    booking.print_count += 1
    booking.save(update_fields=["printed_at", "print_count", "updated_at"])

    trip = booking.trip
    route = trip.route
    return {
        "ticket_number": booking.ticket_number,
        "passenger_name": booking.passenger_name,
        "phone": booking.phone,
        "seat_number": booking.seat_number,
        "amount": booking.amount,
        "status": booking.status,
        "company_name": route.company.name,
        "origin_city": route.origin_city.name,
        "destination_city": route.destination_city.name,
        "departure_time": trip.departure_time,
        "qr_code": booking.qr_code,
        "printed_at": booking.printed_at,
        "print_count": booking.print_count,
    }


def generate_ticket_pdf(booking: Booking) -> bytes:
    """Render a booking ticket as a PDF document.

    Args:
        booking: The booking to render. Contains trip, seat and QR data.

    Returns:
        The PDF file content as bytes.
    """
    # Import local : ReportLab n'est requis que pour la generation PDF.
    import base64

    from reportlab.lib.pagesizes import A6
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    width, height = A6
    pdf = canvas.Canvas(buffer, pagesize=A6)

    trip = booking.trip
    route = trip.route

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(15 * mm, height - 18 * mm, "TransBooking BF")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(15 * mm, height - 24 * mm, f"Billet : {booking.ticket_number}")

    lines = [
        f"Passager : {booking.passenger_name}",
        f"Trajet : {route.origin_city.name} -> {route.destination_city.name}",
        f"Depart : {timezone.localtime(trip.departure_time):%d/%m/%Y a %Hh%M}",
        f"Siege : {booking.seat_number}",
        f"Montant : {booking.amount} FCFA",
        f"Statut : {booking.get_status_display()}",
    ]
    y = height - 34 * mm
    pdf.setFont("Helvetica", 9)
    for line in lines:
        pdf.drawString(15 * mm, y, line)
        y -= 6 * mm

    if booking.qr_code:
        try:
            qr_image = ImageReader(BytesIO(base64.b64decode(booking.qr_code)))
            pdf.drawImage(
                qr_image,
                width - 45 * mm,
                15 * mm,
                width=30 * mm,
                height=30 * mm,
            )
        except Exception:
            # Un QR illisible ne doit pas casser la generation du billet.
            pass

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
