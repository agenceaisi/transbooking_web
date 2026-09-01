from datetime import timedelta

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.companies.models import CompanyStatus
from apps.companies.tests.factories import CompanyFactory
from apps.subscriptions.models import (
    Subscription,
    SubscriptionInvoice,
    SubscriptionStatus,
)
from apps.users.models import Role, User

from .factories import SubscriptionFactory, SubscriptionPlanFactory


PLANS_URL = "/api/v1/super/subscription-plans/"
SUBSCRIPTIONS_URL = "/api/v1/super/subscriptions/"
COMPANY_SUBSCRIPTION_URL = "/api/v1/company/subscription/"
COMPANY_INVOICES_URL = "/api/v1/company/subscription/invoices/"


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test",
        nom="User",
        phone=phone,
        password="password123",
        role=role,
    )


def _make_company_admin(company, phone: str) -> User:
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    return admin


# --------------------------------------------------------------------------- #
# Forfaits (super admin)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_super_admin_creates_and_lists_plans(api_client):
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000001")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        PLANS_URL,
        {"name": "Premium", "price": "75000.00", "duration_months": 12},
        format="json",
    )
    assert response.status_code == 201
    assert response.data["name"] == "Premium"

    listing = api_client.get(PLANS_URL)
    assert listing.status_code == 200
    assert "Premium" in [p["name"] for p in listing.data["results"]]


@pytest.mark.django_db
def test_super_admin_updates_and_deletes_plan(api_client):
    plan = SubscriptionPlanFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000002")
    api_client.force_authenticate(user=admin)

    patch = api_client.patch(f"{PLANS_URL}{plan.id}/", {"price": "60000.00"}, format="json")
    assert patch.status_code == 200
    assert patch.data["price"] == "60000.00"

    delete = api_client.delete(f"{PLANS_URL}{plan.id}/")
    assert delete.status_code == 204


@pytest.mark.django_db
def test_plan_used_by_a_subscription_cannot_be_deleted(api_client):
    subscription = SubscriptionFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000003")
    api_client.force_authenticate(user=admin)

    response = api_client.delete(f"{PLANS_URL}{subscription.plan_id}/")

    assert response.status_code == 400
    assert "detail" in response.data


@pytest.mark.django_db
def test_plan_rejects_invalid_duration(api_client):
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000004")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        PLANS_URL,
        {"name": "Invalide", "price": "1000", "duration_months": 0},
        format="json",
    )

    assert response.status_code == 400
    assert "duration_months" in response.data


@pytest.mark.django_db
def test_company_admin_cannot_manage_plans(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22671000005")
    api_client.force_authenticate(user=admin)

    assert api_client.get(PLANS_URL).status_code == 403
    assert api_client.post(PLANS_URL, {"name": "X", "price": "1"}, format="json").status_code == 403


@pytest.mark.django_db
def test_plans_require_authentication(api_client):
    assert api_client.get(PLANS_URL).status_code == 401


# --------------------------------------------------------------------------- #
# Abonnements (super admin)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_super_admin_assigns_plan_to_company_and_issues_invoice(api_client):
    company = CompanyFactory()
    plan = SubscriptionPlanFactory(duration_months=12, price=100000)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000010")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        SUBSCRIPTIONS_URL,
        {"company": company.id, "plan": plan.id, "auto_renew": True},
        format="json",
    )

    assert response.status_code == 201
    subscription = Subscription.objects.get(company=company)
    assert subscription.status == SubscriptionStatus.ACTIVE
    # end_date deduite de la duree du forfait.
    assert subscription.end_date == subscription.start_date + timedelta(days=365)
    assert response.data["days_remaining"] > 0
    invoice = SubscriptionInvoice.objects.get(subscription=subscription)
    assert invoice.amount == plan.price
    assert invoice.paid_at is None


@pytest.mark.django_db
def test_assigning_a_second_running_subscription_is_rejected(api_client):
    subscription = SubscriptionFactory()
    plan = SubscriptionPlanFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000011")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        SUBSCRIPTIONS_URL,
        {"company": subscription.company_id, "plan": plan.id},
        format="json",
    )

    assert response.status_code == 400
    assert "company" in response.data


@pytest.mark.django_db
def test_super_admin_deactivates_subscription_with_patch(api_client):
    subscription = SubscriptionFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000012")
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        f"{SUBSCRIPTIONS_URL}{subscription.id}/",
        {"status": SubscriptionStatus.CANCELLED},
        format="json",
    )

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.status == SubscriptionStatus.CANCELLED


@pytest.mark.django_db
def test_patch_rejects_end_date_before_start_date(api_client):
    subscription = SubscriptionFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000013")
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        f"{SUBSCRIPTIONS_URL}{subscription.id}/",
        {"end_date": (subscription.start_date - timedelta(days=1)).isoformat()},
        format="json",
    )

    assert response.status_code == 400
    assert "end_date" in response.data


@pytest.mark.django_db
def test_super_admin_renews_subscription(api_client):
    subscription = SubscriptionFactory()
    previous_end = subscription.end_date
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22671000014")
    api_client.force_authenticate(user=admin)

    response = api_client.post(f"{SUBSCRIPTIONS_URL}{subscription.id}/renew/")

    assert response.status_code == 200
    subscription.refresh_from_db()
    assert subscription.end_date > previous_end
    assert subscription.invoices.count() == 1


@pytest.mark.django_db
def test_company_admin_cannot_reach_super_subscriptions(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22671000015")
    api_client.force_authenticate(user=admin)

    assert api_client.get(SUBSCRIPTIONS_URL).status_code == 403


# --------------------------------------------------------------------------- #
# Company admin — forfait courant et factures
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_admin_reads_its_current_subscription(api_client):
    subscription = SubscriptionFactory()
    admin = _make_company_admin(subscription.company, "+22671000020")
    api_client.force_authenticate(user=admin)

    response = api_client.get(COMPANY_SUBSCRIPTION_URL)

    assert response.status_code == 200
    assert response.data["id"] == subscription.id
    assert response.data["plan"]["name"] == subscription.plan.name
    assert response.data["renewal_date"] == subscription.end_date.isoformat()
    assert response.data["is_current"] is True


@pytest.mark.django_db
def test_company_admin_without_subscription_gets_404(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22671000021")
    api_client.force_authenticate(user=admin)

    assert api_client.get(COMPANY_SUBSCRIPTION_URL).status_code == 404


@pytest.mark.django_db
def test_company_admin_lists_only_its_own_invoices(api_client):
    mine = SubscriptionFactory()
    other = SubscriptionFactory()
    SubscriptionInvoice.objects.create(subscription=mine, amount=50000)
    SubscriptionInvoice.objects.create(subscription=other, amount=99999)
    admin = _make_company_admin(mine.company, "+22671000022")
    api_client.force_authenticate(user=admin)

    response = api_client.get(COMPANY_INVOICES_URL)

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["amount"] == "50000.00"
    assert response.data["results"][0]["is_paid"] is False


@pytest.mark.django_db
def test_company_admin_downloads_invoice_pdf(api_client):
    subscription = SubscriptionFactory()
    invoice = SubscriptionInvoice.objects.create(subscription=subscription, amount=50000)
    admin = _make_company_admin(subscription.company, "+22671000023")
    api_client.force_authenticate(user=admin)

    response = api_client.get(f"{COMPANY_INVOICES_URL}{invoice.id}/download/")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")


@pytest.mark.django_db
def test_company_admin_cannot_download_another_company_invoice(api_client):
    mine = SubscriptionFactory()
    other = SubscriptionFactory()
    invoice = SubscriptionInvoice.objects.create(subscription=other, amount=50000)
    admin = _make_company_admin(mine.company, "+22671000024")
    api_client.force_authenticate(user=admin)

    response = api_client.get(f"{COMPANY_INVOICES_URL}{invoice.id}/download/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_voyageur_cannot_reach_company_subscription(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22671000025")
    api_client.force_authenticate(user=voyageur)

    assert api_client.get(COMPANY_SUBSCRIPTION_URL).status_code == 403
    assert api_client.get(COMPANY_INVOICES_URL).status_code == 403


# --------------------------------------------------------------------------- #
# Regle : abonnement expire => compagnie traitee comme suspendue
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_expired_subscription_blocks_company_admin_routes(api_client):
    today = timezone.localdate()
    subscription = SubscriptionFactory(
        start_date=today - timedelta(days=60),
        end_date=today - timedelta(days=1),
        status=SubscriptionStatus.EXPIRED,
    )
    admin = _make_company_admin(subscription.company, "+22671000030")
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/settings/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_expired_subscription_keeps_billing_routes_reachable(api_client):
    today = timezone.localdate()
    subscription = SubscriptionFactory(
        start_date=today - timedelta(days=60),
        end_date=today - timedelta(days=1),
        status=SubscriptionStatus.EXPIRED,
    )
    SubscriptionInvoice.objects.create(subscription=subscription, amount=50000)
    admin = _make_company_admin(subscription.company, "+22671000031")
    api_client.force_authenticate(user=admin)

    detail = api_client.get(COMPANY_SUBSCRIPTION_URL)
    invoices = api_client.get(COMPANY_INVOICES_URL)

    assert detail.status_code == 200
    assert detail.data["is_current"] is False
    assert invoices.status_code == 200
    assert invoices.data["count"] == 1


@pytest.mark.django_db
def test_suspended_company_still_reaches_its_invoices(api_client):
    subscription = SubscriptionFactory()
    company = subscription.company
    company.status = CompanyStatus.SUSPENDED
    company.save(update_fields=["status"])
    admin = _make_company_admin(company, "+22671000032")
    api_client.force_authenticate(user=admin)

    assert api_client.get(COMPANY_INVOICES_URL).status_code == 200
    assert api_client.get("/api/v1/company/settings/").status_code == 403


@pytest.mark.django_db
def test_active_subscription_keeps_company_admin_routes_open(api_client):
    subscription = SubscriptionFactory()
    admin = _make_company_admin(subscription.company, "+22671000033")
    api_client.force_authenticate(user=admin)

    assert api_client.get("/api/v1/company/settings/").status_code == 200


@pytest.mark.django_db
def test_company_without_any_subscription_is_not_blocked(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22671000034")
    api_client.force_authenticate(user=admin)

    assert api_client.get("/api/v1/company/settings/").status_code == 200
