from datetime import timedelta

import pytest
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.parcels.models import NotificationMethod, ParcelNotification, ParcelStatus
from apps.parcels.tests.factories import ParcelFactory
from apps.users.models import Role
from apps.users.tests.factories import UserFactory

from .factories import make_company_trip, make_guichet_agent


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.bookings.services.send_sms", lambda *a, **k: None)
    monkeypatch.setattr("apps.parcels.services.send_sms", lambda *a, **k: None)


def _booking_payload(trip, ticket_number, seat_number=""):
    return {
        "ticket_number": ticket_number,
        "trip_id": trip.id,
        "first_name": "Aminata",
        "last_name": "TRAORE",
        "phone": "+22670000001",
        "seat_number": seat_number,
        "amount": str(trip.price),
        "payment_method": "cash",
        "offline_created_at": timezone.now().isoformat(),
    }


@pytest.mark.django_db
def test_agent_sync_returns_synced_counts(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_booking_payload(trip, "BF2026000001")]},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    assert response.data["conflicts"] == []
    assert response.data["errors"] == []
    assert Booking.objects.filter(ticket_number="BF2026000001").exists()


@pytest.mark.django_db
def test_agent_sync_reports_seat_conflict(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    BookingFactory(trip=trip, seat_number="1", status=BookingStatus.PAID)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_booking_payload(trip, "BF2026000010", seat_number="1")]},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    assert len(response.data["conflicts"]) == 1
    conflict = response.data["conflicts"][0]
    assert conflict["original_seat"] == "1"
    assert conflict["assigned_seat"] != "1"
    assert "Nouveau siege attribue" in conflict["message"]


@pytest.mark.django_db
def test_agent_sync_bookings_processed_in_offline_created_at_order(api_client):
    # Envoyees dans l'ordre inverse de la saisie reelle : la sync doit malgre
    # tout traiter la plus ancienne en premier (premier enregistre, premier
    # servi), pas l'ordre d'arrivee dans le lot (cf. requetes agent module §4).
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)

    now = timezone.now()
    earlier = _booking_payload(trip, "BF2026000021")
    earlier["offline_created_at"] = (now - timedelta(minutes=5)).isoformat()
    later = _booking_payload(trip, "BF2026000022")
    later["offline_created_at"] = now.isoformat()

    response = api_client.post(
        "/api/v1/agent/sync/", {"bookings": [later, earlier]}, format="json"
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 2
    earlier_seat = int(Booking.objects.get(ticket_number="BF2026000021").seat_number)
    later_seat = int(Booking.objects.get(ticket_number="BF2026000022").seat_number)
    assert earlier_seat < later_seat


@pytest.mark.django_db
def test_voyageur_cannot_sync(api_client):
    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    voyageur = UserFactory(role=role, phone="+22670001234")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post("/api/v1/agent/sync/", {}, format="json")

    assert response.status_code == 403


@pytest.mark.django_db
def test_agent_without_profile_gets_404(api_client):
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = UserFactory(role=role, phone="+22670005678")
    api_client.force_authenticate(user=agent)

    response = api_client.post("/api/v1/agent/sync/", {}, format="json")

    assert response.status_code == 404


@pytest.mark.django_db
def test_agent_lists_sync_logs(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)
    api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_booking_payload(trip, "BF2026000001")]},
        format="json",
    )

    response = api_client.get("/api/v1/agent/sync/logs/")

    assert response.status_code == 200
    assert response.data["results"][0]["bookings_synced"] == 1


@pytest.mark.django_db
def test_agent_lists_last_conflicts(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    BookingFactory(trip=trip, seat_number="1", status=BookingStatus.PAID)
    api_client.force_authenticate(user=agent)
    api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_booking_payload(trip, "BF2026000010", seat_number="1")]},
        format="json",
    )

    response = api_client.get("/api/v1/agent/sync/conflicts/")

    assert response.status_code == 200
    assert len(response.data) == 1
    assert response.data[0]["conflict_type"] == "seat_conflict"


@pytest.mark.django_db
def test_agent_offline_data(api_client):
    trip = make_company_trip(
        total_seats=10,
        departure_time=timezone.now(),
        driver_name="Salif Traore",
        driver_phone="+22670001122",
    )
    company = trip.route.company
    agent = make_guichet_agent(company)
    BookingFactory(trip=trip, status=BookingStatus.PAID)
    ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/agent/offline-data/")

    assert response.status_code == 200
    assert len(response.data["trips"]) == 1
    assert response.data["trips"][0]["driver_name"] == "Salif Traore"
    assert response.data["trips"][0]["driver_phone"] == "+22670001122"
    assert response.data["trips"][0]["total_seats"] == 10
    assert (
        parse_datetime(response.data["trips"][0]["registration_closes_at"])
        == trip.departure_time
    )
    assert len(response.data["bookings"]) == 1
    assert response.data["bookings"][0]["id"] == Booking.objects.get().id
    assert len(response.data["parcel_arrivals"]) == 1


# --------------------------------------------------------------------------- #
# Vente Mobile Money hors ligne (transaction_ref)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_agent_sync_offline_mobile_money_booking_with_ref(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)
    booking = _booking_payload(trip, "BF2026000010")
    booking["payment_method"] = "orange_money"
    booking["transaction_ref"] = "OM-2026-778899"

    response = api_client.post(
        "/api/v1/agent/sync/", {"bookings": [booking]}, format="json"
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    assert Booking.objects.filter(ticket_number="BF2026000010").exists()


@pytest.mark.django_db
def test_agent_sync_offline_mobile_money_booking_requires_ref(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)
    booking = _booking_payload(trip, "BF2026000011")
    booking["payment_method"] = "orange_money"  # pas de transaction_ref

    response = api_client.post(
        "/api/v1/agent/sync/", {"bookings": [booking]}, format="json"
    )

    assert response.status_code == 400
    assert not Booking.objects.filter(ticket_number="BF2026000011").exists()


@pytest.mark.django_db
def test_agent_sync_offline_booking_with_baggage(api_client):
    # Meme famille de manque que transaction_ref hors ligne (point 6 de la
    # demande) : un bagage saisi hors ligne doit etre transmis via le sync.
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)
    booking = _booking_payload(trip, "BF2026000012")
    booking["baggage"] = [
        {"label": "Valise rigide", "weight_kg": "18.0"},
        {"label": "Sac a dos", "weight_kg": "5.5", "location": "cabin"},
    ]

    response = api_client.post(
        "/api/v1/agent/sync/", {"bookings": [booking]}, format="json"
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    created = Booking.objects.get(ticket_number="BF2026000012")
    assert created.baggage.count() == 2
    assert created.baggage.first().is_offline is True


# --------------------------------------------------------------------------- #
# Notification colis « marquer prevenu » hors ligne
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_agent_sync_offline_parcel_notification(api_client):
    company = make_company_trip(total_seats=10).route.company
    agent = make_guichet_agent(company)
    parcel = ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {
            "parcel_notifications": [
                {
                    "tracking_number": parcel.tracking_number,
                    "method": "call",
                    "offline_created_at": timezone.now().isoformat(),
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["parcel_notifications"] == 1
    parcel.refresh_from_db()
    assert parcel.status == ParcelStatus.NOTIFIED
    notification = ParcelNotification.objects.get(parcel=parcel)
    assert notification.method == NotificationMethod.CALL
    assert notification.is_offline is True
    assert notification.synced_at is not None


@pytest.mark.django_db
def test_agent_sync_parcel_notification_is_idempotent(api_client):
    company = make_company_trip(total_seats=10).route.company
    agent = make_guichet_agent(company)
    parcel = ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
    api_client.force_authenticate(user=agent)
    stamp = timezone.now().isoformat()
    payload = {
        "parcel_notifications": [
            {"tracking_number": parcel.tracking_number, "offline_created_at": stamp}
        ]
    }

    first = api_client.post("/api/v1/agent/sync/", payload, format="json")
    second = api_client.post("/api/v1/agent/sync/", payload, format="json")

    assert first.data["synced"]["parcel_notifications"] == 1
    # Re-sync du meme appel (meme colis + meme horodatage) : aucun doublon.
    assert second.data["synced"]["parcel_notifications"] == 0
    assert ParcelNotification.objects.filter(parcel=parcel).count() == 1


@pytest.mark.django_db
def test_agent_sync_parcel_notification_unknown_tracking_is_error(api_client):
    company = make_company_trip(total_seats=10).route.company
    agent = make_guichet_agent(company)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {
            "parcel_notifications": [
                {
                    "tracking_number": "COL2026999999",
                    "offline_created_at": timezone.now().isoformat(),
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["parcel_notifications"] == 0
    assert len(response.data["errors"]) == 1
    assert response.data["errors"][0]["reference"] == "COL2026999999"


# --------------------------------------------------------------------------- #
# Annulation d'un billet deja synchronise, hors ligne
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_agent_sync_cancels_already_synced_booking(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    booking = BookingFactory(trip=trip, status=BookingStatus.PAID)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {
            "cancellations": [
                {
                    "ticket_number": booking.ticket_number,
                    "reason": "Client absent",
                    "offline_created_at": timezone.now().isoformat(),
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["cancellations"] == 1
    booking.refresh_from_db()
    assert booking.status == BookingStatus.CANCELLED


@pytest.mark.django_db
def test_agent_sync_cancellation_is_idempotent(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    booking = BookingFactory(trip=trip, status=BookingStatus.CANCELLED)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {
            "cancellations": [
                {
                    "ticket_number": booking.ticket_number,
                    "offline_created_at": timezone.now().isoformat(),
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["cancellations"] == 0


@pytest.mark.django_db
def test_agent_sync_cancellation_unknown_ticket_is_error(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {
            "cancellations": [
                {
                    "ticket_number": "BF2026999999",
                    "offline_created_at": timezone.now().isoformat(),
                }
            ]
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["cancellations"] == 0
    assert len(response.data["errors"]) == 1
    assert response.data["errors"][0]["reference"] == "BF2026999999"
