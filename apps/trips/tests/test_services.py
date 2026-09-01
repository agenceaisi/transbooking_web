from datetime import timedelta

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.routes.tests.factories import RouteFactory
from apps.trips.exceptions import TripAlreadyCompleted
from apps.trips.models import Trip
from apps.trips.services import (
    cancel_trip,
    close_expired_registrations,
    delay_trip,
    generate_trips,
)
from apps.vehicles.models import Vehicle
from apps.vehicles.tests.factories import VehicleFactory

from .factories import TripFactory


@pytest.mark.django_db
def test_generate_trips_creates_expected_count():
    route = RouteFactory()
    vehicle = VehicleFactory(company=route.company, total_seats=40)
    # Tous les jours de la semaine -> 7 voyages sur 7 jours.
    config = [{"time": "06:00", "days": [0, 1, 2, 3, 4, 5, 6], "vehicle_id": vehicle.id}]

    trips = generate_trips(route.id, config, days=7)

    assert len(trips) == 7
    assert all(t.available_seats == 40 for t in trips)
    assert all(t.price == route.base_price for t in trips)


@pytest.mark.django_db
def test_generate_trips_respects_weekday_filter():
    route = RouteFactory()
    vehicle = VehicleFactory(company=route.company)
    # Un seul jour de la semaine actif -> au plus 1 voyage sur 7 jours.
    config = [{"time": "08:00", "days": [0], "vehicle_id": vehicle.id}]

    trips = generate_trips(route.id, config, days=7)

    assert len(trips) == 1
    assert trips[0].departure_time.weekday() == 0


@pytest.mark.django_db
def test_generate_trips_rejects_vehicle_in_maintenance():
    route = RouteFactory()
    vehicle = VehicleFactory(
        company=route.company, status=Vehicle.VehicleStatus.MAINTENANCE
    )
    config = [{"time": "06:00", "days": [0, 1, 2, 3, 4, 5, 6], "vehicle_id": vehicle.id}]

    with pytest.raises(ValidationError):
        generate_trips(route.id, config, days=7)


@pytest.mark.django_db
def test_cancel_trip_sets_status_and_sends_sms(monkeypatch):
    trip = TripFactory()
    sent = []
    monkeypatch.setattr(
        "apps.trips.services._passenger_phones", lambda t: ["+22670000999"]
    )
    monkeypatch.setattr(
        "apps.trips.services.send_sms", lambda phone, message: sent.append(phone)
    )

    cancel_trip(trip, "Panne mecanique")

    trip.refresh_from_db()
    assert trip.status == Trip.TripStatus.CANCELLED
    assert trip.cancellation_reason == "Panne mecanique"
    assert sent == ["+22670000999"]


@pytest.mark.django_db
def test_cancel_trip_already_cancelled_raises():
    trip = TripFactory(status=Trip.TripStatus.CANCELLED)

    with pytest.raises(ValidationError):
        cancel_trip(trip, "Deja annule")


@pytest.mark.django_db
def test_trip_registration_closes_at_defaults_to_departure_time():
    departure = timezone.now() + timedelta(days=1)
    trip = TripFactory(departure_time=departure)

    assert trip.registration_closes_at == departure


@pytest.mark.django_db
def test_delay_trip_shifts_departure_and_registration_closes():
    departure = timezone.now() + timedelta(hours=1)
    trip = TripFactory(departure_time=departure)

    delay_trip(trip, 10)

    trip.refresh_from_db()
    assert trip.departure_time == departure + timedelta(minutes=10)
    assert trip.registration_closes_at == departure + timedelta(minutes=10)
    assert trip.status == Trip.TripStatus.DELAYED
    assert trip.delay_minutes == 10


@pytest.mark.django_db
def test_delay_trip_is_cumulative():
    trip = TripFactory(departure_time=timezone.now() + timedelta(hours=1))

    delay_trip(trip, 10)
    delay_trip(trip, 5)

    trip.refresh_from_db()
    assert trip.delay_minutes == 15


@pytest.mark.django_db
def test_delay_trip_rejects_already_completed():
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)

    with pytest.raises(TripAlreadyCompleted):
        delay_trip(trip, 10)


@pytest.mark.django_db
def test_close_expired_registrations_flips_scheduled_trip_to_completed():
    trip = TripFactory(departure_time=timezone.now() - timedelta(minutes=5))

    closed = close_expired_registrations()

    trip.refresh_from_db()
    assert closed == 1
    assert trip.status == Trip.TripStatus.COMPLETED


@pytest.mark.django_db
def test_close_expired_registrations_ignores_future_trips():
    trip = TripFactory(departure_time=timezone.now() + timedelta(hours=1))

    closed = close_expired_registrations()

    trip.refresh_from_db()
    assert closed == 0
    assert trip.status == Trip.TripStatus.SCHEDULED


@pytest.mark.django_db
def test_close_expired_registrations_ignores_already_cancelled_trips():
    trip = TripFactory(
        departure_time=timezone.now() - timedelta(minutes=5),
        status=Trip.TripStatus.CANCELLED,
    )

    closed = close_expired_registrations()

    trip.refresh_from_db()
    assert closed == 0
    assert trip.status == Trip.TripStatus.CANCELLED
