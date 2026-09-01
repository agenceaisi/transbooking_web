from decimal import Decimal

import pytest

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from rest_framework.exceptions import ValidationError

from apps.payments.exceptions import (
    BookingAlreadyPaid,
    PaymentAlreadyConfirmed,
    PaymentProviderError,
    PaymentProviderNotConfigured,
    TransactionRefRequired,
)
from apps.payments.models import PaymentMethod, PaymentStatus
from apps.payments.providers import (
    MockPaymentProvider,
    MoovMoneyProvider,
    OrangeMoneyProvider,
    get_payment_provider,
)
from apps.payments.services import (
    compute_commission,
    confirm_payment,
    generate_receipt_pdf,
    hash_otp_code,
    initiate_payment,
    start_redirect_flow,
)

from .factories import PaymentFactory


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    monkeypatch.setattr("apps.payments.services.send_sms", lambda *a, **k: None)


@pytest.mark.django_db
def test_initiate_cash_payment_creates_pending_payment():
    booking = BookingFactory(status=BookingStatus.PENDING, amount=5000)

    payment = initiate_payment(booking, method=PaymentMethod.CASH)

    assert payment.status == PaymentStatus.PENDING
    assert payment.amount == booking.amount
    assert payment.booking == booking


@pytest.mark.django_db
def test_initiate_mobile_payment_starts_otp_flow():
    booking = BookingFactory(status=BookingStatus.PENDING, amount=5000)

    payment = initiate_payment(
        booking, method=PaymentMethod.ORANGE_MONEY, phone="+22670000001"
    )

    assert payment.status == PaymentStatus.OTP_REQUIRED
    assert payment.provider_ref
    assert payment.otps.count() == 1


@pytest.mark.django_db
def test_initiate_payment_rejects_already_paid_booking():
    booking = BookingFactory(status=BookingStatus.PAID)
    with pytest.raises(BookingAlreadyPaid):
        initiate_payment(booking, method=PaymentMethod.CASH)


@pytest.mark.django_db
def test_confirm_payment_marks_booking_paid():
    booking = BookingFactory(status=BookingStatus.PENDING)
    payment = PaymentFactory(booking=booking, method=PaymentMethod.CASH)

    payment = confirm_payment(payment)

    booking.refresh_from_db()
    assert payment.status == PaymentStatus.PAID
    assert payment.paid_at is not None
    assert payment.receipt_url
    assert booking.status == BookingStatus.PAID


@pytest.mark.django_db
def test_confirm_mobile_money_requires_transaction_ref():
    payment = PaymentFactory(method=PaymentMethod.MOOV_MONEY)
    with pytest.raises(TransactionRefRequired):
        confirm_payment(payment, transaction_ref="")


@pytest.mark.django_db
def test_confirm_payment_is_idempotent():
    payment = PaymentFactory(method=PaymentMethod.CASH)
    confirm_payment(payment)
    payment.refresh_from_db()
    with pytest.raises(PaymentAlreadyConfirmed):
        confirm_payment(payment)


@pytest.mark.django_db
def test_confirm_payment_freezes_commission():
    booking = BookingFactory(status=BookingStatus.PENDING, amount=Decimal("10000"))
    booking.trip.route.company.commission_rate = Decimal("8.00")
    booking.trip.route.company.save(update_fields=["commission_rate"])
    payment = PaymentFactory(booking=booking, amount=Decimal("10000"), method=PaymentMethod.CASH)

    payment = confirm_payment(payment)

    assert payment.commission == Decimal("800.00")


@pytest.mark.django_db
def test_compute_commission_falls_back_to_default(settings):
    settings.COMMISSION_RATE_DEFAULT = 10.0
    assert compute_commission(Decimal("5000"), company=None) == Decimal("500.00")


@pytest.mark.django_db
def test_generate_receipt_pdf_returns_pdf_bytes():
    payment = confirm_payment(PaymentFactory(method=PaymentMethod.CASH))
    pdf = generate_receipt_pdf(payment)
    assert isinstance(pdf, bytes)
    assert pdf[:4] == b"%PDF"


# --------------------------------------------------------------------------- #
# Fournisseurs Mobile Money (cf. PROMPT_SUP B1)
# --------------------------------------------------------------------------- #
def test_sandbox_routes_every_method_to_the_mock_provider(settings):
    settings.PAYMENT_SANDBOX = True
    settings.PAYMENT_PROVIDER = "orange_money"

    provider = get_payment_provider(PaymentMethod.ORANGE_MONEY)

    assert isinstance(provider, MockPaymentProvider)
    assert provider.generates_otp is False


def test_provider_is_resolved_from_the_method_outside_sandbox(settings):
    settings.PAYMENT_SANDBOX = False
    settings.PAYMENT_PROVIDER = "mock"

    provider = get_payment_provider(PaymentMethod.MOOV_MONEY)

    assert isinstance(provider, MoovMoneyProvider)
    # L'operateur reel genere et verifie lui-meme le code.
    assert provider.generates_otp is True


def test_unknown_method_has_no_provider(settings):
    settings.PAYMENT_SANDBOX = False
    settings.PAYMENT_PROVIDER = "mock"

    with pytest.raises(PaymentProviderNotConfigured):
        get_payment_provider("bitcoin")


def test_operator_provider_requires_credentials(settings):
    settings.PAYMENT_API_BASE_URL = ""
    settings.PAYMENT_API_KEY = ""
    settings.PAYMENT_API_SECRET = ""
    settings.PAYMENT_API_MERCHANT_ID = ""

    with pytest.raises(PaymentProviderNotConfigured):
        OrangeMoneyProvider().initiate(payment=None)


@pytest.mark.django_db
def test_mobile_payment_stays_pending_with_a_redirect_provider(settings):
    """Orange Money direct n'ouvre pas sa transaction des l'initiation.

    Ce test remplace `test_mobile_payment_fails_when_operator_is_not_wired`,
    ecrit quand tous les operateurs suivaient le parcours OTP. Orange Money en
    compte marchand direct suit l'autre parcours : la transaction ne s'ouvre
    qu'une fois connues les URL de retour et de notification, que seul
    l'appelant connait. Le paiement reste donc `pending` — mais il ne peut
    surtout pas etre considere comme regle.
    """
    settings.PAYMENT_SANDBOX = False
    settings.PAYMENT_PROVIDER = "mock"
    settings.PAYMENT_API_BASE_URL = "https://operateur.example"
    settings.PAYMENT_API_KEY = "key"
    settings.PAYMENT_API_SECRET = "secret"
    settings.PAYMENT_API_MERCHANT_ID = "merchant"
    booking = BookingFactory(status=BookingStatus.PENDING)

    payment = initiate_payment(
        booking, method=PaymentMethod.ORANGE_MONEY, phone="+22670000001"
    )

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING
    assert payment.status == PaymentStatus.PENDING
    # Aucun code de confirmation n'a ete emis : ce parcours n'en utilise pas.
    assert not payment.otps.exists()


@pytest.mark.django_db
def test_redirect_flow_refuses_to_start_without_credentials(settings):
    """Sans identifiants marchands, la transaction ne s'ouvre pas.

    Le garde-fou qui compte : un deploiement mal configure doit echouer bruyamment
    au moment du paiement, jamais delivrer un billet sans encaisser.
    """
    settings.PAYMENT_SANDBOX = False
    settings.PAYMENT_PROVIDER = "mock"
    settings.PAYMENT_API_BASE_URL = ""
    settings.PAYMENT_API_KEY = ""
    settings.PAYMENT_API_SECRET = ""
    settings.PAYMENT_API_MERCHANT_ID = ""
    booking = BookingFactory(status=BookingStatus.PENDING)
    payment = initiate_payment(
        booking, method=PaymentMethod.ORANGE_MONEY, phone="+22670000001"
    )

    with pytest.raises(PaymentProviderNotConfigured):
        start_redirect_flow(
            payment,
            return_url="https://exemple.bf/retour/",
            cancel_url="https://exemple.bf/annule/",
            notify_url="https://exemple.bf/webhook/",
        )

    booking.refresh_from_db()
    assert booking.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_disabled_payment_method_is_refused():
    from apps.core.services import set_payment_methods_config

    set_payment_methods_config([{"method": PaymentMethod.ORANGE_MONEY, "is_active": False}])
    booking = BookingFactory(status=BookingStatus.PENDING)

    with pytest.raises(ValidationError):
        initiate_payment(
            booking, method=PaymentMethod.ORANGE_MONEY, phone="+22670000001"
        )


def test_hash_otp_code_is_not_reversible():
    digest = hash_otp_code("123456")

    assert digest != "123456"
    assert "123456" not in digest
    assert digest == hash_otp_code("123456")
    assert digest != hash_otp_code("123457")
