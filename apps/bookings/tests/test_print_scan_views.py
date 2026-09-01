"""Impression de billet et historique des scans agent (cf. PROMPT_SUP A7)."""
import pytest
from rest_framework.test import APIClient

from apps.bookings.models import BookingStatus, ScanLog, ScanResult
from apps.companies.tests.factories import CompanyFactory
from apps.routes.tests.factories import RouteFactory
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.tests.factories import VehicleFactory

from .factories import BookingFactory


SCAN_URL = "/api/v1/agent/scan/"
SCAN_HISTORY_URL = "/api/v1/agent/scan/history/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.bookings.services.send_sms", lambda *a, **k: None)


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


def _make_agent(company, phone: str, role_name=Role.RoleName.AGENT_GUICHET) -> User:
    agent = _make_user(role_name, phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=(
            AgentProfile.AgentType.GUICHET
            if role_name == Role.RoleName.AGENT_GUICHET
            else AgentProfile.AgentType.CONTROLEUR
        ),
    )
    return agent


def _booking_for_company(company, **kwargs):
    route = RouteFactory(company=company)
    vehicle = VehicleFactory(company=company, total_seats=30)
    trip = TripFactory(route=route, vehicle=vehicle)
    return BookingFactory(trip=trip, **kwargs)


# --------------------------------------------------------------------------- #
# Impression du billet au guichet
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_prints_ticket_and_gets_payload(api_client):
    company = CompanyFactory()
    booking = _booking_for_company(company, status=BookingStatus.PAID)
    agent = _make_agent(company, "+22675000001")
    api_client.force_authenticate(user=agent)

    response = api_client.post(f"/api/v1/agent/bookings/{booking.ticket_number}/print/")

    assert response.status_code == 200
    assert response.data["ticket_number"] == booking.ticket_number
    assert response.data["seat_number"] == booking.seat_number
    assert response.data["company_name"] == company.name
    assert response.data["print_count"] == 1
    booking.refresh_from_db()
    assert booking.printed_at is not None
    assert booking.print_count == 1


@pytest.mark.django_db
def test_reprint_increments_the_counter(api_client):
    company = CompanyFactory()
    booking = _booking_for_company(company, status=BookingStatus.PAID)
    agent = _make_agent(company, "+22675000002")
    api_client.force_authenticate(user=agent)

    api_client.post(f"/api/v1/agent/bookings/{booking.ticket_number}/print/")
    response = api_client.post(f"/api/v1/agent/bookings/{booking.ticket_number}/print/")

    assert response.data["print_count"] == 2


@pytest.mark.django_db
def test_agent_cannot_print_ticket_of_another_company(api_client):
    mine = CompanyFactory()
    other = CompanyFactory()
    foreign_booking = _booking_for_company(other, status=BookingStatus.PAID)
    agent = _make_agent(mine, "+22675000003")
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        f"/api/v1/agent/bookings/{foreign_booking.ticket_number}/print/"
    )

    assert response.status_code == 404
    foreign_booking.refresh_from_db()
    assert foreign_booking.print_count == 0


@pytest.mark.django_db
def test_voyageur_cannot_print_at_the_counter(api_client):
    company = CompanyFactory()
    booking = _booking_for_company(company, status=BookingStatus.PAID)
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22675000004")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(f"/api/v1/agent/bookings/{booking.ticket_number}/print/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_print_requires_authentication(api_client):
    company = CompanyFactory()
    booking = _booking_for_company(company)

    response = api_client.post(f"/api/v1/agent/bookings/{booking.ticket_number}/print/")

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Historique des scans
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_scan_is_recorded_in_history(api_client):
    company = CompanyFactory()
    booking = _booking_for_company(company, status=BookingStatus.PAID)
    controleur = _make_agent(company, "+22675000010", Role.RoleName.CONTROLEUR)
    api_client.force_authenticate(user=controleur)

    api_client.post(SCAN_URL, {"ticket_number": booking.ticket_number}, format="json")
    response = api_client.get(SCAN_HISTORY_URL)

    assert response.status_code == 200
    assert response.data["count"] == 1
    entry = response.data["results"][0]
    assert entry["ticket_number"] == booking.ticket_number
    assert entry["result"] == ScanResult.VALID
    assert entry["passenger_name"] == booking.passenger_name
    assert entry["scanned_at"] is not None


@pytest.mark.django_db
def test_unknown_ticket_scan_is_also_traced(api_client):
    company = CompanyFactory()
    controleur = _make_agent(company, "+22675000011", Role.RoleName.CONTROLEUR)
    api_client.force_authenticate(user=controleur)

    scan = api_client.post(SCAN_URL, {"ticket_number": "BF2026999999"}, format="json")
    response = api_client.get(SCAN_HISTORY_URL)

    assert scan.status_code == 404
    assert response.data["count"] == 1
    assert response.data["results"][0]["result"] == ScanResult.NOT_FOUND
    assert response.data["results"][0]["passenger_name"] is None


@pytest.mark.django_db
def test_history_is_limited_to_the_last_50_scans(api_client):
    company = CompanyFactory()
    controleur = _make_agent(company, "+22675000012", Role.RoleName.CONTROLEUR)
    for index in range(55):
        ScanLog.objects.create(
            agent=controleur,
            ticket_number=f"BF2026{index:06d}",
            result=ScanResult.VALID,
        )
    api_client.force_authenticate(user=controleur)

    response = api_client.get(f"{SCAN_HISTORY_URL}?page_size=100")

    assert response.data["count"] == 50


@pytest.mark.django_db
def test_history_only_shows_own_scans(api_client):
    company = CompanyFactory()
    mine = _make_agent(company, "+22675000013", Role.RoleName.CONTROLEUR)
    other = _make_agent(company, "+22675000014", Role.RoleName.CONTROLEUR)
    ScanLog.objects.create(agent=other, ticket_number="BF2026000001", result=ScanResult.VALID)
    api_client.force_authenticate(user=mine)

    response = api_client.get(SCAN_HISTORY_URL)

    assert response.data["count"] == 0


@pytest.mark.django_db
def test_voyageur_cannot_read_scan_history(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22675000015")
    api_client.force_authenticate(user=voyageur)

    assert api_client.get(SCAN_HISTORY_URL).status_code == 403


@pytest.mark.django_db
def test_scan_history_requires_authentication(api_client):
    assert api_client.get(SCAN_HISTORY_URL).status_code == 401
