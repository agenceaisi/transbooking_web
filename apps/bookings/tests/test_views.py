from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import (
    BaggageLocation,
    BoardingValidation,
    Booking,
    BookingStatus,
)
from apps.routes.tests.factories import RouteFactory
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.tests.factories import VehicleFactory

from .factories import BaggageFactory, BookingFactory


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


def _trip_for_company(company, **kwargs):
    route = RouteFactory(company=company)
    vehicle = VehicleFactory(company=company, total_seats=kwargs.pop("total_seats", 30))
    return TripFactory(route=route, vehicle=vehicle, **kwargs)


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_voyageur_creates_booking(api_client):
    trip = TripFactory(available_seats=30)
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001000")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/bookings/", {"trip": trip.id}, format="json"
    )

    assert response.status_code == 201
    assert response.data["status"] == BookingStatus.PENDING
    assert response.data["ticket_number"].startswith("BF")
    booking = Booking.objects.get(ticket_number=response.data["ticket_number"])
    assert booking.user == voyageur


@pytest.mark.django_db
def test_voyageur_only_sees_own_bookings(api_client):
    mine = BookingFactory()
    BookingFactory()  # autre voyageur
    api_client.force_authenticate(user=mine.user)
    # mine.user n'a pas de role voyageur (UserFactory en met un par defaut).
    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    mine.user.role = role
    mine.user.save(update_fields=["role"])

    response = api_client.get("/api/v1/bookings/")

    assert response.status_code == 200
    ids = [b["id"] for b in response.data["results"]]
    assert ids == [mine.id]


@pytest.mark.django_db
def test_voyageur_booking_detail_exposes_company_on_trip(api_client):
    # En-tete compagnie du billet (maquette "Mon billet").
    booking = BookingFactory()
    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    booking.user.role = role
    booking.user.save(update_fields=["role"])
    api_client.force_authenticate(user=booking.user)

    response = api_client.get(f"/api/v1/bookings/{booking.id}/")

    assert response.status_code == 200
    company = booking.trip.route.company
    assert response.data["trip"]["company_name"] == company.name
    assert response.data["trip"]["company_sigle"] == company.sigle


@pytest.mark.django_db
def test_voyageur_booking_detail_lists_baggage(api_client):
    # Ecran « Bagages » : bagages enregistres + poids total.
    booking = BookingFactory()
    BaggageFactory(booking=booking, label="Valise", weight_kg=Decimal("12.0"))
    BaggageFactory(
        booking=booking,
        label="Sac a dos",
        weight_kg=Decimal("8.5"),
        location=BaggageLocation.CABIN,
    )
    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    booking.user.role = role
    booking.user.save(update_fields=["role"])
    api_client.force_authenticate(user=booking.user)

    response = api_client.get(f"/api/v1/bookings/{booking.id}/")

    assert response.status_code == 200
    bags = response.data["baggage"]
    assert {b["label"] for b in bags} == {"Valise", "Sac a dos"}
    assert all(b["tag"].startswith("TB-B-") for b in bags)
    assert response.data["baggage_total_weight_kg"] == "20.5"


@pytest.mark.django_db
def test_voyageur_cancels_booking_restores_seat(api_client):
    trip = TripFactory(
        available_seats=29, departure_time=timezone.now() + timedelta(days=2)
    )
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001001")
    booking = BookingFactory(trip=trip, user=voyageur, status=BookingStatus.PAID)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(f"/api/v1/bookings/{booking.id}/cancel/")

    assert response.status_code == 200
    booking.refresh_from_db()
    trip.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert trip.available_seats == 30


@pytest.mark.django_db
def test_voyageur_cancel_too_late_returns_409(api_client):
    trip = TripFactory(departure_time=timezone.now() + timedelta(minutes=30))
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001002")
    booking = BookingFactory(trip=trip, user=voyageur)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(f"/api/v1/bookings/{booking.id}/cancel/")

    assert response.status_code == 409


@pytest.mark.django_db
def test_voyageur_downloads_ticket_pdf(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001003")
    booking = BookingFactory(user=voyageur)
    api_client.force_authenticate(user=voyageur)

    response = api_client.get(f"/api/v1/bookings/{booking.id}/ticket/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


# --------------------------------------------------------------------------- #
# Agent guichet
# --------------------------------------------------------------------------- #
def _agent(api_client, company, phone, agent_type):
    agent = _make_user(
        Role.RoleName.AGENT_GUICHET
        if agent_type == AgentProfile.AgentType.GUICHET
        else Role.RoleName.CONTROLEUR,
        phone,
    )
    AgentProfile.objects.create(
        user=agent, company=company, agent_type=agent_type
    )
    api_client.force_authenticate(user=agent)
    return agent


@pytest.mark.django_db
def test_agent_creates_offline_booking(api_client):
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002000",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Aminata",
            "last_name": "TRAORE",
            "phone": "+22670000123",
            "payment_method": "cash",
            "is_offline": True,
            "offline_created_at": timezone.now().isoformat(),
        },
        format="json",
    )

    assert response.status_code == 201
    booking = Booking.objects.get(ticket_number=response.data["ticket_number"])
    assert booking.is_offline is True
    assert booking.synced_at is None
    assert booking.status == BookingStatus.PAID
    assert booking.agent is not None


@pytest.mark.django_db
def test_agent_creates_booking_with_null_optional_fields(api_client):
    # Le client Flutter serialise ses DTO avec `null` explicite pour un champ
    # facultatif non renseigne (seat_number, transaction_ref, baggage...)
    # plutot que de l'omettre : ces valeurs ne doivent pas etre rejetees
    # (regression #184).
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002050",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Aminata",
            "last_name": "TRAORE",
            "phone": "+22670000123",
            "payment_method": "cash",
            "seat_number": None,
            "amount": None,
            "transaction_ref": None,
            "ticket_number": None,
            "is_offline": None,
            "baggage": None,
            "gender": None,
            "id_type": None,
            "id_number": None,
            "discount_code": None,
        },
        format="json",
    )

    assert response.status_code == 201
    booking = Booking.objects.get(ticket_number=response.data["ticket_number"])
    assert booking.is_offline is False
    assert booking.baggage.count() == 0
    assert booking.gender == ""
    assert booking.id_type == "none"


@pytest.mark.django_db
def test_agent_registers_booking_with_gender_and_id(api_client):
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002200",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Fatimata",
            "last_name": "SAWADOGO",
            "phone": "+22670000789",
            "payment_method": "cash",
            "gender": "F",
            "id_type": "cnib",
            "id_number": "B12345678",
            "discount_code": "PROMO10",
        },
        format="json",
    )

    assert response.status_code == 201
    booking = Booking.objects.get(ticket_number=response.data["ticket_number"])
    assert booking.gender == "F"
    assert booking.id_type == "cnib"
    assert booking.id_number == "B12345678"
    assert booking.discount_code == "PROMO10"
    # Donnee sensible : jamais renvoyee dans la reponse serialisee.
    assert "id_number" not in response.data


@pytest.mark.django_db
def test_agent_booking_id_number_required_when_id_type_set(api_client):
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002201",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Fatimata",
            "last_name": "SAWADOGO",
            "phone": "+22670000789",
            "payment_method": "cash",
            "id_type": "cnib",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "id_number" in response.data


@pytest.mark.django_db
def test_agent_registers_booking_with_baggage(api_client):
    # Le guichet pese et etiquette les bagages a l'enregistrement.
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002100",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Ali",
            "last_name": "OUEDRAOGO",
            "phone": "+22670000456",
            "payment_method": "cash",
            "baggage": [
                {"label": "Valise rigide", "weight_kg": "18.0"},
                {"label": "Sac a dos", "weight_kg": "5.5", "location": "cabin"},
            ],
        },
        format="json",
    )

    assert response.status_code == 201
    bags = response.data["baggage"]
    assert len(bags) == 2
    assert all(b["tag"].startswith("TB-B-") for b in bags)
    assert response.data["baggage_total_weight_kg"] == "23.5"
    booking = Booking.objects.get(ticket_number=response.data["ticket_number"])
    assert booking.baggage.count() == 2


@pytest.mark.django_db
def test_agent_mobile_money_requires_transaction_ref(api_client):
    trip = TripFactory(available_seats=30)
    _agent(
        api_client,
        trip.route.company,
        "+22670002001",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "Aminata",
            "last_name": "TRAORE",
            "phone": "+22670000123",
            "payment_method": "orange_money",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "transaction_ref" in response.data


@pytest.mark.django_db
def test_agent_looks_up_booking_by_ticket_number(api_client):
    booking = BookingFactory()
    _agent(
        api_client,
        booking.trip.route.company,
        "+22670002002",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.get(f"/api/v1/agent/bookings/{booking.ticket_number}/")

    assert response.status_code == 200
    assert response.data["ticket_number"] == booking.ticket_number


# --------------------------------------------------------------------------- #
# Controleur — scan & embarquement
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_controleur_scan_invalid_ticket_returns_404(api_client):
    company = VehicleFactory().company
    _agent(api_client, company, "+22670003000", AgentProfile.AgentType.CONTROLEUR)

    response = api_client.post(
        "/api/v1/agent/scan/", {"qr_data": "BF2026000000"}, format="json"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_controleur_scan_valid_ticket_returns_green(api_client):
    booking = BookingFactory(status=BookingStatus.PAID)
    _agent(
        api_client,
        booking.trip.route.company,
        "+22670003001",
        AgentProfile.AgentType.CONTROLEUR,
    )

    response = api_client.post(
        "/api/v1/agent/scan/", {"qr_data": booking.ticket_number}, format="json"
    )

    assert response.status_code == 200
    assert response.data["color"] == "green"
    trip = response.data["booking"]["trip"]
    assert trip["id"] == booking.trip_id
    assert trip["origin_city"] == booking.trip.route.origin_city.name
    assert trip["destination_city"] == booking.trip.route.destination_city.name


@pytest.mark.django_db
def test_controleur_manual_check_in(api_client):
    booking = BookingFactory(status=BookingStatus.PAID)
    _agent(
        api_client,
        booking.trip.route.company,
        "+22670003002",
        AgentProfile.AgentType.CONTROLEUR,
    )

    response = api_client.post(
        f"/api/v1/agent/trips/{booking.trip_id}/boarding/{booking.id}/"
    )

    assert response.status_code == 201
    assert BoardingValidation.objects.filter(booking=booking).exists()


@pytest.mark.django_db
def test_controleur_bulk_check_in_requires_confirm(api_client):
    trip = TripFactory()
    BookingFactory(trip=trip, status=BookingStatus.PAID, seat_number="1")
    _agent(
        api_client,
        trip.route.company,
        "+22670003003",
        AgentProfile.AgentType.CONTROLEUR,
    )

    no_confirm = api_client.post(f"/api/v1/agent/trips/{trip.id}/boarding/all/")
    assert no_confirm.status_code == 400

    confirmed = api_client.post(
        f"/api/v1/agent/trips/{trip.id}/boarding/all/",
        {"confirm": True},
        format="json",
    )
    assert confirmed.status_code == 200
    assert confirmed.data["boarded"] == 1


@pytest.mark.django_db
def test_boarding_validate_returns_summary_shape(api_client):
    trip = TripFactory()
    paid = BookingFactory(trip=trip, status=BookingStatus.PAID, seat_number="1")
    BookingFactory(trip=trip, status=BookingStatus.PENDING, seat_number="2")
    controleur = _agent(
        api_client,
        trip.route.company,
        "+22670003004",
        AgentProfile.AgentType.CONTROLEUR,
    )
    api_client.post(f"/api/v1/agent/trips/{trip.id}/boarding/{paid.id}/")

    response = api_client.post(f"/api/v1/agent/trips/{trip.id}/boarding/validate/")

    assert response.status_code == 200
    assert response.data == {
        "trip": trip.id,
        "total_paid": 1,
        "boarded": 1,
        "not_boarded": 0,
        "locked": True,
    }


# --------------------------------------------------------------------------- #
# Agent guichet — annulation au guichet
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_cancels_booking_at_counter(api_client):
    booking = _booking_for_company_helper()
    agent = _agent(
        api_client,
        booking.trip.route.company,
        "+22670003010",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        f"/api/v1/agent/bookings/{booking.ticket_number}/cancel/",
        {"reason": "Client absent"},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == BookingStatus.CANCELLED
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED
    assert booking.cancelled_by == agent


@pytest.mark.django_db
def test_agent_cancels_booking_close_to_departure(api_client):
    # Contrairement au voyageur, l'agent n'est pas soumis au delai de 2h.
    trip = _trip_for_company(
        VehicleFactory().company,
        departure_time=timezone.now() + timedelta(minutes=10),
    )
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    _agent(
        api_client,
        booking.trip.route.company,
        "+22670003011",
        AgentProfile.AgentType.GUICHET,
    )

    response = api_client.post(
        f"/api/v1/agent/bookings/{booking.ticket_number}/cancel/"
    )

    assert response.status_code == 200


@pytest.mark.django_db
def test_agent_cannot_cancel_booking_of_another_company(api_client):
    mine = VehicleFactory().company
    other = _booking_for_company_helper()
    _agent(api_client, mine, "+22670003012", AgentProfile.AgentType.GUICHET)

    response = api_client.post(
        f"/api/v1/agent/bookings/{other.ticket_number}/cancel/"
    )

    assert response.status_code == 404


@pytest.mark.django_db
def test_agent_cannot_cancel_already_boarded_booking(api_client):
    booking = _booking_for_company_helper()
    agent = _agent(
        api_client,
        booking.trip.route.company,
        "+22670003013",
        AgentProfile.AgentType.GUICHET,
    )
    BoardingValidation.objects.create(
        booking=booking, validated_by=agent, boarded_at=timezone.now()
    )

    response = api_client.post(
        f"/api/v1/agent/bookings/{booking.ticket_number}/cancel/"
    )

    assert response.status_code == 409


@pytest.mark.django_db
def test_voyageur_cannot_use_agent_cancel_endpoint(api_client):
    booking = _booking_for_company_helper()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003014")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        f"/api/v1/agent/bookings/{booking.ticket_number}/cancel/"
    )

    assert response.status_code == 403


def _booking_for_company_helper():
    trip = _trip_for_company(VehicleFactory().company)
    return BookingFactory(trip=trip, status=BookingStatus.PAID)


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_admin_only_sees_own_bookings(api_client):
    own_trip = _trip_for_company(VehicleFactory().company)
    mine = BookingFactory(trip=own_trip)
    BookingFactory()  # autre compagnie

    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670004000")
    company = own_trip.route.company
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/bookings/")

    assert response.status_code == 200
    ids = [b["id"] for b in response.data["results"]]
    assert ids == [mine.id]


@pytest.mark.django_db
def test_company_admin_exports_bookings_pdf(api_client):
    own_trip = _trip_for_company(VehicleFactory().company)
    BookingFactory(trip=own_trip)
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670004001")
    company = own_trip.route.company
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/bookings/export/?format=pdf")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_voyageur_cannot_access_agent_endpoint(api_client):
    trip = TripFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670005000")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/agent/bookings/",
        {
            "trip": trip.id,
            "first_name": "X",
            "last_name": "Y",
            "phone": "+22670000111",
            "payment_method": "cash",
        },
        format="json",
    )

    assert response.status_code == 403
