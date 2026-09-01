from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import CityFactory
from apps.parcels.models import NotificationMethod, ParcelNotification, ParcelStatus
from apps.parcels.services import (
    calculate_tariff,
    generate_tracking_number,
    notify_recipient,
    register_parcel,
    update_status,
)
from apps.routes.tests.factories import RouteFactory

from .factories import ParcelFactory


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.parcels.services.send_sms", lambda *a, **k: None)


def _route(distance_km, **overrides):
    """Create a route of a given distance and return (route, company, cities)."""
    return RouteFactory(distance_km=distance_km, **overrides)


@pytest.mark.django_db
def test_calculate_tariff_short_tier():
    # < 100 km : tier_short = 250/kg + 500 fixe.
    route = _route(80)
    tariff = calculate_tariff(
        Decimal("4"), route.origin_city_id, route.destination_city_id, route.company
    )
    assert tariff == Decimal("1500")  # 4 * 250 + 500


@pytest.mark.django_db
def test_calculate_tariff_medium_tier():
    # 100..300 km : tier_medium = 200/kg + 750 fixe.
    route = _route(250)
    tariff = calculate_tariff(
        Decimal("4"), route.origin_city_id, route.destination_city_id, route.company
    )
    assert tariff == Decimal("1550")  # 4 * 200 + 750


@pytest.mark.django_db
def test_calculate_tariff_long_tier():
    # > 300 km : tier_long = 150/kg + 1000 fixe.
    route = _route(450)
    tariff = calculate_tariff(
        Decimal("4"), route.origin_city_id, route.destination_city_id, route.company
    )
    assert tariff == Decimal("1600")  # 4 * 150 + 1000


@pytest.mark.django_db
def test_calculate_tariff_boundary_300_is_medium():
    # 300 km exactement reste dans la tranche moyenne (<=).
    route = _route(300)
    tariff = calculate_tariff(
        Decimal("1"), route.origin_city_id, route.destination_city_id, route.company
    )
    assert tariff == Decimal("950")  # 1 * 200 + 750


@pytest.mark.django_db
def test_calculate_tariff_without_route_raises():
    company = CompanyFactory()
    origin = CityFactory()
    dest = CityFactory()
    with pytest.raises(ValidationError):
        calculate_tariff(Decimal("4"), origin.id, dest.id, company)


@pytest.mark.django_db
def test_generate_tracking_number_increments():
    ParcelFactory(tracking_number=f"COL{timezone.now().year}000044")
    assert generate_tracking_number() == f"COL{timezone.now().year}000045"


@pytest.mark.django_db
def test_register_parcel_generates_tracking_and_tariff():
    route = _route(250)
    data = {
        "company": route.company,
        "origin_city": route.origin_city,
        "destination_city": route.destination_city,
        "sender_name": "Issa KABORE",
        "sender_phone": "+22670000001",
        "recipient_name": "Fatou DIALLO",
        "recipient_phone": "+22660000001",
        "weight_kg": Decimal("3"),
    }
    parcel = register_parcel(data)

    assert parcel.tracking_number.startswith("COL")
    assert parcel.qr_code
    assert parcel.tariff == Decimal("1350")  # 3 * 200 + 750
    assert parcel.status == ParcelStatus.REGISTERED
    assert parcel.synced_at is not None


@pytest.mark.django_db
def test_register_offline_parcel_keeps_local_tracking_and_no_synced_at():
    route = _route(250)
    data = {
        "company": route.company,
        "origin_city": route.origin_city,
        "destination_city": route.destination_city,
        "sender_name": "Issa KABORE",
        "sender_phone": "+22670000001",
        "recipient_name": "Fatou DIALLO",
        "recipient_phone": "+22660000001",
        "weight_kg": Decimal("3"),
        "is_offline": True,
        "tracking_number": "COL2026900001",
        "offline_created_at": timezone.now(),
    }
    parcel = register_parcel(data)

    assert parcel.is_offline is True
    assert parcel.synced_at is None
    assert parcel.tracking_number == "COL2026900001"


@pytest.mark.django_db
def test_notify_recipient_sms_sets_status_and_creates_record():
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    notification = notify_recipient(parcel)

    parcel.refresh_from_db()
    assert notification.method == NotificationMethod.SMS
    assert parcel.status == ParcelStatus.NOTIFIED
    assert ParcelNotification.objects.filter(parcel=parcel, method="sms").count() == 1


@pytest.mark.django_db
def test_notify_recipient_duplicate_sms_raises():
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    notify_recipient(parcel)
    with pytest.raises(ValidationError):
        notify_recipient(parcel)


@pytest.mark.django_db
def test_notify_recipient_call_does_not_block_later_sms():
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    notify_recipient(parcel, method=NotificationMethod.CALL)
    # Un appel manuel ne consomme pas la regle anti-doublon SMS.
    sms = notify_recipient(parcel, method=NotificationMethod.SMS)
    assert sms.method == NotificationMethod.SMS


@pytest.mark.django_db
def test_notify_again_force_bypasses_duplicate_guard():
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    notify_recipient(parcel)
    again = notify_recipient(parcel, method=NotificationMethod.SMS, force=True)
    assert again.method == NotificationMethod.SMS
    assert ParcelNotification.objects.filter(parcel=parcel, method="sms").count() == 2


@pytest.mark.django_db
def test_update_status_collected_stamps_time():
    parcel = ParcelFactory(status=ParcelStatus.NOTIFIED)
    update_status(parcel, ParcelStatus.COLLECTED)
    parcel.refresh_from_db()
    assert parcel.status == ParcelStatus.COLLECTED
    assert parcel.collected_at is not None


@pytest.mark.django_db
def test_update_status_invalid_raises():
    parcel = ParcelFactory()
    with pytest.raises(ValidationError):
        update_status(parcel, "unknown")
