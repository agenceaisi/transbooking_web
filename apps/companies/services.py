from django.core.exceptions import ValidationError
from django.db.models import Count, F, Q

from apps.core.services import log_activity
from apps.notifications.models import NotificationType
from apps.notifications.services import notify
from utils.sms import send_sms

from .models import OPEN_REQUEST_STATUSES, Company, CompanyStatus


def create_company_request(data: dict) -> Company:
    """Create a public company registration request.

    The request is stored as a company in the ``pending`` state: no active
    company and no ``company_admin`` account are created until a super admin
    approves it (cf. ``approve_company``).

    Args:
        data: Validated payload with ``company_name``, ``manager_name``,
            ``phone``, ``email``, ``city`` and an optional ``documents`` file.

    Returns:
        The created pending company request.

    Raises:
        ValidationError: If a company already uses the requested name.
    """
    name = (data.get("company_name") or "").strip()
    if Company.objects.filter(name__iexact=name).exists():
        raise ValidationError({"company_name": "Une compagnie porte deja ce nom."})

    phone = (data.get("phone") or "").strip()
    company = Company.objects.create(
        name=name,
        responsible_name=(data.get("manager_name") or "").strip(),
        responsible_phone=phone,
        phone=phone,
        email=(data.get("email") or "").strip(),
        city=(data.get("city") or "").strip(),
        documents=data.get("documents") or None,
        status=CompanyStatus.PENDING,
    )

    if company.responsible_phone:
        send_sms(
            company.responsible_phone,
            f"Votre demande d'inscription TransBooking BF pour {company.name} "
            "a bien ete enregistree. Elle sera examinee par notre equipe.",
        )
    return company


def request_company_info(company: Company, message: str, actor=None) -> Company:
    """Ask a company applicant for additional information.

    Moves an open registration request to ``info_requested``, stores the super
    admin message and notifies the applicant by SMS (plus an in-app
    notification when an admin account already exists).

    Args:
        company: The open registration request.
        message: Information requested from the applicant (stored and sent).
        actor: The super admin performing the action (audit trail).

    Returns:
        The updated company request.

    Raises:
        ValidationError: If the request is closed or the message is empty.
    """
    if company.status not in OPEN_REQUEST_STATUSES:
        raise ValidationError(
            "Seules les demandes en cours d'instruction peuvent faire l'objet "
            "d'une demande d'informations."
        )
    if not message or not message.strip():
        raise ValidationError({"message": "Le message est obligatoire."})

    company.status = CompanyStatus.INFO_REQUESTED
    company.info_request_message = message.strip()
    company.save(update_fields=["status", "info_request_message", "updated_at"])

    log_activity(
        actor,
        action="company.request_info",
        entity_type="company",
        entity_id=company.id,
        details={"message": company.info_request_message},
    )
    _notify_applicant(
        company,
        title="Informations complementaires demandees",
        body=(
            f"Votre demande TransBooking BF pour {company.name} necessite des "
            f"informations complementaires : {company.info_request_message}"
        ),
    )
    return company


def _notify_applicant(company: Company, title: str, body: str) -> None:
    """Notify a company applicant by SMS and, when possible, in-app.

    A registration request has no user account until it is approved, so the SMS
    sent to the legal representative is the primary channel. The in-app
    notification is only created when the company already has an admin account.

    Args:
        company: The company whose applicant must be notified.
        title: Headline of the in-app notification.
        body: Message body, reused as the SMS content.
    """
    if company.responsible_phone:
        send_sms(company.responsible_phone, body)

    if company.admin_user_id:
        notify(
            user_id=company.admin_user_id,
            type=NotificationType.SYSTEM,
            title=title,
            body=body,
            reference_id=company.id,
            reference_type="company",
        )


def approve_company(company: Company, actor=None) -> Company:
    """Approve an open company registration request.

    Sets the company status to active and sends a welcome SMS to the
    legal representative.

    Args:
        company: The pending (or info_requested) company to approve.
        actor: The super admin performing the action (audit trail).

    Returns:
        The approved company.

    Raises:
        ValidationError: If the request is no longer open.
    """
    if company.status not in OPEN_REQUEST_STATUSES:
        raise ValidationError("Seules les demandes en attente peuvent etre approuvees.")

    company.status = CompanyStatus.ACTIVE
    company.rejection_reason = ""
    company.info_request_message = ""
    company.save(
        update_fields=["status", "rejection_reason", "info_request_message", "updated_at"]
    )

    log_activity(
        actor,
        action="company.approve",
        entity_type="company",
        entity_id=company.id,
    )
    if company.responsible_phone:
        send_sms(
            company.responsible_phone,
            f"Bienvenue sur TransBooking BF ! La compagnie {company.name} est activee.",
        )
    return company


def reject_company(company: Company, reason: str, actor=None) -> Company:
    """Reject a pending company registration request.

    Args:
        company: The pending (or info_requested) company to reject.
        reason: Human-readable rejection reason (stored and sent by SMS).
        actor: The super admin performing the action (audit trail).

    Returns:
        The rejected company.

    Raises:
        ValidationError: If the request is closed or the reason is empty.
    """
    if company.status not in OPEN_REQUEST_STATUSES:
        raise ValidationError("Seules les demandes en attente peuvent etre rejetees.")
    if not reason or not reason.strip():
        raise ValidationError({"reason": "Le motif de rejet est obligatoire."})

    company.status = CompanyStatus.REJECTED
    company.rejection_reason = reason.strip()
    company.save(update_fields=["status", "rejection_reason", "updated_at"])

    log_activity(
        actor,
        action="company.reject",
        entity_type="company",
        entity_id=company.id,
        details={"reason": company.rejection_reason},
    )
    if company.responsible_phone:
        send_sms(
            company.responsible_phone,
            f"Votre demande TransBooking BF pour {company.name} a ete rejetee : {reason.strip()}",
        )
    return company


def activate_company(company: Company, actor=None) -> Company:
    """Reactivate a suspended (or pending) company.

    Args:
        company: The company to activate.
        actor: The super admin performing the action (audit trail).

    Returns:
        The activated company.

    Raises:
        ValidationError: If the company is already active.
    """
    if company.status == CompanyStatus.ACTIVE:
        raise ValidationError("La compagnie est deja active.")

    company.status = CompanyStatus.ACTIVE
    company.suspension_reason = ""
    company.save(update_fields=["status", "suspension_reason", "updated_at"])

    log_activity(
        actor,
        action="company.activate",
        entity_type="company",
        entity_id=company.id,
    )
    if company.responsible_phone:
        send_sms(
            company.responsible_phone,
            f"La compagnie {company.name} a ete reactivee sur TransBooking BF.",
        )
    return company


def suspend_company(company: Company, reason: str, actor=None) -> Company:
    """Suspend an active company and notify its representative.

    Args:
        company: The company to suspend.
        reason: Human-readable suspension reason (stored and sent by SMS).
        actor: The super admin performing the action, ``None`` for the system
            (expired subscription) — audit trail.

    Returns:
        The suspended company.

    Raises:
        ValidationError: If the reason is empty.
    """
    if not reason or not reason.strip():
        raise ValidationError({"reason": "Le motif de suspension est obligatoire."})

    company.status = CompanyStatus.SUSPENDED
    company.suspension_reason = reason.strip()
    company.save(update_fields=["status", "suspension_reason", "updated_at"])

    log_activity(
        actor,
        action="company.suspend",
        entity_type="company",
        entity_id=company.id,
        details={"reason": company.suspension_reason},
    )
    if company.responsible_phone:
        send_sms(
            company.responsible_phone,
            f"La compagnie {company.name} a ete suspendue : {reason.strip()}",
        )
    return company


def public_company_directory(limit: int | None = None) -> list[Company]:
    """List active companies for public display, with their rating and reach.

    Chaque compagnie porte trois annotations calculees ici : ``rating``
    (moyenne des avis publics non signales, cf. reviews.services), ``reviews_count``
    et ``routes_count`` (nombre de trajets actifs). Les compagnies sans aucun
    avis restent affichees mais passent en fin de liste — un avis absent ne
    doit pas se lire comme une mauvaise note.

    Args:
        limit: Maximum number of companies returned. ``None`` returns them all.

    Returns:
        Active companies ordered by rating, then by review count, then by name.
    """
    # Import local pour eviter un cycle companies.services <-> reviews.services.
    from apps.reviews.services import company_rating_subquery

    queryset = (
        Company.objects.filter(status=CompanyStatus.ACTIVE)
        .annotate(
            rating=company_rating_subquery("id"),
            reviews_count=Count(
                "reviews", filter=Q(reviews__is_flagged=False), distinct=True
            ),
            routes_count=Count("routes", distinct=True),
        )
        .order_by(F("rating").desc(nulls_last=True), "-reviews_count", "name")
    )
    return list(queryset[:limit]) if limit else list(queryset)
