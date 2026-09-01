"""Tests du flux de paiement Mobile Money par OTP (cf. PROMPT_SUP partie B)."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.payments.models import PaymentMethod, PaymentOtp, PaymentStatus
from apps.payments.services import hash_otp_code
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.tests.factories import VehicleFactory

SANDBOX_OTP = "123456"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _sandbox(settings):
    """Force le fournisseur sandbox avec un OTP de test connu."""
    settings.PAYMENT_SANDBOX = True
    settings.PAYMENT_SANDBOX_OTP = SANDBOX_OTP
    settings.PAYMENT_SANDBOX_FORCE_FAILURE = False
    return settings


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.payments.services.send_sms", lambda *a, **k: None)


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


def _start_payment(api_client, voyageur, method=PaymentMethod.ORANGE_MONEY):
    """Initie un paiement Mobile Money et renvoie (payment_id, booking)."""
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)
    response = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": method, "phone": "+22670000001"},
        format="json",
    )
    assert response.status_code == 201, response.data
    return response.data["id"], booking


# --------------------------------------------------------------------------- #
# Initiation
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_initiate_returns_otp_required_with_masked_phone(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003000")
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
    # Numero masque : jamais le numero complet dans la reponse.
    assert response.data["phone"] == "****0001"
    assert response.data["otp_expires_at"] is not None
    assert response.data["otp_attempts_remaining"] == 3


@pytest.mark.django_db
def test_initiate_mobile_payment_requires_phone(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003001")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.ORANGE_MONEY},
        format="json",
    )

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_initiate_rejects_card(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003002")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.CARD},
        format="json",
    )

    assert response.status_code == 400
    assert "method" in response.data


@pytest.mark.django_db
def test_otp_code_is_never_stored_in_clear(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003003")
    payment_id, _ = _start_payment(api_client, voyageur)

    otp = PaymentOtp.objects.get(payment_id=payment_id)
    assert otp.code_hash != SANDBOX_OTP
    assert otp.code_hash == hash_otp_code(SANDBOX_OTP)


# --------------------------------------------------------------------------- #
# Verification du code
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_valid_otp_marks_payment_paid(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003010")
    payment_id, booking = _start_payment(api_client, voyageur)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["status"] == PaymentStatus.PAID
    # Reference operateur conservee pour la reconciliation, mais masquee.
    assert response.data["transaction_ref"].startswith("****")
    assert response.data["receipt_url"]
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PAID


@pytest.mark.django_db
def test_wrong_otp_decrements_attempts(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003011")
    payment_id, _ = _start_payment(api_client, voyageur)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": "999999"},
        format="json",
    )

    assert response.status_code == 400
    assert response.data["attempts_remaining"] == 2
    otp = PaymentOtp.objects.get(payment_id=payment_id)
    assert otp.attempts == 1
    # Le paiement reste ouvert tant qu'il reste des tentatives.
    assert otp.payment.status == PaymentStatus.OTP_REQUIRED


@pytest.mark.django_db
def test_expired_otp_fails_payment(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003012")
    payment_id, _ = _start_payment(api_client, voyageur)

    PaymentOtp.objects.filter(payment_id=payment_id).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )

    assert response.status_code == 400
    otp = PaymentOtp.objects.get(payment_id=payment_id)
    assert otp.payment.status == PaymentStatus.FAILED


@pytest.mark.django_db
def test_max_attempts_fails_payment(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003013")
    payment_id, booking = _start_payment(api_client, voyageur)

    for _ in range(3):
        response = api_client.post(
            f"/api/v1/payments/{payment_id}/verify-otp/",
            {"otp": "999999"},
            format="json",
        )
        assert response.status_code == 400

    otp = PaymentOtp.objects.get(payment_id=payment_id)
    assert otp.attempts == 3
    assert otp.payment.status == PaymentStatus.FAILED
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING

    # Le bon code n'y change plus rien une fois le paiement en echec.
    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )
    assert response.status_code == 400


@pytest.mark.django_db
def test_provider_failure_marks_payment_failed(api_client, _sandbox):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003014")
    payment_id, booking = _start_payment(api_client, voyageur)

    # Refus de l'operateur alors que le code saisi est correct.
    _sandbox.PAYMENT_SANDBOX_FORCE_FAILURE = True

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )

    assert response.status_code == 400
    otp = PaymentOtp.objects.get(payment_id=payment_id)
    assert otp.payment.status == PaymentStatus.FAILED
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_verify_otp_rejects_non_numeric_code(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003015")
    payment_id, _ = _start_payment(api_client, voyageur)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/", {"otp": "abcdef"}, format="json"
    )

    assert response.status_code == 400
    assert "otp" in response.data


@pytest.mark.django_db
def test_manual_verify_rejected_for_mobile_money(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003016")
    payment_id, _ = _start_payment(api_client, voyageur)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify/",
        {"transaction_ref": "OM240630ABCD"},
        format="json",
    )

    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Renvoi du code
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_resend_otp_is_rate_limited(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003020")
    payment_id, _ = _start_payment(api_client, voyageur)

    response = api_client.post(f"/api/v1/payments/{payment_id}/resend-otp/", {})

    assert response.status_code == 429
    assert PaymentOtp.objects.filter(payment_id=payment_id).count() == 1


@pytest.mark.django_db
def test_resend_otp_issues_new_code_after_interval(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003021")
    payment_id, _ = _start_payment(api_client, voyageur)

    # On vieillit le code precedent au-dela du delai de renvoi.
    PaymentOtp.objects.filter(payment_id=payment_id).update(
        created_at=timezone.now() - timedelta(seconds=120)
    )

    response = api_client.post(f"/api/v1/payments/{payment_id}/resend-otp/", {})

    assert response.status_code == 200
    assert response.data["status"] == PaymentStatus.OTP_REQUIRED
    assert PaymentOtp.objects.filter(payment_id=payment_id).count() == 2

    # Le dernier code emis confirme bien le paiement.
    confirm = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )
    assert confirm.status_code == 200
    assert confirm.data["status"] == PaymentStatus.PAID


@pytest.mark.django_db
def test_resend_otp_rejected_on_cash_payment(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003022")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)
    created = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.CASH},
        format="json",
    )

    response = api_client.post(
        f"/api/v1/payments/{created.data['id']}/resend-otp/", {}
    )

    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Isolation & permissions
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_other_voyageur_cannot_verify_payment(api_client):
    owner = _make_user(Role.RoleName.VOYAGEUR, "+22670003030")
    payment_id, _ = _start_payment(api_client, owner)

    intruder = _make_user(Role.RoleName.VOYAGEUR, "+22670003031")
    api_client.force_authenticate(user=intruder)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )

    assert response.status_code == 404
    assert PaymentOtp.objects.get(payment_id=payment_id).payment.status == (
        PaymentStatus.OTP_REQUIRED
    )


@pytest.mark.django_db
def test_anonymous_cannot_verify_payment(api_client):
    owner = _make_user(Role.RoleName.VOYAGEUR, "+22670003032")
    payment_id, _ = _start_payment(api_client, owner)
    api_client.force_authenticate(user=None)

    response = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )

    assert response.status_code == 401


# --------------------------------------------------------------------------- #
# Guichet agent
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_mobile_payment_uses_otp_flow(api_client):
    vehicle = VehicleFactory()
    company = vehicle.company
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670003040")
    AgentProfile.objects.create(
        user=agent, company=company, agent_type=AgentProfile.AgentType.GUICHET
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
            "method": PaymentMethod.ORANGE_MONEY,
            "phone": "+22670000009",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == PaymentStatus.OTP_REQUIRED
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING

    # L'agent confirme avec le code communique par le client.
    confirm = api_client.post(
        f"/api/v1/payments/{response.data['id']}/verify-otp/",
        {"otp": SANDBOX_OTP},
        format="json",
    )
    assert confirm.status_code == 200
    assert confirm.data["status"] == PaymentStatus.PAID


@pytest.mark.django_db
def test_voyageur_cannot_use_agent_payment_endpoint(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670003041")
    booking = BookingFactory(user=voyageur, status=BookingStatus.PENDING)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/agent/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.CASH},
        format="json",
    )

    assert response.status_code == 403
