import pytest

from apps.parcels.models import NotificationMethod, ParcelStatus

from .factories import ParcelFactory


@pytest.mark.django_db
def test_parcel_str_is_tracking_number():
    parcel = ParcelFactory(tracking_number="COL2026000123")
    assert str(parcel) == "COL2026000123"


@pytest.mark.django_db
def test_parcel_defaults_to_registered():
    parcel = ParcelFactory()
    assert parcel.status == ParcelStatus.REGISTERED


@pytest.mark.django_db
def test_parcel_notification_str(monkeypatch):
    parcel = ParcelFactory(tracking_number="COL2026000777")
    notification = parcel.notifications.create(method=NotificationMethod.SMS)
    assert "COL2026000777" in str(notification)
    assert "SMS" in str(notification)
