import logging
from datetime import timedelta
from decimal import Decimal
from io import BytesIO

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from rest_framework.exceptions import ValidationError

from apps.bookings.models import Booking, BookingStatus
from utils.sms import send_sms

from .exceptions import (
    BookingAlreadyPaid,
    OtpExpired,
    OtpInvalid,
    OtpMaxAttemptsReached,
    OtpNotRequired,
    OtpResendTooSoon,
    PaymentAlreadyConfirmed,
    PaymentFlowNotSupported,
    PaymentProviderError,
    TransactionRefRequired,
)
from .models import (
    MOBILE_MONEY_METHODS,
    Payment,
    PaymentMethod,
    PaymentOtp,
    PaymentStatus,
)
from .providers import (
    PAYMENT_FLOW_OTP,
    PAYMENT_FLOW_REDIRECT,
    get_payment_provider,
    mask_phone,
)

logger = logging.getLogger(__name__)

# Sel du HMAC des codes OTP (derive de SECRET_KEY par `salted_hmac`).
OTP_HASH_SALT = "apps.payments.otp"


def _mask_ref(ref: str) -> str:
    """Mask a transaction reference for safe logging.

    Keeps only the last 4 characters visible (cf. security.md §sensitive data).

    Args:
        ref: The raw transaction reference.

    Returns:
        The masked reference (e.g. ``****1234``), or an empty string.
    """
    if not ref:
        return ""
    return f"****{ref[-4:]}" if len(ref) > 4 else "****"


def compute_commission(amount: Decimal, company) -> Decimal:
    """Compute the platform commission for a paid amount.

    Uses the company's ``commission_rate`` when set, otherwise the global rate
    configured by the super admin (`/api/v1/super/settings/commissions/`), which
    itself falls back to ``COMMISSION_RATE_DEFAULT`` (cf. business_rules.md §2).

    Args:
        amount: The booking amount.
        company: The company owning the route, or ``None``.

    Returns:
        The commission, quantised to 2 decimal places.
    """
    # Import local : evite un cycle d'import entre payments et core.
    from apps.core.services import get_global_commission_rate

    rate = getattr(company, "commission_rate", None)
    if rate is None:
        rate = get_global_commission_rate()
    commission = (Decimal(amount) * Decimal(rate)) / Decimal("100")
    return commission.quantize(Decimal("0.01"))


def initiate_payment(booking: Booking, method: str, phone: str = "", agent=None) -> Payment:
    """Create a payment for a booking and start the matching flow.

    Mobile Money payments enter the OTP flow: the provider transaction is
    opened, a one-time code is issued and the payment moves to
    ``otp_required``. Cash stays ``pending`` until the agent confirms it
    (cf. business_rules.md §2).

    Args:
        booking: The booking to pay for.
        method: One of ``PaymentMethod`` values.
        phone: The payer phone number (Mobile Money), optional for cash.
        agent: The agent recording the payment, or ``None`` online.

    Returns:
        The created payment.

    Raises:
        BookingAlreadyPaid: If the booking is already paid.
        ValidationError: If the method is disabled platform-wide.
        PaymentProviderNotConfigured: If no provider handles the method.

    # TODO: accepter aussi un colis (parcels.Parcel) quand le module sera dispo.
    """
    # Import local : evite un cycle d'import entre payments et core.
    from apps.core.services import is_payment_method_enabled

    if booking.status == BookingStatus.PAID:
        raise BookingAlreadyPaid()

    if not is_payment_method_enabled(method):
        raise ValidationError(
            {"method": "Ce moyen de paiement est actuellement desactive."}
        )

    payment = Payment.objects.create(
        booking=booking,
        amount=booking.amount,
        method=method,
        phone=phone or "",
        agent=agent,
        status=PaymentStatus.PENDING,
    )
    logger.info("Paiement %s initie pour le billet %s", payment.pk, booking.ticket_number)

    if method in MOBILE_MONEY_METHODS:
        # Deux parcours possibles selon le fournisseur configure. Le parcours
        # par redirection n'ouvre pas la transaction ici : il lui faut les URL
        # de retour et de notification, que seul l'appelant connait. Il
        # enchaine donc sur start_redirect_flow(), et le paiement reste
        # `pending` d'ici la.
        if get_payment_provider(method).flow == PAYMENT_FLOW_OTP:
            start_otp_flow(payment)
    return payment


# --------------------------------------------------------------------------- #
# Flux Mobile Money par redirection (compte marchand direct)
# --------------------------------------------------------------------------- #
def start_redirect_flow(
    payment: Payment,
    *,
    return_url: str,
    cancel_url: str,
    notify_url: str,
) -> str:
    """Open the operator transaction and return where to send the payer.

    Le pendant de ``start_otp_flow`` pour les operateurs a compte marchand
    direct : le payeur part sur la page de l'operateur, valide avec son code
    PIN, et la confirmation revient par notification serveur.

    Args:
        payment: The freshly created Mobile Money payment.
        return_url: Where the operator sends the browser back on success. Cette
            page n'accorde jamais le paiement : elle affiche une attente et
            interroge notre propre statut.
        cancel_url: Where the operator sends the browser back on abort.
        notify_url: Public webhook URL. Seule source de verite.

    Returns:
        The operator page URL to redirect the payer to.

    Raises:
        PaymentFlowNotSupported: If the provider uses the OTP flow.
        PaymentProviderError: If the operator refuses to open the transaction.
    """
    provider = get_payment_provider(payment.method)
    if provider.flow != PAYMENT_FLOW_REDIRECT:
        raise PaymentFlowNotSupported(
            "Ce moyen de paiement se confirme par code, pas par redirection."
        )

    try:
        redirection = provider.start_redirect(
            payment,
            return_url=return_url,
            cancel_url=cancel_url,
            notify_url=notify_url,
        )
    except NotImplementedError as exc:
        _mark_failed(payment)
        raise PaymentProviderError(str(exc)) from exc

    payment.provider_ref = redirection.provider_ref
    # `otp_required` sert ici d'etat « en attente du payeur ». Le libelle parle
    # de code de confirmation, ce qui est un abus de langage pour un parcours
    # par redirection, mais l'etat couvre la meme realite : de l'argent peut
    # bouger a tout moment, la place ne doit pas etre liberee, et la
    # reconciliation doit surveiller la transaction.
    # TODO(schema): introduire `awaiting_payer` dans PaymentStatus quand les
    # DTO Flutter seront regeneres — la distinction rendra les tableaux de bord
    # plus lisibles.
    payment.status = PaymentStatus.OTP_REQUIRED
    payment.save(update_fields=["provider_ref", "status", "updated_at"])

    logger.info(
        "Paiement %s ouvert chez %s (parcours par redirection)",
        payment.pk,
        provider.name,
    )
    return redirection.redirect_url


# --------------------------------------------------------------------------- #
# Flux Mobile Money par OTP (cf. PROMPT_SUP partie B)
# --------------------------------------------------------------------------- #
def hash_otp_code(code: str) -> str:
    """Hash an OTP code for storage.

    Uses a keyed HMAC derived from ``SECRET_KEY``: a 6-digit code would be
    trivially brute-forced from a plain digest.

    Args:
        code: The clear-text code.

    Returns:
        The hexadecimal HMAC digest.
    """
    return salted_hmac(OTP_HASH_SALT, code, algorithm="sha256").hexdigest()


def start_otp_flow(payment: Payment) -> PaymentOtp:
    """Open the provider transaction and issue the first OTP.

    Args:
        payment: The freshly created Mobile Money payment.

    Returns:
        The issued one-time code row.

    Raises:
        PaymentProviderError: If the provider refuses to open the transaction.
        PaymentProviderNotConfigured: If no provider handles the method.
    """
    provider = get_payment_provider(payment.method)
    try:
        provider_ref = provider.initiate(payment)
    except NotImplementedError as exc:
        # Operateur reel non branche : le paiement echoue proprement.
        _mark_failed(payment)
        raise PaymentProviderError(str(exc)) from exc

    payment.provider_ref = provider_ref or ""
    payment.status = PaymentStatus.OTP_REQUIRED
    payment.save(update_fields=["provider_ref", "status", "updated_at"])
    return _issue_otp(payment, provider)


def _issue_otp(payment: Payment, provider) -> PaymentOtp:
    """Generate, store (hashed) and deliver a one-time code.

    Args:
        payment: The payment awaiting confirmation.
        provider: The resolved payment provider.

    Returns:
        The created ``PaymentOtp``.

    Raises:
        PaymentProviderError: If the provider fails to send the code.
    """
    # Fournisseur maitre de l'OTP : rien a hasher cote plateforme, la ligne ne
    # sert qu'au suivi de l'expiration et des tentatives.
    code = "" if provider.generates_otp else provider.build_otp_code()

    otp = PaymentOtp.objects.create(
        payment=payment,
        code_hash=hash_otp_code(code) if code else "",
        expires_at=timezone.now() + timedelta(minutes=settings.OTP_EXPIRY_MINUTES),
        max_attempts=settings.OTP_MAX_ATTEMPTS,
    )

    try:
        provider.send_otp(payment, code=code)
    except NotImplementedError as exc:
        _mark_failed(payment)
        raise PaymentProviderError(str(exc)) from exc

    # Jamais le code ni le numero complet dans les logs (cf. security.md).
    logger.info(
        "OTP emis pour le paiement %s (%s)", payment.pk, mask_phone(payment.phone)
    )
    return otp


def get_active_otp(payment: Payment) -> PaymentOtp | None:
    """Return the most recent one-time code of a payment.

    Args:
        payment: The payment to inspect.

    Returns:
        The latest ``PaymentOtp``, or ``None`` when the payment has none.
    """
    return payment.otps.order_by("-created_at").first()


def resend_payment_otp(payment: Payment) -> PaymentOtp:
    """Issue a fresh one-time code for a payment.

    Rate limited to one code per ``settings.OTP_RESEND_INTERVAL_SECONDS``. The
    guard is computed from the last code's ``created_at`` rather than the cache
    so that it holds across workers and stays deterministic.

    Args:
        payment: The payment awaiting confirmation.

    Returns:
        The newly issued code.

    Raises:
        OtpNotRequired: If the payment is not waiting for a code.
        OtpResendTooSoon: If a code was issued less than the interval ago.
    """
    if payment.status != PaymentStatus.OTP_REQUIRED:
        raise OtpNotRequired()

    last_otp = get_active_otp(payment)
    if last_otp is not None:
        elapsed = (timezone.now() - last_otp.created_at).total_seconds()
        remaining = settings.OTP_RESEND_INTERVAL_SECONDS - elapsed
        if remaining > 0:
            raise OtpResendTooSoon(
                f"Patientez {int(remaining) + 1} seconde(s) avant de demander "
                "un nouveau code."
            )

    provider = get_payment_provider(payment.method)
    return _issue_otp(payment, provider)


def _check_otp_attempt(payment: Payment, code: str):
    """Validate one OTP attempt and record its consequences.

    Runs under a row lock on the code: the ``attempts`` counter is the only
    protection against brute-forcing a 6-digit code. Returns the exception to
    raise instead of raising it, so the caller raises it outside the
    transaction — raising inside would roll back the very counter increment (and
    the failed status) this function just persisted.

    Args:
        payment: The payment awaiting confirmation.
        code: The code entered by the payer.

    Returns:
        The exception to raise, or ``None`` when the code checks out.
    """
    with transaction.atomic():
        otp = payment.otps.select_for_update().order_by("-created_at").first()
        if otp is None:
            return OtpNotRequired()

        if otp.attempts >= otp.max_attempts:
            _mark_failed(payment)
            return OtpMaxAttemptsReached()

        if otp.expires_at <= timezone.now():
            _mark_failed(payment)
            return OtpExpired()

        # Verification locale : seulement quand la plateforme detient le hash.
        # Avec un operateur maitre de l'OTP, elle est deleguee a confirm_otp.
        if not otp.code_hash:
            return None
        if constant_time_compare(otp.code_hash, hash_otp_code(code)):
            return None

        otp.attempts += 1
        otp.save(update_fields=["attempts", "updated_at"])
        if otp.attempts_remaining == 0:
            _mark_failed(payment)
            return OtpMaxAttemptsReached()
        return OtpInvalid(otp.attempts_remaining)


def verify_payment_otp(payment: Payment, code: str) -> Payment:
    """Confirm a Mobile Money payment with the code entered by the payer.

    Increments the attempt counter on every wrong code; the payment fails once
    the code has expired or the attempts are exhausted. On success the provider
    debits the payer and returns the ``transaction_ref`` kept for reconciliation.

    Args:
        payment: The payment awaiting confirmation.
        code: The code entered by the payer.

    Returns:
        The paid payment.

    Raises:
        OtpNotRequired: If the payment is not waiting for a code.
        OtpExpired: If the code has expired.
        OtpMaxAttemptsReached: If the attempts are exhausted.
        PaymentProviderError: If the provider refuses the payment.
        ValidationError: If the code is wrong (with the remaining attempts).
    """
    if payment.status == PaymentStatus.PAID:
        raise PaymentAlreadyConfirmed()
    if payment.status != PaymentStatus.OTP_REQUIRED:
        raise OtpNotRequired()

    # L'erreur est levee APRES la transaction : la lever a l'interieur
    # annulerait l'increment de `attempts` et le passage en echec.
    error = _check_otp_attempt(payment, code)
    if error is not None:
        raise error

    provider = get_payment_provider(payment.method)
    try:
        confirmation = provider.confirm_otp(payment, code)
    except NotImplementedError as exc:
        _mark_failed(payment)
        raise PaymentProviderError(str(exc)) from exc

    otp = get_active_otp(payment)

    if not confirmation.success:
        # Refus operateur : le code etait bon, le paiement echoue quand meme.
        _mark_failed(payment)
        raise PaymentProviderError(
            confirmation.message or PaymentProviderError.default_detail
        )

    if otp is not None:
        otp.is_used = True
        otp.save(update_fields=["is_used", "updated_at"])
    # Reference de reconciliation : celle de l'operateur, a defaut celle de la
    # transaction ouverte a l'initiation.
    return confirm_payment(
        payment,
        transaction_ref=confirmation.transaction_ref or payment.provider_ref,
    )


def _mark_failed(payment: Payment) -> None:
    """Mark a payment as failed.

    Args:
        payment: The payment to fail.
    """
    if payment.status == PaymentStatus.FAILED:
        return
    payment.status = PaymentStatus.FAILED
    payment.save(update_fields=["status", "updated_at"])
    logger.info("Paiement %s passe en echec", payment.pk)


def confirm_payment(payment: Payment, transaction_ref: str = "") -> Payment:
    """Confirm a payment and mark its booking as paid.

    For Mobile Money / card the ``transaction_ref`` supplied by the agent is
    mandatory. The seat is already reserved at booking creation
    (cf. apps.bookings.services.create_booking, which decrements
    ``trip.available_seats`` under a row lock), so confirmation only flips the
    booking status to ``paid`` and freezes the platform commission.

    Args:
        payment: The pending payment to confirm.
        transaction_ref: The Mobile Money / card transaction reference.

    Returns:
        The updated payment.

    Raises:
        PaymentAlreadyConfirmed: If the payment is already paid.
        TransactionRefRequired: If a non-cash payment lacks a transaction ref.
    """
    if payment.status == PaymentStatus.PAID:
        raise PaymentAlreadyConfirmed()

    if payment.method != PaymentMethod.CASH and not transaction_ref:
        raise TransactionRefRequired()

    with transaction.atomic():
        # Verrou ligne sur le paiement : serialise une double confirmation.
        payment = Payment.objects.select_for_update().get(pk=payment.pk)
        if payment.status == PaymentStatus.PAID:
            raise PaymentAlreadyConfirmed()

        booking = payment.booking
        if booking is not None:
            company = booking.trip.route.company
            payment.commission = compute_commission(payment.amount, company)
            # La reservation passe a paye (le siege est deja reserve a la creation).
            booking.status = BookingStatus.PAID
            booking.payment_method = payment.method
            booking.save(update_fields=["status", "payment_method", "updated_at"])

        payment.transaction_ref = transaction_ref
        payment.status = PaymentStatus.PAID
        payment.paid_at = timezone.now()
        payment.receipt_url = f"/api/v1/payments/{payment.pk}/receipt/"
        payment.save(
            update_fields=[
                "transaction_ref",
                "status",
                "paid_at",
                "receipt_url",
                "commission",
                "updated_at",
            ]
        )

    logger.info(
        "Paiement %s confirme (ref %s)", payment.pk, _mask_ref(transaction_ref)
    )
    _send_payment_sms(payment)
    if booking is not None:
        _schedule_booking_notifications(booking)
    return payment


# Delai avant le depart pour l'envoi du SMS de rappel (cf. PROMPT 12).
REMINDER_HOURS_BEFORE = 3


def _schedule_booking_notifications(booking) -> None:
    """Trigger the confirmation SMS and schedule the departure reminder.

    Sends the booking confirmation asynchronously and books the departure
    reminder for ~3h before the trip via ``apply_async(eta=...)`` (skipped when
    the trip already departs within that window).

    Args:
        booking: The paid booking to notify.
    """
    # Import local : evite un cycle d'import bookings <-> payments au chargement.
    from datetime import timedelta

    from apps.bookings.tasks import (
        send_booking_confirmation_sms,
        send_departure_reminder_sms,
    )

    send_booking_confirmation_sms.delay(booking.pk)

    reminder_eta = booking.trip.departure_time - timedelta(hours=REMINDER_HOURS_BEFORE)
    if reminder_eta > timezone.now():
        send_departure_reminder_sms.apply_async(args=[booking.pk], eta=reminder_eta)


def _send_payment_sms(payment: Payment) -> None:
    """Send the payment confirmation SMS to the passenger.

    Args:
        payment: The confirmed payment.
    """
    booking = payment.booking
    if booking is None:
        return
    message = (
        f"Paiement confirme. Billet {booking.ticket_number}, "
        f"montant {payment.amount} FCFA. Bon voyage."
    )
    send_sms(booking.phone, message)


def generate_receipt_pdf(payment: Payment) -> bytes:
    """Render a payment receipt as a PDF document.

    Contains the transaction number, amount, date, company, trip, passenger and
    the booking QR code (cf. business_rules.md §2).

    Args:
        payment: The payment to render.

    Returns:
        The PDF file content as bytes.
    """
    # Import local : ReportLab n'est requis que pour la generation PDF.
    import base64

    from reportlab.lib.pagesizes import A6
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    width, height = A6
    pdf = canvas.Canvas(buffer, pagesize=A6)

    booking = payment.booking

    pdf.setFont("Helvetica-Bold", 14)
    pdf.drawString(15 * mm, height - 18 * mm, "TransBooking BF - Recu")
    pdf.setFont("Helvetica", 9)
    pdf.drawString(15 * mm, height - 24 * mm, f"Recu N : PAY{payment.pk:06d}")

    lines = [
        f"Date : {timezone.localtime(payment.paid_at or payment.created_at):%d/%m/%Y %Hh%M}",
        f"Montant : {payment.amount} FCFA",
        f"Moyen : {payment.get_method_display()}",
        f"Reference : {payment.transaction_ref or '-'}",
    ]
    if booking is not None:
        route = booking.trip.route
        lines.extend(
            [
                f"Compagnie : {route.company.name}",
                f"Trajet : {route.origin_city.name} -> {route.destination_city.name}",
                f"Passager : {booking.passenger_name}",
                f"Billet : {booking.ticket_number}",
            ]
        )

    y = height - 32 * mm
    pdf.setFont("Helvetica", 9)
    for line in lines:
        pdf.drawString(15 * mm, y, line)
        y -= 6 * mm

    if booking is not None and booking.qr_code:
        try:
            qr_image = ImageReader(BytesIO(base64.b64decode(booking.qr_code)))
            pdf.drawImage(
                qr_image,
                width - 40 * mm,
                12 * mm,
                width=25 * mm,
                height=25 * mm,
            )
        except Exception:
            # Un QR illisible ne doit pas casser la generation du recu.
            pass

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
