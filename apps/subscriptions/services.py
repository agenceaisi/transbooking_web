from datetime import date
from decimal import Decimal
from io import BytesIO

from dateutil.relativedelta import relativedelta
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.services import log_activity

from .models import Subscription, SubscriptionInvoice, SubscriptionStatus


def get_current_subscription(company, today: date | None = None) -> Subscription | None:
    """Return the subscription currently covering a company, if any.

    The current plan is the active subscription whose period has not lapsed
    yet; the latest ``end_date`` wins when several overlap.

    Args:
        company: The company to inspect.
        today: Reference date (defaults to the local current date).

    Returns:
        The covering subscription, or ``None`` when the company has none.
    """
    today = today or timezone.localdate()
    return (
        Subscription.objects.filter(
            company=company,
            status=SubscriptionStatus.ACTIVE,
            end_date__gte=today,
        )
        .select_related("plan")
        .order_by("-end_date")
        .first()
    )


def has_blocking_subscription(company, today: date | None = None) -> bool:
    """Tell whether a company must be treated as suspended (expired plan).

    A company that never subscribed keeps operating (historical accounts, and
    plans are assigned by the super admin). Once it has at least one
    subscription, it must keep a valid one (cf. PROMPT_SUP A3).

    Args:
        company: The company to inspect.
        today: Reference date (defaults to the local current date).

    Returns:
        ``True`` when the company subscribed at least once and no subscription
        currently covers it.
    """
    if company is None:
        return False
    if not Subscription.objects.filter(company=company).exists():
        return False
    return get_current_subscription(company, today) is None


def create_subscription(data: dict, actor=None) -> Subscription:
    """Assign a plan to a company and issue the matching invoice.

    ``start_date`` defaults to today and ``end_date`` to ``start_date`` plus the
    plan duration.

    Args:
        data: Validated payload with ``company``, ``plan`` and the optional
            ``start_date``, ``end_date`` and ``auto_renew`` keys.
        actor: The super admin assigning the plan (audit trail).

    Returns:
        The created subscription.

    Raises:
        ValidationError: If the company already has a running subscription or if
            ``end_date`` precedes ``start_date``.
    """
    company = data["company"]
    plan = data["plan"]
    start_date = data.get("start_date") or timezone.localdate()
    end_date = data.get("end_date") or start_date + relativedelta(
        months=plan.duration_months
    )

    if end_date < start_date:
        raise ValidationError(
            {"end_date": "La date de fin doit suivre la date de debut."}
        )
    if get_current_subscription(company) is not None:
        raise ValidationError(
            {"company": "Cette compagnie a deja un abonnement en cours."}
        )

    subscription = Subscription.objects.create(
        company=company,
        plan=plan,
        start_date=start_date,
        end_date=end_date,
        auto_renew=data.get("auto_renew", False),
        status=SubscriptionStatus.ACTIVE,
    )
    create_invoice(subscription)
    log_activity(
        actor,
        action="subscription.create",
        entity_type="subscription",
        entity_id=subscription.id,
        details={
            "company_id": company.id,
            "plan": plan.name,
            "end_date": str(subscription.end_date),
        },
    )
    return subscription


def create_invoice(subscription: Subscription, amount: Decimal | None = None):
    """Issue an invoice for a subscription cycle.

    Args:
        subscription: The billed subscription.
        amount: Billed amount (defaults to the plan price).

    Returns:
        The created invoice.
    """
    return SubscriptionInvoice.objects.create(
        subscription=subscription,
        amount=subscription.plan.price if amount is None else amount,
    )


def renew_subscription(
    subscription: Subscription, today: date | None = None, actor=None
) -> Subscription:
    """Extend a subscription by its plan duration from its current end date.

    Resets the expiry reminder flag so the next cycle can warn again and issues
    the invoice of the new cycle. Kept idempotent at the caller level: only
    auto-renewable, expired subscriptions should be passed in.

    Args:
        subscription: The subscription to renew.
        today: Reference date (defaults to the local current date). Used as the
            new start date when the previous period already lapsed.
        actor: The super admin renewing the plan, ``None`` for the automatic
            renewal task (audit trail).

    Returns:
        The renewed subscription.
    """
    today = today or timezone.localdate()
    duration = relativedelta(months=subscription.plan.duration_months)
    # On repart de la borne la plus tardive pour ne pas perdre de jours.
    base = max(subscription.end_date, today)
    subscription.start_date = today
    subscription.end_date = base + duration
    subscription.status = SubscriptionStatus.ACTIVE
    subscription.expiry_reminder_sent = False
    subscription.save(
        update_fields=[
            "start_date",
            "end_date",
            "status",
            "expiry_reminder_sent",
            "updated_at",
        ]
    )
    # Chaque cycle renouvele donne lieu a une nouvelle facture.
    create_invoice(subscription)
    log_activity(
        actor,
        action="subscription.renew",
        entity_type="subscription",
        entity_id=subscription.id,
        details={"end_date": str(subscription.end_date)},
    )
    return subscription


def expire_subscription(subscription: Subscription) -> Subscription:
    """Mark a subscription as expired (no auto-renewal).

    The caller is responsible for suspending the company; this only flips the
    subscription status so a re-run does not reprocess it.

    Args:
        subscription: The subscription to expire.

    Returns:
        The expired subscription.
    """
    subscription.status = SubscriptionStatus.EXPIRED
    subscription.save(update_fields=["status", "updated_at"])
    return subscription


def invoice_reference(invoice: SubscriptionInvoice) -> str:
    """Build the human-readable reference of an invoice.

    Args:
        invoice: The invoice to reference.

    Returns:
        A reference such as ``FACT-2026-000012``.
    """
    return f"FACT-{invoice.created_at:%Y}-{invoice.pk:06d}"


def generate_invoice_pdf(invoice: SubscriptionInvoice) -> bytes:
    """Render a subscription invoice as a PDF document.

    The stored file is served when present; otherwise the PDF is rendered on the
    fly from the invoice data (no file is written).

    Args:
        invoice: The invoice to render.

    Returns:
        The PDF file content as bytes.
    """
    if invoice.pdf:
        try:
            with invoice.pdf.open("rb") as stored:
                return stored.read()
        except (FileNotFoundError, ValueError):
            # Fichier absent du stockage : on regenere a la volee.
            pass

    # Import local : ReportLab n'est requis que pour la generation PDF.
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas

    subscription = invoice.subscription
    company = subscription.company
    buffer = BytesIO()
    _, height = A4
    pdf = canvas.Canvas(buffer, pagesize=A4)

    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(20 * mm, height - 25 * mm, "TransBooking BF")
    pdf.setFont("Helvetica-Bold", 12)
    pdf.drawString(20 * mm, height - 35 * mm, f"Facture {invoice_reference(invoice)}")

    lines = [
        f"Compagnie : {company.name}",
        f"Forfait : {subscription.plan.name}",
        f"Periode : du {subscription.start_date:%d/%m/%Y} au {subscription.end_date:%d/%m/%Y}",
        f"Montant : {invoice.amount} FCFA",
        f"Emise le : {timezone.localtime(invoice.created_at):%d/%m/%Y}",
        (
            f"Reglee le : {timezone.localtime(invoice.paid_at):%d/%m/%Y}"
            if invoice.paid_at
            else "Statut : en attente de reglement"
        ),
    ]
    pdf.setFont("Helvetica", 10)
    y = height - 50 * mm
    for line in lines:
        pdf.drawString(20 * mm, y, line)
        y -= 7 * mm

    pdf.showPage()
    pdf.save()
    return buffer.getvalue()
