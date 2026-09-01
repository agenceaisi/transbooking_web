from datetime import timedelta

from django.db.models import (
    Avg,
    BooleanField,
    Case,
    DurationField,
    ExpressionWrapper,
    F,
    QuerySet,
    When,
)
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from .models import UNRESOLVED_STATUSES, Claim, ClaimAttachment, ClaimStatus

# Delai au-dela duquel une reclamation non traitee est consideree en retard.
OVERDUE_AFTER = timedelta(hours=48)


def create_claim(data: dict, user) -> Claim:
    """Create a claim filed by a traveler, deducing the company when needed.

    Mirrors the validation of ``ClaimCreateSerializer`` so the server-rendered
    web view (which calls this directly, never the HTTP API) carries no
    business logic of its own.

    Args:
        data: Cleaned fields. Recognised keys: ``booking`` (optional),
            ``company`` (required only when ``booking`` is absent),
            ``claim_type``, ``subject``, ``description``, ``travel_date``
            (optional).
        user: The traveler filing the claim.

    Returns:
        The created claim.

    Raises:
        ValidationError: If neither a booking nor a company is given, or the
            booking does not belong to ``user``.
    """
    booking = data.get("booking")
    company = data.get("company")

    if booking is not None:
        if booking.user_id != user.id:
            raise ValidationError({"booking": "Cette reservation ne vous appartient pas."})
        company = booking.trip.route.company
    elif company is None:
        raise ValidationError({"company": "La compagnie ou une reservation est obligatoire."})

    return Claim.objects.create(
        company=company,
        user=user,
        booking=booking,
        claim_type=data["claim_type"],
        subject=data["subject"],
        description=data["description"],
        travel_date=data.get("travel_date"),
    )


def accept_claim_response(claim: Claim, user) -> Claim:
    """Record the traveler's acceptance of a company's claim response.

    Args:
        claim: The claim being accepted.
        user: The traveler accepting the response.

    Returns:
        The updated claim, moved to ``resolved``.

    Raises:
        ValidationError: If the claim does not belong to ``user``, carries no
            response yet, or is not currently ``in_progress``.
    """
    if claim.user_id != user.id:
        raise ValidationError("Cette reclamation ne vous appartient pas.")
    if not claim.response or claim.status != ClaimStatus.IN_PROGRESS:
        raise ValidationError(
            "Cette reclamation n'a pas de proposition en attente d'acceptation."
        )

    claim.traveler_accepted_at = timezone.now()
    claim.status = ClaimStatus.RESOLVED
    claim.save(update_fields=["traveler_accepted_at", "status", "updated_at"])
    return claim


def add_claim_attachment(claim: Claim, uploaded_file) -> ClaimAttachment:
    """Attach an uploaded file to a claim, freezing its metadata.

    Size and content-type validation is enforced upstream by the serializer
    (``validate_claim_attachment``): 10 MB max, PDF or image only.

    Args:
        claim: The claim to attach the file to.
        uploaded_file: The validated uploaded file.

    Returns:
        The created ``ClaimAttachment``.
    """
    return ClaimAttachment.objects.create(
        claim=claim,
        file=uploaded_file,
        original_name=(getattr(uploaded_file, "name", "") or "")[:255],
        content_type=getattr(uploaded_file, "content_type", "") or "",
        size=uploaded_file.size,
    )


def annotated_claims(queryset: QuerySet | None = None) -> QuerySet:
    """Annotate claims with ``is_overdue`` (cf. business_rules.md §5).

    A claim is overdue when it is still in a ``submitted`` state and was created
    more than 48 hours ago. The flag is computed at query time, never stored.

    Args:
        queryset: Base queryset to annotate. Defaults to all claims.

    Returns:
        The annotated queryset.
    """
    queryset = Claim.objects.all() if queryset is None else queryset
    return queryset.annotate(
        is_overdue=Case(
            When(
                status=ClaimStatus.SUBMITTED,
                created_at__lt=timezone.now() - OVERDUE_AFTER,
                then=True,
            ),
            default=False,
            output_field=BooleanField(),
        )
    )


def unresolved_first(queryset: QuerySet) -> QuerySet:
    """Order claims so unresolved ones come first, newest within each group.

    Args:
        queryset: The claims queryset to order.

    Returns:
        The ordered queryset.
    """
    return queryset.annotate(
        _unresolved=Case(
            When(status__in=UNRESOLVED_STATUSES, then=0),
            default=1,
            output_field=BooleanField(),
        )
    ).order_by("_unresolved", "-created_at")


def respond_to_claim(claim: Claim, response: str, status: str, responder) -> Claim:
    """Record a company response to a claim and update its status.

    Args:
        claim: The claim being answered.
        response: The textual response shown to the traveller.
        status: The new claim status (must be a resolution status).
        responder: The company admin user answering.

    Returns:
        The updated claim.

    Raises:
        ValidationError: If ``status`` is not a valid resolution status.
    """
    allowed = {ClaimStatus.IN_PROGRESS, ClaimStatus.RESOLVED, ClaimStatus.CLOSED}
    if status not in allowed:
        raise ValidationError({"status": "Statut de reponse invalide."})

    claim.response = response
    claim.status = status
    claim.responded_by = responder
    claim.responded_at = timezone.now()
    claim.save(
        update_fields=["response", "status", "responded_by", "responded_at", "updated_at"]
    )
    return claim


def escalate_claim(claim: Claim) -> Claim:
    """Escalate a claim to push the company to handle it (super admin action).

    Args:
        claim: The claim to escalate.

    Returns:
        The updated claim.
    """
    claim.status = ClaimStatus.ESCALATED
    claim.save(update_fields=["status", "updated_at"])
    return claim


def close_claim(claim: Claim) -> Claim:
    """Close a claim directly (super admin action).

    Args:
        claim: The claim to close.

    Returns:
        The updated claim.
    """
    claim.status = ClaimStatus.CLOSED
    if claim.responded_at is None:
        claim.responded_at = timezone.now()
        claim.save(update_fields=["status", "responded_at", "updated_at"])
    else:
        claim.save(update_fields=["status", "updated_at"])
    return claim


def claim_stats(queryset: QuerySet) -> dict:
    """Compute resolution statistics for a set of claims.

    Args:
        queryset: The claims to aggregate (already scoped to a company).

    Returns:
        A dict with ``total``, ``resolved``, ``resolution_rate`` (percentage)
        and ``avg_response_hours`` (average hours between creation and response).
    """
    total = queryset.count()
    resolved = queryset.filter(
        status__in=[ClaimStatus.RESOLVED, ClaimStatus.CLOSED]
    ).count()

    response_delay = ExpressionWrapper(
        F("responded_at") - F("created_at"), output_field=DurationField()
    )
    avg_delay = (
        queryset.filter(responded_at__isnull=False)
        .annotate(_delay=response_delay)
        .aggregate(avg=Avg("_delay"))
        .get("avg")
    )
    avg_response_hours = (
        round(avg_delay.total_seconds() / 3600, 2) if avg_delay else None
    )

    return {
        "total": total,
        "resolved": resolved,
        "resolution_rate": round(resolved / total * 100, 2) if total else 0.0,
        "avg_response_hours": avg_response_hours,
    }
