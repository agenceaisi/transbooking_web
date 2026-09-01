import pytest
from rest_framework.test import APIClient

from apps.geography.tests.factories import CityFactory
from apps.users.models import Role, User

from .factories import RouteFactory, RouteStopFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


def _company_admin(api_client, company, phone):
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)
    return admin


@pytest.mark.django_db
def test_company_admin_only_sees_own_routes(api_client):
    own = RouteFactory()
    RouteFactory()  # autre compagnie
    _company_admin(api_client, own.company, "+22670000300")

    response = api_client.get("/api/v1/company/routes/")

    assert response.status_code == 200
    ids = [r["id"] for r in response.data["results"]]
    assert ids == [own.id]


@pytest.mark.django_db
def test_create_route_attached_to_admin_company(api_client):
    admin_route = RouteFactory()
    _company_admin(api_client, admin_route.company, "+22670000301")
    origin = CityFactory()
    destination = CityFactory()

    response = api_client.post(
        "/api/v1/company/routes/",
        {
            "origin_city": origin.id,
            "destination_city": destination.id,
            "distance_km": "120.00",
            "base_price": "4000.00",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["origin_city"] == origin.id


@pytest.mark.django_db
def test_create_route_same_city_rejected(api_client):
    route = RouteFactory()
    _company_admin(api_client, route.company, "+22670000302")
    city = CityFactory()

    response = api_client.post(
        "/api/v1/company/routes/",
        {"origin_city": city.id, "destination_city": city.id, "base_price": "4000"},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_duplicate_route_creates_reverse(api_client):
    route = RouteFactory()
    RouteStopFactory(route=route, stop_order=1)
    _company_admin(api_client, route.company, "+22670000303")

    response = api_client.post(f"/api/v1/company/routes/{route.id}/duplicate/")

    assert response.status_code == 201
    assert response.data["origin_city"] == route.destination_city_id
    assert response.data["destination_city"] == route.origin_city_id


@pytest.mark.django_db
def test_nested_stops_crud(api_client):
    route = RouteFactory()
    _company_admin(api_client, route.company, "+22670000304")
    city = CityFactory()

    create = api_client.post(
        f"/api/v1/company/routes/{route.id}/stops/",
        {"city": city.id, "stop_order": 1, "stop_price": "1500"},
        format="json",
    )
    assert create.status_code == 201
    stop_id = create.data["id"]

    listing = api_client.get(f"/api/v1/company/routes/{route.id}/stops/")
    assert listing.status_code == 200
    assert listing.data["count"] == 1

    delete = api_client.delete(
        f"/api/v1/company/routes/{route.id}/stops/{stop_id}/"
    )
    assert delete.status_code == 204


@pytest.mark.django_db
def test_company_admin_cannot_access_other_company_route(api_client):
    other = RouteFactory()
    own = RouteFactory()
    _company_admin(api_client, own.company, "+22670000305")

    response = api_client.get(f"/api/v1/company/routes/{other.id}/")

    assert response.status_code == 404
