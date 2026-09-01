import pytest

from apps.payments.models import PaymentStatus

from .factories import PaymentFactory


@pytest.mark.django_db
def test_payment_str_contains_amount_and_status():
    payment = PaymentFactory(amount=5000, status=PaymentStatus.PENDING)
    label = str(payment)
    assert "5000" in label
    assert PaymentStatus.PENDING in label


@pytest.mark.django_db
def test_payment_defaults_to_pending():
    payment = PaymentFactory()
    assert payment.status == PaymentStatus.PENDING
    assert payment.paid_at is None
    assert payment.receipt_url == ""
