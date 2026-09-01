import pytest
from django.utils import timezone

from apps.bookings.models import BoardingValidation, Booking, BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.parcels.models import Parcel, ParcelStatus
from apps.parcels.tests.factories import ParcelFactory
from apps.sync.models import SyncConflict, SyncConflictType
from apps.sync.services import get_offline_data, sync_agent_data
from apps.trips.models import Trip

from .factories import make_company_trip, make_guichet_agent


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    # Le coeur de la sync passe par bookings/parcels.services -> on coupe leurs SMS.
    monkeypatch.setattr("apps.bookings.services.send_sms", lambda *a, **k: None)
    monkeypatch.setattr("apps.parcels.services.send_sms", lambda *a, **k: None)


def _booking_item(trip, ticket_number, seat_number="", **overrides):
    item = {
        "ticket_number": ticket_number,
        "trip_id": trip.id,
        "first_name": "Aminata",
        "last_name": "TRAORE",
        "phone": "+22670000001",
        "seat_number": seat_number,
        "amount": str(trip.price),
        "payment_method": "cash",
        "offline_created_at": timezone.now(),
    }
    item.update(overrides)
    return item


# --------------------------------------------------------------------------- #
# Bookings — cas nominal et idempotence
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_sync_with_zero_conflicts_creates_bookings():
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    payload = {
        "bookings": [
            _booking_item(trip, "BF2026000001"),
            _booking_item(trip, "BF2026000002", phone="+22670000002"),
        ]
    }

    log = sync_agent_data(agent, payload)

    assert log.bookings_synced == 2
    assert log.conflicts_count == 0
    assert log.errors_count == 0
    assert Booking.objects.filter(ticket_number="BF2026000001").exists()
    booking = Booking.objects.get(ticket_number="BF2026000001")
    assert booking.is_offline is True
    assert booking.synced_at is not None
    trip.refresh_from_db()
    assert trip.available_seats == 8


@pytest.mark.django_db
def test_idempotent_resync_creates_nothing_second_time():
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    payload = {"bookings": [_booking_item(trip, "BF2026000001")]}

    first = sync_agent_data(agent, payload)
    second = sync_agent_data(agent, payload)

    assert first.bookings_synced == 1
    assert second.bookings_synced == 0
    assert second.errors_count == 0
    assert Booking.objects.filter(ticket_number="BF2026000001").count() == 1


# --------------------------------------------------------------------------- #
# Bookings — conflits de siege
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_sync_with_two_seat_conflicts_reassigns_seats():
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    # Sieges "1" et "2" deja occupes en base (synchronises plus tot).
    BookingFactory(trip=trip, seat_number="1", status=BookingStatus.PAID)
    BookingFactory(trip=trip, seat_number="2", status=BookingStatus.PAID)

    payload = {
        "bookings": [
            _booking_item(trip, "BF2026000010", seat_number="1"),
            _booking_item(trip, "BF2026000011", seat_number="2", phone="+22670000099"),
        ]
    }

    log = sync_agent_data(agent, payload)

    assert log.bookings_synced == 2
    assert log.conflicts_count == 2
    assert log.errors_count == 0

    conflicts = SyncConflict.objects.filter(sync_log=log).order_by("reference")
    assert all(c.conflict_type == SyncConflictType.SEAT_CONFLICT for c in conflicts)
    assert all(c.resolved for c in conflicts)
    # Les nouveaux sieges different de ceux demandes.
    first = Booking.objects.get(ticket_number="BF2026000010")
    second = Booking.objects.get(ticket_number="BF2026000011")
    assert first.seat_number not in {"1", "2"}
    assert second.seat_number not in {"1", "2"}
    assert first.seat_number != second.seat_number
    # La resolution est decrite en francais.
    assert "Nouveau siege attribue" in conflicts[0].resolution


@pytest.mark.django_db
def test_sync_rejects_booking_on_full_trip():
    trip = make_company_trip(total_seats=10, available_seats=0)
    agent = make_guichet_agent(trip.route.company)
    payload = {"bookings": [_booking_item(trip, "BF2026000020")]}

    log = sync_agent_data(agent, payload)

    assert log.bookings_synced == 0
    assert log.errors_count == 1
    error = SyncConflict.objects.get(sync_log=log)
    assert error.conflict_type == SyncConflictType.TRIP_FULL
    assert error.resolved is False


@pytest.mark.django_db
def test_sync_rejects_booking_on_cancelled_trip():
    trip = make_company_trip(total_seats=10, status=Trip.TripStatus.CANCELLED)
    agent = make_guichet_agent(trip.route.company)
    payload = {"bookings": [_booking_item(trip, "BF2026000030")]}

    log = sync_agent_data(agent, payload)

    assert log.errors_count == 1
    error = SyncConflict.objects.get(sync_log=log)
    assert error.conflict_type == SyncConflictType.TRIP_UNAVAILABLE


@pytest.mark.django_db
def test_sync_rejects_booking_of_other_company_trip():
    # Isolation multi-tenant : un agent ne peut pas synchroniser le voyage
    # d'une autre compagnie.
    foreign_trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(make_company_trip().route.company)
    payload = {"bookings": [_booking_item(foreign_trip, "BF2026000040")]}

    log = sync_agent_data(agent, payload)

    assert log.bookings_synced == 0
    assert log.errors_count == 1
    assert SyncConflict.objects.get(sync_log=log).conflict_type == (
        SyncConflictType.INVALID
    )


# --------------------------------------------------------------------------- #
# Colis
# --------------------------------------------------------------------------- #
def _parcel_item(route, tracking_number, **overrides):
    item = {
        "tracking_number": tracking_number,
        "origin_city": route.origin_city_id,
        "destination_city": route.destination_city_id,
        "sender_name": "Issa KABORE",
        "sender_phone": "+22670000010",
        "recipient_name": "Fatou DIALLO",
        "recipient_phone": "+22660000011",
        "description": "Carton",
        "weight_kg": "5.00",
        "offline_created_at": timezone.now(),
    }
    item.update(overrides)
    return item


@pytest.mark.django_db
def test_sync_parcels_registers_and_prices(monkeypatch):
    from apps.routes.tests.factories import RouteFactory

    route = RouteFactory(distance_km=80)
    agent = make_guichet_agent(route.company)
    payload = {"parcels": [_parcel_item(route, "COL2026000001")]}

    log = sync_agent_data(agent, payload)

    assert log.parcels_synced == 1
    parcel = Parcel.objects.get(tracking_number="COL2026000001")
    assert parcel.is_offline is True
    assert parcel.synced_at is not None
    assert parcel.tariff == 1750  # 5 * 250 + 500 (tier court)


@pytest.mark.django_db
def test_sync_parcels_idempotent():
    from apps.routes.tests.factories import RouteFactory

    route = RouteFactory(distance_km=80)
    agent = make_guichet_agent(route.company)
    payload = {"parcels": [_parcel_item(route, "COL2026000001")]}

    sync_agent_data(agent, payload)
    second = sync_agent_data(agent, payload)

    assert second.parcels_synced == 0
    assert Parcel.objects.filter(tracking_number="COL2026000001").count() == 1


@pytest.mark.django_db
def test_sync_parcels_rejects_unpriceable_route():
    from apps.geography.tests.factories import CityFactory

    company = make_company_trip().route.company
    agent = make_guichet_agent(company)
    # Deux villes sans trajet de la compagnie -> tarif impossible -> rejet.
    origin = CityFactory()
    destination = CityFactory()
    payload = {
        "parcels": [
            {
                "tracking_number": "COL2026000099",
                "origin_city": origin.id,
                "destination_city": destination.id,
                "sender_name": "Issa",
                "sender_phone": "+22670000010",
                "recipient_name": "Fatou",
                "recipient_phone": "+22660000011",
                "weight_kg": "5.00",
                "offline_created_at": timezone.now(),
            }
        ]
    }

    log = sync_agent_data(agent, payload)

    assert log.parcels_synced == 0
    assert log.errors_count == 1
    assert SyncConflict.objects.get(sync_log=log).conflict_type == (
        SyncConflictType.INVALID
    )


# --------------------------------------------------------------------------- #
# Validations d'embarquement
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_sync_validations_creates_boarding():
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    payload = {
        "validations": [
            {"ticket_number": booking.ticket_number, "offline_created_at": timezone.now()}
        ]
    }

    log = sync_agent_data(agent, payload)

    assert log.validations_synced == 1
    validation = BoardingValidation.objects.get(booking=booking)
    assert validation.is_offline is True
    assert validation.synced_at is not None


@pytest.mark.django_db
def test_sync_validations_idempotent():
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    payload = {
        "validations": [
            {"ticket_number": booking.ticket_number, "offline_created_at": timezone.now()}
        ]
    }

    sync_agent_data(agent, payload)
    second = sync_agent_data(agent, payload)

    assert second.validations_synced == 0
    assert BoardingValidation.objects.filter(booking=booking).count() == 1


# --------------------------------------------------------------------------- #
# Donnees hors ligne
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_get_offline_data_returns_today_trips_and_arrivals():
    trip = make_company_trip(total_seats=10, departure_time=timezone.now())
    company = trip.route.company
    agent = make_guichet_agent(company)
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    # Colis arrive dans la compagnie de l'agent.
    ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
    # Colis non arrive : exclu.
    ParcelFactory(company=company, status=ParcelStatus.REGISTERED)

    data = get_offline_data(agent)

    assert list(data["trips"]) == [trip]
    assert booking in list(data["bookings"])
    assert data["parcel_arrivals"].count() == 1
    assert data["parcel_arrivals"].first().status == ParcelStatus.ARRIVED


@pytest.mark.django_db
def test_get_offline_data_excludes_other_company():
    trip = make_company_trip(total_seats=10, departure_time=timezone.now())
    agent = make_guichet_agent(trip.route.company)
    # Voyage du jour d'une autre compagnie : ne doit pas apparaitre.
    make_company_trip(total_seats=10, departure_time=timezone.now())

    data = get_offline_data(agent)

    assert list(data["trips"]) == [trip]
