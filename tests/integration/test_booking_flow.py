"""Tests d'integration du parcours de reservation (voyageur et agent).

Couvre trois flux de bout en bout :
1. Recherche publique -> reservation voyageur -> paiement confirme -> billet PDF.
2. Reservation hors ligne d'un agent -> sync -> aucun conflit.
3. Reservation hors ligne d'un agent -> sync -> conflit de siege resolu.
"""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.payments.models import PaymentMethod, PaymentStatus
from tests.factories import make_company_trip, make_guichet_agent, make_voyageur


def _offline_booking_payload(trip, ticket_number, seat_number=""):
    """Build the offline booking dict an agent app would POST to /agent/sync/."""
    return {
        "ticket_number": ticket_number,
        "trip_id": trip.id,
        "first_name": "Aminata",
        "last_name": "TRAORE",
        "phone": "+22670000123",
        "seat_number": seat_number,
        "amount": str(trip.price),
        "payment_method": "cash",
        "offline_created_at": timezone.now().isoformat(),
    }


# --------------------------------------------------------------------------- #
# 1. Recherche publique -> reservation -> paiement -> billet
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_public_search_to_paid_ticket(api_client, sms_outbox):
    trip = make_company_trip(
        total_seats=30, departure_time=timezone.now() + timedelta(days=1)
    )
    route = trip.route

    # 1. Le public trouve le voyage via la recherche.
    search = api_client.get(
        "/api/v1/trips/search/",
        {"origin_city": route.origin_city_id, "dest_city": route.destination_city_id},
    )
    assert search.status_code == 200
    assert trip.id in [item["id"] for item in search.data["results"]]

    # 2. Un voyageur authentifie reserve une place.
    voyageur = make_voyageur("+22670010000")
    api_client.force_authenticate(user=voyageur)
    booking_response = api_client.post(
        "/api/v1/bookings/", {"trip": trip.id}, format="json"
    )
    assert booking_response.status_code == 201
    assert booking_response.data["status"] == BookingStatus.PENDING
    ticket_number = booking_response.data["ticket_number"]
    booking = Booking.objects.get(ticket_number=ticket_number)
    assert booking.user == voyageur

    trip.refresh_from_db()
    assert trip.available_seats == 29  # place reservee des la creation

    # 3. Le voyageur paie (Mobile Money : confirmation par code OTP).
    initiate = api_client.post(
        "/api/v1/payments/",
        {"booking_id": booking.id, "method": PaymentMethod.ORANGE_MONEY,
         "phone": voyageur.phone},
        format="json",
    )
    assert initiate.status_code == 201
    assert initiate.data["status"] == PaymentStatus.OTP_REQUIRED
    payment_id = initiate.data["id"]

    verify = api_client.post(
        f"/api/v1/payments/{payment_id}/verify-otp/",
        {"otp": settings.PAYMENT_SANDBOX_OTP},
        format="json",
    )
    assert verify.status_code == 200
    assert verify.data["status"] == PaymentStatus.PAID
    booking.refresh_from_db()
    assert booking.status == BookingStatus.PAID

    # La confirmation part par SMS une fois le paiement valide.
    assert sms_outbox.sent_to(booking.phone)

    # 4. Le voyageur telecharge son billet PDF.
    ticket = api_client.get(f"/api/v1/bookings/{booking.id}/ticket/")
    assert ticket.status_code == 200
    assert ticket["Content-Type"] == "application/pdf"
    assert ticket.content[:4] == b"%PDF"


# --------------------------------------------------------------------------- #
# 2. Reservation hors ligne -> sync sans conflit
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_offline_booking_syncs_without_conflict(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_offline_booking_payload(trip, "BF2026000001", seat_number="4")]},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    assert response.data["conflicts"] == []
    assert response.data["errors"] == []

    booking = Booking.objects.get(ticket_number="BF2026000001")
    assert booking.seat_number == "4"
    assert booking.is_offline is True
    assert booking.synced_at is not None  # marque comme synchronise apres l'upload
    trip.refresh_from_db()
    assert trip.available_seats == 9


# --------------------------------------------------------------------------- #
# 3. Reservation hors ligne -> sync avec conflit de siege resolu
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_offline_booking_sync_resolves_seat_conflict(api_client):
    trip = make_company_trip(total_seats=10)
    agent = make_guichet_agent(trip.route.company)
    # Un autre passager occupe deja le siege 1 (reserve pendant la deconnexion).
    BookingFactory(trip=trip, seat_number="1", status=BookingStatus.PAID)
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/agent/sync/",
        {"bookings": [_offline_booking_payload(trip, "BF2026000010", seat_number="1")]},
        format="json",
    )

    assert response.status_code == 200
    assert response.data["synced"]["bookings"] == 1
    assert len(response.data["conflicts"]) == 1

    conflict = response.data["conflicts"][0]
    assert conflict["original_seat"] == "1"
    assert conflict["assigned_seat"] != "1"
    assert "Nouveau siege attribue" in conflict["message"]

    # La reservation synchronisee porte le nouveau siege, l'ancienne est intacte.
    synced = Booking.objects.get(ticket_number="BF2026000010")
    assert synced.seat_number == conflict["assigned_seat"]
    assert Booking.objects.filter(trip=trip, seat_number="1").count() == 1
