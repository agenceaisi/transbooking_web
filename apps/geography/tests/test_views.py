import pytest
from rest_framework.test import APIClient

from apps.users.models import Role, User

from .factories import CityFactory, StationFactory


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


@pytest.mark.django_db
def test_public_can_list_cities_without_auth(api_client):
    CityFactory(name="Ouagadougou")
    CityFactory(name="Bobo-Dioulasso")

    response = api_client.get("/api/v1/cities/")

    assert response.status_code == 200
    names = [c["name"] for c in response.data]
    assert "Ouagadougou" in names
    assert "Bobo-Dioulasso" in names


@pytest.mark.django_db
def test_super_admin_can_create_city(api_client):
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000100")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        "/api/v1/super/cities/",
        {"name": "Koudougou", "region": "Centre-Ouest"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["name"] == "Koudougou"


@pytest.mark.django_db
def test_voyageur_cannot_create_city(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670000101")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/super/cities/", {"name": "Fada"}, format="json"
    )

    assert response.status_code == 403


@pytest.mark.django_db
def test_company_admin_only_sees_own_stations(api_client):
    own = StationFactory(name="Gare A")
    StationFactory(name="Gare B")  # autre compagnie

    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000110")
    own.company.admin_user = admin
    own.company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/stations/")

    assert response.status_code == 200
    names = [s["name"] for s in response.data["results"]]
    assert names == ["Gare A"]


@pytest.mark.django_db
def test_company_admin_creates_station_for_own_company(api_client):
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000111")
    station = StationFactory()
    company = station.company
    station.delete()
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    city = CityFactory(name="Tenkodogo")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        "/api/v1/company/stations/",
        {"city": city.id, "name": "Gare centrale", "address": "Centre-ville"},
        format="json",
    )

    assert response.status_code == 201
    assert company.stations.filter(name="Gare centrale").exists()
