import pytest
from django.core.exceptions import ValidationError

from apps.vehicles.models import Vehicle
from apps.vehicles.services import (
    ensure_vehicle_assignable,
    get_available_seats,
    next_available_seat,
)

from .factories import VehicleFactory


@pytest.mark.django_db
def test_get_available_seats_falls_back_to_total_seats():
    vehicle = VehicleFactory(total_seats=3, seat_plan={})

    seats = get_available_seats(vehicle, trip=None)

    assert seats == ["1", "2", "3"]


@pytest.mark.django_db
def test_get_available_seats_uses_layout_and_excludes_reserved():
    vehicle = VehicleFactory(
        seat_plan={"layout": [[1, 2], [3, 4]], "reserved": [1]},
    )

    seats = get_available_seats(vehicle, trip=None)

    assert seats == ["2", "3", "4"]


@pytest.mark.django_db
def test_next_available_seat_returns_first_free():
    vehicle = VehicleFactory(seat_plan={"layout": [[1, 2], [3, 4]], "reserved": []})

    assert next_available_seat(vehicle, trip=None) == "1"


@pytest.mark.django_db
def test_next_available_seat_raises_when_full():
    vehicle = VehicleFactory(seat_plan={"layout": [[1]], "reserved": [1]})

    with pytest.raises(ValidationError):
        next_available_seat(vehicle, trip=None)


@pytest.mark.django_db
def test_vehicle_in_maintenance_cannot_be_assigned():
    vehicle = VehicleFactory(status=Vehicle.VehicleStatus.MAINTENANCE)

    with pytest.raises(ValidationError):
        ensure_vehicle_assignable(vehicle)


@pytest.mark.django_db
def test_active_vehicle_is_assignable():
    vehicle = VehicleFactory(status=Vehicle.VehicleStatus.ACTIVE)

    # Ne doit lever aucune exception.
    ensure_vehicle_assignable(vehicle)
