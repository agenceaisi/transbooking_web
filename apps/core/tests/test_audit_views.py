"""Audit et notifications super admin (cf. PROMPT_SUP A6)."""
from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.claims.models import ClaimStatus
from apps.claims.tests.factories import ClaimFactory
from apps.companies.models import CompanyStatus
from apps.companies.tests.factories import CompanyFactory
from apps.core.models import ActivityLog
from apps.speed_reports.tests.factories import SpeedReportFactory
from apps.subscriptions.models import SubscriptionStatus
from apps.subscriptions.tests.factories import SubscriptionFactory
from apps.users.models import Role, User


ACTIVITY_LOGS_URL = "/api/v1/super/activity-logs/"
SUPER_NOTIFICATIONS_URL = "/api/v1/super/notifications/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.companies.services.send_sms", lambda *a, **k: None)


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Ali",
        nom="Traore",
        phone=phone,
        password="password123",
        role=role,
    )


@pytest.fixture
def super_admin():
    return _make_user(Role.RoleName.SUPER_ADMIN, "+22674000001")


@pytest.fixture
def super_client(api_client, super_admin):
    api_client.force_authenticate(user=super_admin)
    return api_client


# --------------------------------------------------------------------------- #
# Journal d'audit
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_sensitive_company_actions_are_logged(super_client, super_admin):
    company = CompanyFactory(status=CompanyStatus.PENDING)

    super_client.post(f"/api/v1/super/company-requests/{company.id}/approve/")

    log = ActivityLog.objects.get(action="company.approve")
    assert log.user_id == super_admin.id
    assert log.entity_type == "company"
    assert log.entity_id == company.id


@pytest.mark.django_db
def test_suspension_reason_is_recorded(super_client):
    company = CompanyFactory(status=CompanyStatus.ACTIVE)

    super_client.post(
        f"/api/v1/super/companies/{company.id}/suspend/",
        {"reason": "Impayes"},
        format="json",
    )

    log = ActivityLog.objects.get(action="company.suspend")
    assert log.details == {"reason": "Impayes"}


@pytest.mark.django_db
def test_activity_logs_are_listed_most_recent_first(super_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    super_client.post(f"/api/v1/super/company-requests/{company.id}/request-info/",
                      {"message": "RCCM manquant."}, format="json")
    super_client.post(f"/api/v1/super/company-requests/{company.id}/approve/")

    response = super_client.get(ACTIVITY_LOGS_URL)

    assert response.status_code == 200
    actions = [entry["action"] for entry in response.data["results"]]
    assert actions[:2] == ["company.approve", "company.request_info"]
    assert response.data["results"][0]["user_role"] == Role.RoleName.SUPER_ADMIN


@pytest.mark.django_db
def test_activity_logs_filter_by_action_and_entity(super_client):
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    super_client.post(
        f"/api/v1/super/companies/{company.id}/suspend/", {"reason": "X"}, format="json"
    )
    super_client.patch("/api/v1/super/settings/", {"maintenance_mode": True}, format="json")

    by_action = super_client.get(f"{ACTIVITY_LOGS_URL}?action=company.")
    by_entity = super_client.get(f"{ACTIVITY_LOGS_URL}?entity_type=global_setting")

    assert by_action.data["count"] == 1
    assert by_action.data["results"][0]["action"] == "company.suspend"
    assert by_entity.data["count"] == 1
    assert by_entity.data["results"][0]["action"] == "settings.update"


@pytest.mark.django_db
def test_activity_logs_filter_by_user_and_dates(super_client, super_admin):
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    super_client.post(
        f"/api/v1/super/companies/{company.id}/suspend/", {"reason": "X"}, format="json"
    )
    today = timezone.localdate()

    by_user = super_client.get(f"{ACTIVITY_LOGS_URL}?user={super_admin.id}")
    in_range = super_client.get(
        f"{ACTIVITY_LOGS_URL}?date_from={today}&date_to={today}"
    )
    out_of_range = super_client.get(
        f"{ACTIVITY_LOGS_URL}?date_from={today + timedelta(days=1)}"
    )

    assert by_user.data["count"] == 1
    assert in_range.data["count"] == 1
    assert out_of_range.data["count"] == 0


@pytest.mark.django_db
def test_system_action_is_attributed_to_systeme(super_client):
    from apps.companies.services import suspend_company

    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    # actor=None : suspension declenchee par la tache d'expiration d'abonnement.
    suspend_company(company, "Abonnement expire.")

    response = super_client.get(ACTIVITY_LOGS_URL)

    assert response.data["results"][0]["user"] is None
    assert response.data["results"][0]["user_name"] == "Systeme"


@pytest.mark.django_db
def test_activity_logs_forbidden_for_company_admin(api_client):
    company = CompanyFactory()
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22674000010")
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    assert api_client.get(ACTIVITY_LOGS_URL).status_code == 403


@pytest.mark.django_db
def test_activity_logs_require_authentication(api_client):
    assert api_client.get(ACTIVITY_LOGS_URL).status_code == 401


# --------------------------------------------------------------------------- #
# Fil de supervision super admin
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_super_notifications_list_new_registrations(super_client):
    CompanyFactory(status=CompanyStatus.PENDING, name="Nouvelle compagnie")
    CompanyFactory(status=CompanyStatus.ACTIVE, name="Deja active")

    response = super_client.get(SUPER_NOTIFICATIONS_URL)

    assert response.status_code == 200
    registrations = [
        item for item in response.data["results"] if item["type"] == "new_registration"
    ]
    assert len(registrations) == 1
    assert "Nouvelle compagnie" in registrations[0]["body"]


@pytest.mark.django_db
def test_super_notifications_list_expired_subscriptions(super_client):
    today = timezone.localdate()
    SubscriptionFactory(
        end_date=today - timedelta(days=2),
        status=SubscriptionStatus.EXPIRED,
    )
    SubscriptionFactory(end_date=today + timedelta(days=30))

    response = super_client.get(f"{SUPER_NOTIFICATIONS_URL}?type=subscription_expired")

    assert response.data["count"] == 1
    assert response.data["results"][0]["severity"] == "warning"


@pytest.mark.django_db
def test_super_notifications_list_urgent_reports(super_client):
    SpeedReportFactory()
    ClaimFactory(status=ClaimStatus.ESCALATED)

    response = super_client.get(f"{SUPER_NOTIFICATIONS_URL}?type=urgent_report")

    assert response.data["count"] == 2
    assert {item["reference_type"] for item in response.data["results"]} == {
        "speed_report",
        "claim",
    }


@pytest.mark.django_db
def test_super_notifications_filter_by_severity(super_client):
    CompanyFactory(status=CompanyStatus.PENDING)
    SpeedReportFactory()

    response = super_client.get(f"{SUPER_NOTIFICATIONS_URL}?severity=critical")

    assert response.data["count"] == 1
    assert response.data["results"][0]["type"] == "urgent_report"


@pytest.mark.django_db
def test_super_notifications_are_paginated(super_client):
    for _ in range(3):
        CompanyFactory(status=CompanyStatus.PENDING)

    response = super_client.get(f"{SUPER_NOTIFICATIONS_URL}?page_size=2")

    assert response.data["count"] == 3
    assert len(response.data["results"]) == 2
    assert response.data["next"] is not None


@pytest.mark.django_db
def test_super_notifications_forbidden_for_other_roles(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22674000020")
    api_client.force_authenticate(user=voyageur)

    assert api_client.get(SUPER_NOTIFICATIONS_URL).status_code == 403


@pytest.mark.django_db
def test_super_notifications_require_authentication(api_client):
    assert api_client.get(SUPER_NOTIFICATIONS_URL).status_code == 401
