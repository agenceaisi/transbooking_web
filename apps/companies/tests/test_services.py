import pytest
from django.core.exceptions import ValidationError

from apps.companies.models import CompanyStatus
from apps.companies.services import (
    activate_company,
    approve_company,
    reject_company,
    request_company_info,
    suspend_company,
)
from apps.notifications.models import Notification
from apps.users.tests.factories import UserFactory

from .factories import CompanyFactory


@pytest.mark.django_db
def test_approve_company_sets_active():
    company = CompanyFactory(status=CompanyStatus.PENDING)
    approve_company(company)
    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_approve_company_rejects_non_pending():
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    with pytest.raises(ValidationError):
        approve_company(company)


@pytest.mark.django_db
def test_reject_company_requires_reason():
    company = CompanyFactory(status=CompanyStatus.PENDING)
    with pytest.raises(ValidationError):
        reject_company(company, "")


@pytest.mark.django_db
def test_reject_company_stores_reason():
    company = CompanyFactory(status=CompanyStatus.PENDING)
    reject_company(company, "Documents manquants")
    company.refresh_from_db()
    assert company.status == CompanyStatus.REJECTED
    assert company.rejection_reason == "Documents manquants"


@pytest.mark.django_db
def test_suspend_then_activate():
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    suspend_company(company, "Impayes")
    company.refresh_from_db()
    assert company.status == CompanyStatus.SUSPENDED
    assert company.suspension_reason == "Impayes"

    activate_company(company)
    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE
    assert company.suspension_reason == ""


@pytest.mark.django_db
def test_suspend_requires_reason():
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    with pytest.raises(ValidationError):
        suspend_company(company, "  ")


# --------------------------------------------------------------------------- #
# Demande d'informations complementaires (A2)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_request_company_info_sets_status_and_message():
    company = CompanyFactory(status=CompanyStatus.PENDING)

    request_company_info(company, "  Merci de fournir le RCCM.  ")

    company.refresh_from_db()
    assert company.status == CompanyStatus.INFO_REQUESTED
    assert company.info_request_message == "Merci de fournir le RCCM."


@pytest.mark.django_db
def test_request_company_info_requires_message():
    company = CompanyFactory(status=CompanyStatus.PENDING)

    with pytest.raises(ValidationError):
        request_company_info(company, "   ")

    company.refresh_from_db()
    assert company.status == CompanyStatus.PENDING


@pytest.mark.django_db
def test_request_company_info_rejects_closed_request():
    company = CompanyFactory(status=CompanyStatus.ACTIVE)

    with pytest.raises(ValidationError):
        request_company_info(company, "Merci de fournir le RCCM.")


@pytest.mark.django_db
def test_request_company_info_can_be_repeated():
    company = CompanyFactory(status=CompanyStatus.INFO_REQUESTED)

    request_company_info(company, "Il manque encore l'agrement.")

    company.refresh_from_db()
    assert company.status == CompanyStatus.INFO_REQUESTED
    assert company.info_request_message == "Il manque encore l'agrement."


@pytest.mark.django_db
def test_request_company_info_notifies_admin_user_in_app():
    admin = UserFactory(phone="+22670000099")
    company = CompanyFactory(status=CompanyStatus.PENDING, admin_user=admin)

    request_company_info(company, "Merci de fournir le RCCM.")

    notification = Notification.objects.get(user=admin)
    assert notification.reference_type == "company"
    assert notification.reference_id == company.id
    assert "RCCM" in notification.body


@pytest.mark.django_db
def test_request_company_info_without_admin_user_creates_no_notification():
    company = CompanyFactory(status=CompanyStatus.PENDING, admin_user=None)

    request_company_info(company, "Merci de fournir le RCCM.")

    # Une demande d'inscription n'a pas encore de compte : SMS uniquement.
    assert Notification.objects.count() == 0


@pytest.mark.django_db
def test_approve_company_from_info_requested_clears_message():
    company = CompanyFactory(
        status=CompanyStatus.INFO_REQUESTED,
        info_request_message="Merci de fournir le RCCM.",
    )

    approve_company(company)

    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE
    assert company.info_request_message == ""


@pytest.mark.django_db
def test_reject_company_from_info_requested():
    company = CompanyFactory(status=CompanyStatus.INFO_REQUESTED)

    reject_company(company, "Dossier incomplet.")

    company.refresh_from_db()
    assert company.status == CompanyStatus.REJECTED
    assert company.rejection_reason == "Dossier incomplet."
