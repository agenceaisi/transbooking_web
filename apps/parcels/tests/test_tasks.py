import pytest

from apps.companies.tests.factories import CompanyNotificationSettingsFactory
from apps.parcels.models import NotificationMethod, ParcelNotification, ParcelStatus
from apps.parcels.tasks import send_parcel_arrival_sms, send_parcel_dispatch_sms

from .factories import ParcelFactory


@pytest.fixture
def sent(monkeypatch):
    """Capture (phone, message) tuples sent through the SMS gateway."""
    calls = []
    monkeypatch.setattr(
        "apps.parcels.tasks.send_sms",
        lambda phone, message: calls.append((phone, message)),
    )
    return calls


@pytest.mark.django_db
def test_dispatch_sms_sent_to_recipient(sent):
    parcel = ParcelFactory()

    send_parcel_dispatch_sms(parcel.pk)

    assert len(sent) == 1
    phone, message = sent[0]
    assert phone == parcel.recipient_phone
    assert parcel.tracking_number in message
    # Le SMS d'enregistrement ne consomme pas la regle anti-doublon.
    assert ParcelNotification.objects.filter(parcel=parcel).count() == 0


@pytest.mark.django_db
def test_arrival_sms_records_notification_and_sets_status(sent):
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)

    send_parcel_arrival_sms(parcel.pk)

    parcel.refresh_from_db()
    assert len(sent) == 1
    assert parcel.status == ParcelStatus.NOTIFIED
    assert ParcelNotification.objects.filter(
        parcel=parcel, method=NotificationMethod.SMS
    ).count() == 1


@pytest.mark.django_db
def test_arrival_sms_is_idempotent(sent):
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)

    send_parcel_arrival_sms(parcel.pk)
    send_parcel_arrival_sms(parcel.pk)

    assert len(sent) == 1
    assert ParcelNotification.objects.filter(parcel=parcel).count() == 1


@pytest.mark.django_db
def test_arrival_sms_skipped_when_company_disabled(sent):
    parcel = ParcelFactory(status=ParcelStatus.ARRIVED)
    CompanyNotificationSettingsFactory(
        company=parcel.company, sms_parcel_arrival=False
    )

    send_parcel_arrival_sms(parcel.pk)

    parcel.refresh_from_db()
    assert sent == []
    assert parcel.status == ParcelStatus.ARRIVED
    assert ParcelNotification.objects.filter(parcel=parcel).count() == 0
