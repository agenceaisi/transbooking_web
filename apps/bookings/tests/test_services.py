from datetime import timedelta

import pytest
from django.utils import timezone

from apps.bookings.exceptions import (
    BookingNotCancellable,
    CancellationTooLate,
    SeatTaken,
    TripFull,
    TripUnavailable,
)
from apps.bookings.models import BoardingValidation, BookingStatus
from apps.bookings.services import (
    cancel_booking,
    create_booking,
    generate_ticket_number,
    generate_ticket_pdf,
    scan_qr,
)
from apps.trips.models import Trip
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role
from apps.users.tests.factories import UserFactory
from apps.vehicles.tests.factories import VehicleFactory

from .factories import BookingFactory


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.bookings.services.send_sms", lambda *a, **k: None)


def _base_data(trip, **overrides):
    data = {
        "trip": trip,
        "first_name": "Aminata",
        "last_name": "TRAORE",
        "phone": "+22670000001",
        "amount": trip.price,
        "payment_method": "cash",
        "status": BookingStatus.PAID,
    }
    data.update(overrides)
    return data


@pytest.mark.django_db
def test_create_booking_decrements_seats_and_generates_ticket():
    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)

    booking = create_booking(_base_data(trip))

    trip.refresh_from_db()
    assert trip.available_seats == 9
    assert booking.ticket_number.startswith("BF")
    assert booking.qr_code
    assert booking.seat_number  # auto-attribue


@pytest.mark.django_db
def test_create_booking_stores_boarding_alighting_city_and_luggage():
    from apps.geography.tests.factories import CityFactory

    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)
    origine = trip.route.origin_city
    escale = CityFactory()

    booking = create_booking(
        _base_data(
            trip,
            origin_city=origine,
            destination_city=escale,
            has_luggage=True,
            luggage_qty=2,
        )
    )

    assert booking.origin_city_id == origine.id
    assert booking.destination_city_id == escale.id
    assert booking.has_luggage is True
    assert booking.luggage_qty == 2


@pytest.mark.django_db
def test_create_booking_auto_assigns_distinct_seats():
    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)

    first = create_booking(_base_data(trip))
    second = create_booking(_base_data(trip, phone="+22670000002"))

    assert first.seat_number != second.seat_number
    trip.refresh_from_db()
    assert trip.available_seats == 8


@pytest.mark.django_db
def test_create_booking_assigns_smallest_free_seat_number():
    # Attribution deterministe : le plus petit numero libre, pas un ordre
    # percu comme aleatoire (cf. requetes agent module §4).
    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)

    first = create_booking(_base_data(trip))
    second = create_booking(_base_data(trip, phone="+22670000002"))

    assert first.seat_number == "1"
    assert second.seat_number == "2"


@pytest.mark.django_db
def test_create_booking_reassigns_freed_seat_when_it_is_smallest():
    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)

    first = create_booking(_base_data(trip))
    create_booking(_base_data(trip, phone="+22670000002"))
    cancel_booking(first, cancelled_by=None)

    third = create_booking(_base_data(trip, phone="+22670000003"))

    assert third.seat_number == "1"


@pytest.mark.django_db
def test_concurrent_booking_same_seat_raises_seat_taken():
    # Deux requetes visant explicitement le meme siege : la 2e est rejetee
    # par la contrainte d'unicite (protection contre la surreservation).
    vehicle = VehicleFactory(total_seats=10)
    trip = TripFactory(vehicle=vehicle, available_seats=10)

    create_booking(_base_data(trip, seat_number="A3"))
    with pytest.raises(SeatTaken):
        create_booking(_base_data(trip, seat_number="A3", phone="+22670000002"))


@pytest.mark.django_db
def test_create_booking_rejected_when_trip_full():
    trip = TripFactory(available_seats=0)
    with pytest.raises(TripFull):
        create_booking(_base_data(trip))


@pytest.mark.django_db
def test_create_booking_rejected_when_trip_cancelled():
    trip = TripFactory(status=Trip.TripStatus.CANCELLED, available_seats=10)
    with pytest.raises(TripUnavailable):
        create_booking(_base_data(trip))


@pytest.mark.django_db
def test_create_booking_rejected_when_registration_closed():
    # La cloture (registration_closes_at) est deja passee mais la tache
    # planifiee n'est pas encore repassee : create_booking l'applique a la
    # volee (cf. requetes agent module §1, "aucune marge de grace").
    trip = TripFactory(
        departure_time=timezone.now() - timedelta(minutes=1), available_seats=10
    )
    with pytest.raises(TripUnavailable):
        create_booking(_base_data(trip))

    trip.refresh_from_db()
    assert trip.status == Trip.TripStatus.COMPLETED


@pytest.mark.django_db
def test_offline_booking_keeps_local_ticket_and_no_synced_at():
    trip = TripFactory(available_seats=10)
    booking = create_booking(
        _base_data(
            trip,
            is_offline=True,
            ticket_number="BF2026123456",
            offline_created_at=timezone.now(),
        )
    )

    assert booking.is_offline is True
    assert booking.synced_at is None
    assert booking.ticket_number == "BF2026123456"
    assert booking.qr_code


@pytest.mark.django_db
def test_generate_ticket_number_increments():
    BookingFactory(ticket_number=f"BF{timezone.now().year}000041")
    assert generate_ticket_number() == f"BF{timezone.now().year}000042"


@pytest.mark.django_db
def test_cancel_booking_by_voyageur_restores_seat():
    trip = TripFactory(available_seats=9, departure_time=timezone.now() + timedelta(days=2))
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    voyageur = UserFactory()

    cancel_booking(booking, cancelled_by=voyageur)

    booking.refresh_from_db()
    trip.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert trip.available_seats == 10


@pytest.mark.django_db
def test_cancel_booking_too_late_for_voyageur():
    trip = TripFactory(departure_time=timezone.now() + timedelta(minutes=30))
    booking = BookingFactory(trip=trip)
    voyageur = UserFactory()

    with pytest.raises(CancellationTooLate):
        cancel_booking(booking, cancelled_by=voyageur)


@pytest.mark.django_db
def test_admin_can_cancel_booking_close_to_departure():
    trip = TripFactory(
        available_seats=9, departure_time=timezone.now() + timedelta(minutes=30)
    )
    booking = BookingFactory(trip=trip)
    role, _ = Role.objects.get_or_create(name=Role.RoleName.COMPANY_ADMIN)
    admin = UserFactory(role=role, phone="+22670000777")

    cancel_booking(booking, cancelled_by=admin)

    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED


@pytest.mark.django_db
def test_scan_qr_valid_paid_booking_is_green():
    booking = BookingFactory(status=BookingStatus.PAID)
    controleur = UserFactory(phone="+22670000888")

    result = scan_qr(booking.ticket_number, controleur)

    assert result["status"] == "valid"
    assert result["color"] == "green"
    assert result["booking"]["ticket_number"] == booking.ticket_number


@pytest.mark.django_db
def test_scan_qr_includes_trip_info():
    booking = BookingFactory(status=BookingStatus.PAID)
    controleur = UserFactory(phone="+22670000889")

    result = scan_qr(booking.ticket_number, controleur)

    trip = result["booking"]["trip"]
    assert trip["id"] == booking.trip_id
    assert trip["origin_city"] == booking.trip.route.origin_city.name
    assert trip["destination_city"] == booking.trip.route.destination_city.name
    assert trip["departure_time"] == booking.trip.departure_time


@pytest.mark.django_db
def test_agent_guichet_can_cancel_close_to_departure():
    # L'annulation au guichet n'est pas soumise au delai de 2h du voyageur.
    trip = TripFactory(
        available_seats=9, departure_time=timezone.now() + timedelta(minutes=30)
    )
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = UserFactory(role=role, phone="+22670000778")

    cancel_booking(booking, cancelled_by=agent)

    booking.refresh_from_db()
    trip.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert trip.available_seats == 10


@pytest.mark.django_db
def test_cancel_booking_rejects_already_boarded():
    booking = BookingFactory(status=BookingStatus.PAID)
    controleur = UserFactory(phone="+22670000779")
    BoardingValidation.objects.create(
        booking=booking, validated_by=controleur, boarded_at=timezone.now()
    )

    with pytest.raises(BookingNotCancellable):
        cancel_booking(booking, cancelled_by=controleur)


@pytest.mark.django_db
def test_cancel_booking_rejects_refunded_booking():
    booking = BookingFactory(status=BookingStatus.REFUNDED)
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = UserFactory(role=role, phone="+22670000780")

    with pytest.raises(BookingNotCancellable):
        cancel_booking(booking, cancelled_by=agent)


@pytest.mark.django_db
def test_scan_qr_cancelled_booking_is_red():
    booking = BookingFactory(status=BookingStatus.CANCELLED)
    controleur = UserFactory(phone="+22670000889")

    result = scan_qr(booking.ticket_number, controleur)

    assert result["color"] == "red"


@pytest.mark.django_db
def test_scan_qr_invalid_ticket_raises():
    controleur = UserFactory(phone="+22670000890")
    from apps.bookings.models import Booking

    with pytest.raises(Booking.DoesNotExist):
        scan_qr("BF2026000000", controleur)


@pytest.mark.django_db
def test_scan_qr_respects_company_isolation():
    # Le controleur d'une compagnie ne peut pas scanner un billet d'une autre.
    booking = BookingFactory()
    other_controleur = UserFactory(phone="+22670000891")
    AgentProfile.objects.create(
        user=other_controleur,
        company=VehicleFactory().company,  # autre compagnie
        agent_type=AgentProfile.AgentType.CONTROLEUR,
    )
    from apps.bookings.models import Booking

    with pytest.raises(Booking.DoesNotExist):
        scan_qr(booking.ticket_number, other_controleur)


@pytest.mark.django_db
def test_generate_ticket_pdf_returns_pdf_bytes():
    booking = BookingFactory()
    pdf = generate_ticket_pdf(booking)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"
