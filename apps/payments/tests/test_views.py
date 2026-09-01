import pytest
from rest_framework.test import APIClient

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.payments.models import PaymentMethod, PaymentStatus
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.tests.factories import VehicleFactory

from .factories import PaymentFactory


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.payments.services.send_sms", lambda *a, **k: None)


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


@pytest.mark.django_db
def test_voyageur_initiates_mobile_payment_requires_otp(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002000")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/payments/",
        {
            "booking_id": booking.id,
            "method": PaymentMethod.ORANGE_MONEY,
            "phone": "+22670000001",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PaymentStatus.OTP_REQUIRED


@pytest.mark.django_db
def test_voyageur_initiates_cash_payment_stays_pending(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002006")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.CASH},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PaymentStatus.PENDING


@pytest.mark.django_db
def test_voyageur_verifies_payment(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002001")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    payment = PaymentFactory(booking=booking, method=PaymentMethod.CASH)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        f"/api/v1/payments/{payment.id}/verify/", {}, format="json"
    )

    assert response.status_code == 200
    assert response.data["status"] == PaymentStatus.PAID
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PAID


@pytest.mark.django_db
def test_voyageur_cannot_see_other_payment(api_client):
    other_payment = PaymentFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002002")
    api_client.force_authenticate(user=voyageur)

    response = api_client.get(f"/api/v1/payments/{other_payment.id}/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_voyageur_lists_only_own_payments(api_client):
    # Sous-onglet "Paiements" du profil : liste paginee des paiements du voyageur.
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002007")
    mine = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    my_payment = PaymentFactory(booking=mine, method=PaymentMethod.CASH)
    PaymentFactory()  # paiement d'un autre voyageur
    api_client.force_authenticate(user=voyageur)

    response = api_client.get("/api/v1/payments/")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    assert [p["id"] for p in results] == [my_payment.id]


@pytest.mark.django_db
def test_receipt_returns_pdf(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002003")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    payment = PaymentFactory(booking=booking, method=PaymentMethod.CASH)
    api_client.force_authenticate(user=voyageur)
    api_client.post(f"/api/v1/payments/{payment.id}/verify/", {}, format="json")

    response = api_client.get(f"/api/v1/payments/{payment.id}/receipt/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content[:4] == b"%PDF"


@pytest.mark.django_db
def test_agent_payment_records_and_confirms(api_client):
    vehicle = VehicleFactory()
    company = vehicle.company
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670002004")
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    from apps.routes.tests.factories import RouteFactory
    from apps.trips.tests.factories import TripFactory

    trip = TripFactory(route=RouteFactory(company=company), vehicle=vehicle)
    booking = BookingFactory(trip=trip, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/payments/",
        {
            "booking_id": booking.id,
            "method": PaymentMethod.CASH,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PaymentStatus.PAID
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PAID


@pytest.mark.django_db
def test_agent_payment_rejects_other_company_booking(api_client):
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670002005")
    AgentProfile.objects.create(
        user=agent,
        company=VehicleFactory().company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    other_booking = BookingFactory(status=BookingStatus.PENDING)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/payments/",
        {"booking_id": other_booking.id, "method": PaymentMethod.CASH},
        format="json",
    )

    assert response.status_code == 404
