"""Configuration globale de la plateforme (cf. PROMPT_SUP A5)."""
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from apps.companies.tests.factories import CompanyFactory
from apps.core.models import GlobalSetting
from apps.core.services import (
    SETTING_GLOBAL_COMMISSION_RATE,
    SETTING_MAINTENANCE_MODE,
    get_global_commission_rate,
    is_payment_method_enabled,
)
from apps.users.models import Role, User


SETTINGS_URL = "/api/v1/super/settings/"
COMMISSIONS_URL = "/api/v1/super/settings/commissions/"
PAYMENT_METHODS_URL = "/api/v1/super/settings/payment-methods/"


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


@pytest.fixture
def super_client(api_client):
    api_client.force_authenticate(user=_make_user(Role.RoleName.SUPER_ADMIN, "+22673000001"))
    return api_client


# --------------------------------------------------------------------------- #
# Parametres generaux
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_general_settings_expose_defaults(super_client):
    response = super_client.get(SETTINGS_URL)

    assert response.status_code == 200
    assert response.data["platform_name"] == "TransBooking BF"
    assert response.data["maintenance_mode"] is False
    assert "sms_provider" in response.data
    # Les identifiants SMS ne transitent jamais par l'API.
    assert "sms_api_key" not in response.data


@pytest.mark.django_db
def test_general_settings_patch_persists_values(super_client):
    response = super_client.patch(
        SETTINGS_URL,
        {
            "platform_name": "TransBooking BF (prod)",
            "support_phone": "+22670000000",
            "maintenance_mode": True,
        },
        format="json",
    )

    assert response.status_code == 200
    assert response.data["platform_name"] == "TransBooking BF (prod)"
    assert response.data["maintenance_mode"] is True
    assert GlobalSetting.objects.get(key=SETTING_MAINTENANCE_MODE).value == "true"

    # La valeur est bien relue au GET suivant.
    assert super_client.get(SETTINGS_URL).data["support_phone"] == "+22670000000"


@pytest.mark.django_db
def test_general_settings_reject_invalid_email(super_client):
    response = super_client.patch(
        SETTINGS_URL, {"support_email": "pas-un-email"}, format="json"
    )

    assert response.status_code == 400
    assert "support_email" in response.data


@pytest.mark.django_db
def test_sms_provider_is_read_only(super_client):
    response = super_client.patch(SETTINGS_URL, {"sms_provider": "pirate"}, format="json")

    assert response.status_code == 200
    assert response.data["sms_provider"] != "pirate"


# --------------------------------------------------------------------------- #
# Commissions
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_commissions_list_global_rate_and_overrides(super_client):
    CompanyFactory(name="Avec surcharge", commission_rate=Decimal("8.00"))
    CompanyFactory(name="Sans surcharge", commission_rate=None)

    response = super_client.get(COMMISSIONS_URL)

    assert response.status_code == 200
    names = [o["company_name"] for o in response.data["company_overrides"]]
    assert names == ["Avec surcharge"]
    assert Decimal(response.data["global_rate"]) > 0


@pytest.mark.django_db
def test_commissions_patch_updates_global_rate_and_override(super_client):
    company = CompanyFactory(commission_rate=None)

    response = super_client.patch(
        COMMISSIONS_URL,
        {
            "global_rate": "12.50",
            "company_overrides": [{"company_id": company.id, "commission_rate": "7.00"}],
        },
        format="json",
    )

    assert response.status_code == 200
    company.refresh_from_db()
    assert company.commission_rate == Decimal("7.00")
    assert get_global_commission_rate() == Decimal("12.50")
    assert GlobalSetting.objects.filter(key=SETTING_GLOBAL_COMMISSION_RATE).exists()


@pytest.mark.django_db
def test_commission_override_can_be_cleared(super_client):
    company = CompanyFactory(commission_rate=Decimal("8.00"))

    response = super_client.patch(
        COMMISSIONS_URL,
        {"company_overrides": [{"company_id": company.id, "commission_rate": None}]},
        format="json",
    )

    assert response.status_code == 200
    company.refresh_from_db()
    # null => la compagnie repasse au taux global.
    assert company.commission_rate is None


@pytest.mark.django_db
def test_commissions_reject_rate_out_of_bounds(super_client):
    response = super_client.patch(COMMISSIONS_URL, {"global_rate": "150"}, format="json")

    assert response.status_code == 400
    assert "global_rate" in response.data


@pytest.mark.django_db
def test_commissions_reject_unknown_company(super_client):
    response = super_client.patch(
        COMMISSIONS_URL,
        {"company_overrides": [{"company_id": 999999, "commission_rate": "5.00"}]},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_global_rate_is_used_by_commission_computation(super_client):
    from apps.payments.services import compute_commission

    company = CompanyFactory(commission_rate=None)
    super_client.patch(COMMISSIONS_URL, {"global_rate": "20.00"}, format="json")

    assert compute_commission(Decimal("10000"), company) == Decimal("2000.00")


# --------------------------------------------------------------------------- #
# Moyens de paiement plateforme
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_payment_methods_default_to_enabled(super_client):
    response = super_client.get(PAYMENT_METHODS_URL)

    assert response.status_code == 200
    methods = {entry["method"]: entry["is_active"] for entry in response.data}
    assert methods == {
        "orange_money": True,
        "moov_money": True,
        "coris_money": True,
        "telecel_money": True,
        "card": True,
    }


@pytest.mark.django_db
def test_payment_method_can_be_disabled(super_client):
    response = super_client.patch(
        PAYMENT_METHODS_URL,
        {"payment_methods": [{"method": "card", "is_active": False}]},
        format="json",
    )

    assert response.status_code == 200
    methods = {entry["method"]: entry["is_active"] for entry in response.data}
    assert methods["card"] is False
    assert methods["orange_money"] is True
    assert is_payment_method_enabled("card") is False
    # Les especes restent toujours disponibles.
    assert is_payment_method_enabled("cash") is True


@pytest.mark.django_db
def test_payment_methods_reject_unknown_method(super_client):
    response = super_client.patch(
        PAYMENT_METHODS_URL,
        {"payment_methods": [{"method": "bitcoin", "is_active": True}]},
        format="json",
    )

    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_admin_cannot_reach_platform_settings(api_client):
    company = CompanyFactory()
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22673000010")
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    assert api_client.get(SETTINGS_URL).status_code == 403
    assert api_client.get(COMMISSIONS_URL).status_code == 403
    assert api_client.patch(PAYMENT_METHODS_URL, {}, format="json").status_code == 403


@pytest.mark.django_db
def test_platform_settings_require_authentication(api_client):
    assert api_client.get(SETTINGS_URL).status_code == 401
    assert api_client.get(COMMISSIONS_URL).status_code == 401
    assert api_client.get(PAYMENT_METHODS_URL).status_code == 401
