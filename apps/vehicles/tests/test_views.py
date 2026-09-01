import pytest
from rest_framework.test import APIClient

from apps.users.models import Role, User
from apps.vehicles.models import Vehicle

from .factories import VehicleFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test",
        nom="User",
        phone=phone,
        password="password123",
        role=role,
    )


def _company_admin(api_client, company, phone):
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)
    return admin


@pytest.mark.django_db
def test_company_admin_only_sees_own_vehicles(api_client):
    own = VehicleFactory(registration="11-AA-1111")
    VehicleFactory(registration="11-BB-2222")  # autre compagnie
    _company_admin(api_client, own.company, "+22670000200")

    response = api_client.get("/api/v1/company/vehicles/")

    assert response.status_code == 200
    registrations = [v["registration"] for v in response.data["results"]]
    assert registrations == ["11-AA-1111"]


@pytest.mark.django_db
def test_maintenance_and_activate_actions(api_client):
    vehicle = VehicleFactory(status=Vehicle.VehicleStatus.ACTIVE)
    _company_admin(api_client, vehicle.company, "+22670000201")

    resp = api_client.post(f"/api/v1/company/vehicles/{vehicle.id}/maintenance/")
    assert resp.status_code == 200
    vehicle.refresh_from_db()
    assert vehicle.status == Vehicle.VehicleStatus.MAINTENANCE

    resp = api_client.post(f"/api/v1/company/vehicles/{vehicle.id}/activate/")
    assert resp.status_code == 200
    vehicle.refresh_from_db()
    assert vehicle.status == Vehicle.VehicleStatus.ACTIVE


@pytest.mark.django_db
def test_read_and_write_seat_plan(api_client):
    vehicle = VehicleFactory(seat_plan={})
    _company_admin(api_client, vehicle.company, "+22670000202")

    plan = {"layout": [[1, 2], [3, 4]], "reserved": [0]}
    put = api_client.put(
        f"/api/v1/company/vehicles/{vehicle.id}/seat-plan/",
        plan,
        format="json",
    )
    assert put.status_code == 200

    get = api_client.get(f"/api/v1/company/vehicles/{vehicle.id}/seat-plan/")
    assert get.status_code == 200
    assert get.data["layout"] == [[1, 2], [3, 4]]


@pytest.mark.django_db
def test_company_admin_cannot_access_other_company_vehicle(api_client):
    other = VehicleFactory()
    own = VehicleFactory()
    _company_admin(api_client, own.company, "+22670000203")

    response = api_client.get(f"/api/v1/company/vehicles/{other.id}/")

    assert response.status_code == 404
