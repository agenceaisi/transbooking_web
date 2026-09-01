from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.geography.tests.factories import StationFactory
from apps.routes.tests.factories import RouteFactory, RouteStopFactory
from apps.trips.models import Trip
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.tests.factories import VehicleFactory

from .factories import TripFactory


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


# --------------------------------------------------------------------------- #
# Company admin
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_create_trip_initialises_available_seats(api_client):
    route = RouteFactory()
    vehicle = VehicleFactory(company=route.company, total_seats=50)
    _company_admin(api_client, route.company, "+22670000400")

    response = api_client.post(
        "/api/v1/company/trips/",
        {
            "route": route.id,
            "vehicle": vehicle.id,
            "departure_time": (timezone.now() + timedelta(days=2)).isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201
    trip = Trip.objects.get(pk=response.data["id"])
    assert trip.available_seats == 50
    assert trip.price == route.base_price


@pytest.mark.django_db
def test_company_admin_only_sees_own_trips(api_client):
    own = TripFactory()
    TripFactory()  # autre compagnie
    _company_admin(api_client, own.route.company, "+22670000401")

    response = api_client.get("/api/v1/company/trips/")

    assert response.status_code == 200
    ids = [t["id"] for t in response.data["results"]]
    assert ids == [own.id]


@pytest.mark.django_db
def test_delete_trip_cancels_and_notifies(api_client, monkeypatch):
    trip = TripFactory()
    _company_admin(api_client, trip.route.company, "+22670000402")
    monkeypatch.setattr("apps.trips.services._passenger_phones", lambda t: [])

    response = api_client.delete(
        f"/api/v1/company/trips/{trip.id}/", {"reason": "Greve"}, format="json"
    )

    assert response.status_code == 200
    trip.refresh_from_db()
    assert trip.status == Trip.TripStatus.CANCELLED


# --------------------------------------------------------------------------- #
# Recherche publique
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_public_search_filters_by_cities_and_passengers(api_client):
    route = RouteFactory()
    match = TripFactory(route=route, available_seats=10)
    # Pas assez de places.
    TripFactory(route=route, available_seats=1)
    # Autre trajet.
    TripFactory()

    response = api_client.get(
        "/api/v1/trips/search/",
        {
            "origin_city": route.origin_city_id,
            "dest_city": route.destination_city_id,
            "passengers": 5,
        },
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.data["results"]]
    assert ids == [match.id]


@pytest.mark.django_db
def test_public_search_direct_excludes_routes_with_stops(api_client):
    route_with_stop = RouteFactory()
    RouteStopFactory(route=route_with_stop, stop_order=1)
    TripFactory(route=route_with_stop)
    direct_trip = TripFactory()

    response = api_client.get("/api/v1/trips/search/", {"direct": "true"})

    assert response.status_code == 200
    ids = [t["id"] for t in response.data["results"]]
    assert direct_trip.id in ids
    assert all(tid != route_with_stop.trips.first().id for tid in ids)


@pytest.mark.django_db
def test_public_search_exposes_company_rating_and_direct_badge(api_client):
    from apps.reviews.tests.factories import ReviewFactory

    route = RouteFactory()
    trip = TripFactory(route=route)
    # Deux avis (4 et 5) => note moyenne 4.5 exposee sur la carte de resultat.
    ReviewFactory(company=route.company, trip=trip, rating=4)
    ReviewFactory(company=route.company, rating=5)

    response = api_client.get("/api/v1/trips/search/")

    assert response.status_code == 200
    card = next(t for t in response.data["results"] if t["id"] == trip.id)
    assert card["company"] == route.company_id
    assert card["company_name"] == route.company.name
    assert card["company_rating"] == 4.5
    assert card["is_direct"] is True
    assert card["stops_count"] == 0
    assert card["duration_minutes"] == route.duration_minutes


@pytest.mark.django_db
def test_public_search_marks_route_with_stops_as_indirect(api_client):
    route = RouteFactory()
    RouteStopFactory(route=route, stop_order=1)
    trip = TripFactory(route=route)

    response = api_client.get("/api/v1/trips/search/")

    card = next(t for t in response.data["results"] if t["id"] == trip.id)
    assert card["is_direct"] is False
    assert card["stops_count"] == 1


@pytest.mark.django_db
def test_public_search_filters_by_company_and_min_rating(api_client):
    from apps.reviews.tests.factories import ReviewFactory

    good_route = RouteFactory()
    good_trip = TripFactory(route=good_route)
    ReviewFactory(company=good_route.company, trip=good_trip, rating=5)

    weak_route = RouteFactory()
    weak_trip = TripFactory(route=weak_route)
    ReviewFactory(company=weak_route.company, trip=weak_trip, rating=2)

    # Filtre compagnie.
    by_company = api_client.get(
        "/api/v1/trips/search/", {"company": good_route.company_id}
    )
    ids = [t["id"] for t in by_company.data["results"]]
    assert ids == [good_trip.id]

    # Filtre note minimale : seule la compagnie bien notee ressort.
    by_rating = api_client.get("/api/v1/trips/search/", {"min_rating": 4})
    ids = [t["id"] for t in by_rating.data["results"]]
    assert good_trip.id in ids
    assert weak_trip.id not in ids


@pytest.mark.django_db
def test_public_trip_detail_exposes_available_seats(api_client):
    trip = TripFactory()

    response = api_client.get(f"/api/v1/trips/{trip.id}/")

    assert response.status_code == 200
    assert "available_seat_numbers" in response.data
    # Les champs compagnie/direct sont aussi presents sur le detail (phase 4B).
    assert response.data["company"] == trip.route.company_id
    assert response.data["is_direct"] is True


# --------------------------------------------------------------------------- #
# Agent — programme du jour
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_today_trips_filtered_by_station(api_client):
    route = RouteFactory()
    station = StationFactory(company=route.company, city=route.origin_city)
    route.origin_station = station
    route.save(update_fields=["origin_station"])

    today_trip = TripFactory(route=route, departure_time=timezone.now())
    # Voyage de demain : exclu.
    TripFactory(route=route, departure_time=timezone.now() + timedelta(days=1))

    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000403")
    AgentProfile.objects.create(
        user=agent,
        company=route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
        station=station,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/agent/trips/today/")

    assert response.status_code == 200
    ids = [t["id"] for t in response.data]
    assert ids == [today_trip.id]


@pytest.mark.django_db
def test_agent_today_trips_date_param_selects_another_day(api_client):
    route = RouteFactory()
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000404")
    AgentProfile.objects.create(
        user=agent,
        company=route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
        vehicle=VehicleFactory(company=route.company),
    )
    api_client.force_authenticate(user=agent)

    tomorrow = timezone.now() + timedelta(days=1)
    tomorrow_trip = TripFactory(
        route=route, vehicle=agent.agent_profile.vehicle, departure_time=tomorrow
    )
    # Voyage d'aujourd'hui : exclu du filtre sur `date`.
    TripFactory(
        route=route, vehicle=agent.agent_profile.vehicle, departure_time=timezone.now()
    )

    response = api_client.get(
        f"/api/v1/agent/trips/today/?date={tomorrow.date().isoformat()}"
    )

    assert response.status_code == 200
    ids = [t["id"] for t in response.data]
    assert ids == [tomorrow_trip.id]


@pytest.mark.django_db
def test_agent_today_trips_invalid_date_param_returns_400(api_client):
    route = RouteFactory()
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000405")
    AgentProfile.objects.create(
        user=agent,
        company=route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
        vehicle=VehicleFactory(company=route.company),
    )
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/agent/trips/today/?date=12-08-2026")

    assert response.status_code == 400


@pytest.mark.django_db
def test_trip_read_exposes_driver_fields(api_client):
    trip = TripFactory(driver_name="Salif Traore", driver_phone="+22670001122")

    response = api_client.get(f"/api/v1/trips/{trip.id}/")

    assert response.status_code == 200
    assert response.data["driver_name"] == "Salif Traore"
    assert response.data["driver_phone"] == "+22670001122"


@pytest.mark.django_db
def test_trip_read_exposes_vehicle_type_and_total_seats(api_client):
    vehicle = VehicleFactory(vehicle_type="vip", total_seats=45)
    trip = TripFactory(vehicle=vehicle)

    response = api_client.get(f"/api/v1/trips/{trip.id}/")

    assert response.status_code == 200
    assert response.data["vehicle_type"] == "vip"
    assert response.data["total_seats"] == 45


@pytest.mark.django_db
def test_trip_read_vehicle_type_is_null_when_blank(api_client):
    vehicle = VehicleFactory(vehicle_type="", total_seats=30)
    trip = TripFactory(vehicle=vehicle)

    response = api_client.get(f"/api/v1/trips/{trip.id}/")

    assert response.status_code == 200
    assert response.data["vehicle_type"] is None


@pytest.mark.django_db
def test_trip_read_exposes_registration_closes_at(api_client):
    departure = timezone.now() + timedelta(days=1)
    trip = TripFactory(departure_time=departure)

    response = api_client.get(f"/api/v1/trips/{trip.id}/")

    assert response.status_code == 200
    assert parse_datetime(response.data["registration_closes_at"]) == departure


# --------------------------------------------------------------------------- #
# Report d'un voyage (« ajouter des minutes »)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_guichet_can_delay_trip(api_client):
    departure = timezone.now() + timedelta(hours=2)
    trip = TripFactory(departure_time=departure)
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000410")
    AgentProfile.objects.create(
        user=agent,
        company=trip.route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 10}, format="json"
    )

    assert response.status_code == 200
    trip.refresh_from_db()
    assert trip.departure_time == departure + timedelta(minutes=10)
    assert trip.registration_closes_at == departure + timedelta(minutes=10)
    assert trip.status == Trip.TripStatus.DELAYED
    assert response.data["status"] == "delayed"


@pytest.mark.django_db
def test_controleur_delay_is_cumulative(api_client):
    departure = timezone.now() + timedelta(hours=2)
    trip = TripFactory(departure_time=departure)
    agent = _make_user(Role.RoleName.CONTROLEUR, "+22670000411")
    AgentProfile.objects.create(
        user=agent,
        company=trip.route.company,
        agent_type=AgentProfile.AgentType.CONTROLEUR,
    )
    api_client.force_authenticate(user=agent)

    api_client.post(f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 10}, format="json")
    api_client.post(f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 5}, format="json")

    trip.refresh_from_db()
    assert trip.departure_time == departure + timedelta(minutes=15)
    assert trip.delay_minutes == 15


@pytest.mark.django_db
def test_company_admin_can_delay_trip(api_client):
    trip = TripFactory()
    _company_admin(api_client, trip.route.company, "+22670000412")

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 5}, format="json"
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_delay_trip_rejects_completed_trip(api_client):
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000413")
    AgentProfile.objects.create(
        user=agent,
        company=trip.route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 10}, format="json"
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_delay_trip_respects_company_isolation(api_client):
    trip = TripFactory()
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000414")
    AgentProfile.objects.create(
        user=agent,
        company=VehicleFactory().company,  # autre compagnie
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 10}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_delay_trip_requires_minutes(api_client):
    trip = TripFactory()
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670000415")
    AgentProfile.objects.create(
        user=agent,
        company=trip.route.company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {}, format="json"
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_voyageur_cannot_delay_trip(api_client):
    trip = TripFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670000416")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/delay/", {"minutes": 10}, format="json"
    )

    assert response.status_code == 403
