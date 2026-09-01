import pytest

from apps.companies.models import CompanyNotificationSettings, CompanyStatus

from .factories import CompanyFactory, CompanyPaymentMethodFactory


@pytest.mark.django_db
def test_company_defaults_to_pending_status():
    company = CompanyFactory(status=CompanyStatus.PENDING)
    assert company.status == CompanyStatus.PENDING
    assert str(company) == company.name


@pytest.mark.django_db
def test_payment_method_unique_per_company():
    pm = CompanyPaymentMethodFactory()
    assert pm.is_active is True
    assert pm.company.payment_methods.count() == 1


@pytest.mark.django_db
def test_notification_settings_defaults_true():
    company = CompanyFactory()
    settings_obj = CompanyNotificationSettings.objects.create(company=company)
    assert settings_obj.sms_booking_confirmation is True
    assert settings_obj.sms_departure_reminder is True
    assert settings_obj.sms_parcel_arrival is True
