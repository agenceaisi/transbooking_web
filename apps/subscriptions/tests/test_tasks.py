from datetime import timedelta

import pytest
from django.utils import timezone

from apps.companies.models import CompanyStatus
from apps.subscriptions.models import SubscriptionStatus
from apps.subscriptions.tasks import check_expiring_subscriptions

from .factories import SubscriptionFactory


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.subscriptions.tasks.send_sms", lambda *a, **k: None)
    monkeypatch.setattr("apps.companies.services.send_sms", lambda *a, **k: None)


@pytest.mark.django_db
def test_reminder_sent_once_for_subscription_expiring_within_7_days():
    today = timezone.localdate()
    sub = SubscriptionFactory(end_date=today + timedelta(days=5))

    summary = check_expiring_subscriptions()

    sub.refresh_from_db()
    assert summary["reminded"] == 1
    assert sub.expiry_reminder_sent is True

    # Idempotence : un second passage ne re-notifie pas.
    summary = check_expiring_subscriptions()
    assert summary["reminded"] == 0


@pytest.mark.django_db
def test_expired_without_auto_renew_suspends_company():
    today = timezone.localdate()
    sub = SubscriptionFactory(end_date=today - timedelta(days=1), auto_renew=False)

    summary = check_expiring_subscriptions()

    sub.refresh_from_db()
    sub.company.refresh_from_db()
    assert summary["suspended"] == 1
    assert sub.status == SubscriptionStatus.EXPIRED
    assert sub.company.status == CompanyStatus.SUSPENDED


@pytest.mark.django_db
def test_expired_with_auto_renew_extends_subscription():
    today = timezone.localdate()
    sub = SubscriptionFactory(
        end_date=today - timedelta(days=1), auto_renew=True
    )

    summary = check_expiring_subscriptions()

    sub.refresh_from_db()
    assert summary["renewed"] == 1
    assert sub.status == SubscriptionStatus.ACTIVE
    assert sub.end_date > today
    assert sub.expiry_reminder_sent is False
    assert sub.company.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_healthy_subscription_is_untouched():
    today = timezone.localdate()
    sub = SubscriptionFactory(end_date=today + timedelta(days=30))

    summary = check_expiring_subscriptions()

    sub.refresh_from_db()
    assert summary == {"reminded": 0, "renewed": 0, "suspended": 0}
    assert sub.expiry_reminder_sent is False
