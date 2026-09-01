import pytest
from rest_framework.test import APIClient

from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import StationFactory
from apps.parcels.models import ParcelNotification, ParcelStatus
from apps.routes.tests.factories import RouteFactory
from apps.users.models import AgentProfile, Role, User

from .factories import ParcelFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.parcels.services.send_sms", lambda *a, **k: None)


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


def _guichet(company, station=None, phone="+22670003000") -> User:
    user = _make_user(Role.RoleName.AGENT_GUICHET, phone)
    AgentProfile.objects.create(
        user=user,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
        station=station,
    )
    return user


# --------------------------------------------------------------------------- #
# Public — suivi
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_public_track_returns_status_and_history(api_client):
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    response = api_client.get(f"/api/v1/parcels/track/{parcel.tracking_number}/")

    assert response.status_code == 200
    assert response.data["status"] == ParcelStatus.ARRIVED
    assert response.data["tracking_number"] == parcel.tracking_number
    assert "history" in response.data
    # Le telephone destinataire est masque pour le public.
    assert "*" in response.data["recipient_phone"]


@pytest.mark.django_db
def test_public_track_history_is_typed_with_location_and_timestamp(api_client):
    parcel = ParcelFactory(status=ParcelStatus.NOTIFIED)
    ParcelNotification.objects.create(
        parcel=parcel,
        method="sms",
        message="A bord du bus TB-4821.",
    )

    response = api_client.get(f"/api/v1/parcels/track/{parcel.tracking_number}/")

    assert response.status_code == 200
    history = response.data["history"]
    # Etape d'enregistrement typee : statut, libelle, lieu, horodatage.
    first = history[0]
    assert first["status"] == ParcelStatus.REGISTERED
    assert first["status_display"] == "Enregistre"
    assert first["location"] == parcel.origin_city.name
    assert first["timestamp"] is not None
    # La notification devient une etape « prevenu » localisee a l'arrivee.
    notified = history[-1]
    assert notified["status"] == ParcelStatus.NOTIFIED
    assert notified["location"] == parcel.destination_city.name
    assert notified["note"] == "A bord du bus TB-4821."


@pytest.mark.django_db
def test_public_track_exposes_current_location_and_estimated_delivery(api_client):
    from datetime import timedelta

    from django.utils import timezone

    from apps.routes.tests.factories import RouteFactory
    from apps.trips.tests.factories import TripFactory

    arrival = timezone.now() + timedelta(hours=6)
    route = RouteFactory()
    trip = TripFactory(route=route, arrival_time=arrival)
    parcel = ParcelFactory(
        company=route.company, status=ParcelStatus.IN_TRANSIT, trip=trip
    )

    response = api_client.get(f"/api/v1/parcels/track/{parcel.tracking_number}/")

    assert response.status_code == 200
    # En transit : position intermediaire inconnue => null (pas d'invention).
    assert response.data["current_location"] is None
    # Livraison estimee = heure d'arrivee prevue du bus transporteur.
    assert response.data["estimated_delivery"] is not None


@pytest.mark.django_db
def test_public_track_unknown_returns_404(api_client):
    response = api_client.get("/api/v1/parcels/track/COL2026999999/")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Agent guichet
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_agent_registers_parcel(api_client):
    route = RouteFactory(distance_km=250)
    station = StationFactory(company=route.company, city=route.origin_city)
    agent = _guichet(route.company, station=station)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/parcels/",
        {
            "origin_city": route.origin_city_id,
            "destination_city": route.destination_city_id,
            "sender_name": "Issa KABORE",
            "sender_phone": "+22670000001",
            "recipient_name": "Fatou DIALLO",
            "recipient_phone": "+22660000001",
            "weight_kg": "3",
        },
        format="json",
    )

    assert response.status_code == 201
    # La reponse 201 est le ParcelRead (id, tarif, tracking_number, qr_code, statut) :
    # il n'existe pas de recherche par tracking_number pour la rattraper apres coup.
    assert response.data["id"] is not None
    assert response.data["tracking_number"].startswith("COL")
    assert response.data["tariff"] == "1350.00"  # 3 * 200 + 750
    assert response.data["qr_code"] != ""
    assert response.data["status"] == ParcelStatus.REGISTERED


@pytest.mark.django_db
def test_agent_registers_parcel_with_null_optional_fields(api_client):
    # Le client Flutter serialise ses DTO avec `null` explicite pour un champ
    # facultatif non renseigne (description, is_offline...) plutot que de
    # l'omettre : ces valeurs ne doivent pas etre rejetees (regression #46).
    route = RouteFactory(distance_km=250)
    station = StationFactory(company=route.company, city=route.origin_city)
    agent = _guichet(route.company, station=station)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/parcels/",
        {
            "origin_city": route.origin_city_id,
            "destination_city": route.destination_city_id,
            "sender_name": "Issa KABORE",
            "sender_phone": "+22670000001",
            "recipient_name": "Fatou DIALLO",
            "recipient_phone": "+22660000001",
            "weight_kg": "3",
            "description": None,
            "tracking_number": None,
            "is_offline": None,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["is_offline"] is False


@pytest.mark.django_db
def test_agent_arrivals_lists_arrived_at_their_station(api_client):
    company = CompanyFactory()
    station = StationFactory(company=company)
    other_station = StationFactory(company=company)
    agent = _guichet(company, station=station)
    api_client.force_authenticate(user=agent)

    here = ParcelFactory(
        company=company, destination_station=station, status=ParcelStatus.ARRIVED
    )
    ParcelFactory(
        company=company, destination_station=other_station, status=ParcelStatus.ARRIVED
    )
    ParcelFactory(
        company=company, destination_station=station, status=ParcelStatus.REGISTERED
    )

    response = api_client.get("/api/v1/agent/parcels/arrivals/")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    tracking_numbers = [item["tracking_number"] for item in results]
    assert tracking_numbers == [here.tracking_number]


@pytest.mark.django_db
def test_agent_notify_sends_sms_and_blocks_duplicate(api_client):
    company = CompanyFactory()
    station = StationFactory(company=company)
    agent = _guichet(company, station=station)
    api_client.force_authenticate(user=agent)
    parcel = ParcelFactory(company=company, status=ParcelStatus.ARRIVED)

    first = api_client.post(f"/api/v1/agent/parcels/{parcel.id}/notify/", {}, format="json")
    assert first.status_code == 200
    assert first.data["status"] == ParcelStatus.NOTIFIED

    second = api_client.post(f"/api/v1/agent/parcels/{parcel.id}/notify/", {}, format="json")
    assert second.status_code == 400


@pytest.mark.django_db
def test_agent_cannot_see_other_company_parcel(api_client):
    company = CompanyFactory()
    agent = _guichet(company)
    api_client.force_authenticate(user=agent)
    other = ParcelFactory()  # autre compagnie

    response = api_client.get(f"/api/v1/agent/parcels/{other.id}/")
    assert response.status_code == 404


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


def _company_admin(company, phone="+22670004000") -> User:
    user = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = user
    company.save(update_fields=["admin_user", "updated_at"])
    return user


@pytest.mark.django_db
def test_company_admin_lists_only_own_parcels(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)
    mine = ParcelFactory(company=company)
    ParcelFactory()  # autre compagnie

    response = api_client.get("/api/v1/company/parcels/")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    tracking_numbers = [item["tracking_number"] for item in results]
    assert tracking_numbers == [mine.tracking_number]


@pytest.mark.django_db
def test_company_admin_changes_status(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)
    parcel = ParcelFactory(company=company, status=ParcelStatus.NOTIFIED)

    response = api_client.post(
        f"/api/v1/company/parcels/{parcel.id}/status/",
        {"status": ParcelStatus.COLLECTED},
        format="json",
    )

    assert response.status_code == 200
    parcel.refresh_from_db()
    assert parcel.status == ParcelStatus.COLLECTED
    assert parcel.collected_at is not None


@pytest.mark.django_db
def test_company_admin_notify_again_bypasses_guard(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)
    parcel = ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
    ParcelNotification.objects.create(parcel=parcel, method="sms")

    response = api_client.post(
        f"/api/v1/company/parcels/{parcel.id}/notify-again/", {}, format="json"
    )

    assert response.status_code == 200
    assert ParcelNotification.objects.filter(parcel=parcel, method="sms").count() == 2


@pytest.mark.django_db
def test_company_export_excel(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)
    ParcelFactory(company=company)

    response = api_client.get("/api/v1/company/parcels/export/?format=excel")

    assert response.status_code == 200
    assert "attachment" in response["Content-Disposition"]


@pytest.mark.django_db
def test_voyageur_cannot_register_parcel(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670005000")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post("/api/v1/agent/parcels/", {}, format="json")
    assert response.status_code == 403
