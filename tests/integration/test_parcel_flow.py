"""Tests d'integration du parcours colis (enregistrement et notification).

Couvre :
1. L'agent enregistre un colis -> tarif calcule -> SMS au destinataire.
2. Un colis arrive -> l'agent notifie le destinataire -> statut = notifie.
"""
import pytest

from apps.parcels.models import Parcel, ParcelNotification, ParcelStatus
from apps.parcels.tests.factories import ParcelFactory
from tests.factories import (
    CompanyFactory,
    RouteFactory,
    StationFactory,
    make_guichet_agent,
)


# --------------------------------------------------------------------------- #
# 1. Enregistrement -> tarif -> SMS destinataire
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_registers_parcel_prices_and_texts_recipient(api_client, sms_outbox):
    # Tranche moyenne (100 < distance <= 300 km) : 200 FCFA/kg + 750 fixes.
    route = RouteFactory(distance_km=250)
    station = StationFactory(company=route.company, city=route.origin_city)
    agent = make_guichet_agent(route.company, station=station)
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
    tracking_number = response.data["tracking_number"]
    assert tracking_number.startswith("COL")
    assert response.data["tariff"] == "1350.00"  # 3 * 200 + 750

    parcel = Parcel.objects.get(tracking_number=tracking_number)
    assert parcel.company == route.company
    assert parcel.status == ParcelStatus.REGISTERED
    # Le destinataire recoit un SMS d'enregistrement (envoi asynchrone eager).
    assert sms_outbox.sent_to("+22660000001")


# --------------------------------------------------------------------------- #
# 2. Colis arrive -> notification -> statut notifie
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_arrived_parcel_notifies_recipient(api_client, sms_outbox):
    company = CompanyFactory()
    station = StationFactory(company=company)
    agent = make_guichet_agent(company, station=station)
    api_client.force_authenticate(user=agent)
    parcel = ParcelFactory(
        company=company,
        destination_station=station,
        status=ParcelStatus.ARRIVED,
        recipient_phone="+22660000002",
    )

    response = api_client.post(
        f"/api/v1/agent/parcels/{parcel.id}/notify/", {}, format="json"
    )

    assert response.status_code == 200
    assert response.data["status"] == ParcelStatus.NOTIFIED

    parcel.refresh_from_db()
    assert parcel.status == ParcelStatus.NOTIFIED
    assert ParcelNotification.objects.filter(parcel=parcel, method="sms").count() == 1
    assert sms_outbox.sent_to("+22660000002")

    # Regle metier : un second SMS d'arrivee est bloque (anti-doublon).
    duplicate = api_client.post(
        f"/api/v1/agent/parcels/{parcel.id}/notify/", {}, format="json"
    )
    assert duplicate.status_code == 400
