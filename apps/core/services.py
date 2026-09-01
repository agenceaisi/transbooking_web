"""Acces typé aux parametres globaux de la plateforme (`core.GlobalSetting`).

Les valeurs sont stockees en texte dans une table cle/valeur ; ce module
centralise leur lecture/ecriture et leur conversion (bool, Decimal, JSON) pour
que les autres apps n'aient jamais a parser la valeur brute.
"""
import json
from decimal import Decimal, InvalidOperation

from django.conf import settings

from apps.companies.models import PaymentMethodChoice

from .models import ActivityLog, GlobalSetting

# Cles des parametres generaux exposes par /api/v1/super/settings/ (cf. mcd.md §15).
SETTING_PLATFORM_NAME = "platform_name"
SETTING_SUPPORT_PHONE = "support_phone"
SETTING_SUPPORT_EMAIL = "support_email"
SETTING_MAINTENANCE_MODE = "platform_maintenance_mode"
SETTING_GLOBAL_COMMISSION_RATE = "global_commission_rate"
SETTING_PAYMENT_METHODS = "payment_methods_enabled"

# Valeurs par defaut appliquees tant que le super admin n'a rien enregistre.
DEFAULT_SETTINGS = {
    SETTING_PLATFORM_NAME: "TransBooking BF",
    SETTING_SUPPORT_PHONE: "",
    SETTING_SUPPORT_EMAIL: "",
    SETTING_MAINTENANCE_MODE: "false",
}

# Moyens de paiement pilotables au niveau plateforme. Les especes (`cash`) sont
# toujours disponibles : elles n'impliquent aucun operateur externe.
PLATFORM_PAYMENT_METHODS = [
    PaymentMethodChoice.ORANGE_MONEY,
    PaymentMethodChoice.MOOV_MONEY,
    PaymentMethodChoice.CORIS_MONEY,
    PaymentMethodChoice.TELECEL_MONEY,
    PaymentMethodChoice.CARD,
]

_TRUE_VALUES = {"true", "1", "yes", "oui", "on"}


def log_activity(
    actor,
    action: str,
    entity_type: str = "",
    entity_id: int | None = None,
    details: dict | None = None,
    ip_address: str | None = None,
) -> ActivityLog:
    """Record a sensitive action in the platform audit trail.

    Single entry point for the audit journal exposed by
    ``GET /api/v1/super/activity-logs/``. ``actor=None`` marks a system action
    (Celery task, cron).

    Args:
        actor: The user performing the action, or ``None`` for the system.
        action: Short action code (e.g. ``"company.approve"``).
        entity_type: Label of the impacted object (e.g. ``"company"``).
        entity_id: Primary key of the impacted object.
        details: Optional JSON snapshot (before/after, reason...). Never store
            credentials, OTP codes or full transaction references here.
        ip_address: Optional client IP address.

    Returns:
        The created audit entry.
    """
    return ActivityLog.objects.create(
        user=actor if getattr(actor, "pk", None) else None,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        details=details,
        ip_address=ip_address,
    )


def get_setting(key: str, default: str | None = None) -> str | None:
    """Read a raw global setting value.

    Args:
        key: The setting key.
        default: Value returned when the key is not stored yet. Falls back to
            ``DEFAULT_SETTINGS`` when omitted.

    Returns:
        The stored value, or the default.
    """
    row = GlobalSetting.objects.filter(key=key).first()
    if row is not None:
        return row.value
    return DEFAULT_SETTINGS.get(key) if default is None else default


def set_setting(key: str, value: str, description: str = "") -> GlobalSetting:
    """Create or update a global setting.

    Args:
        key: The setting key.
        value: The value to store (serialised as text).
        description: Optional human-readable description.

    Returns:
        The stored setting row.
    """
    defaults = {"value": value}
    if description:
        defaults["description"] = description
    row, _ = GlobalSetting.objects.update_or_create(key=key, defaults=defaults)
    return row


def get_bool_setting(key: str) -> bool:
    """Read a boolean global setting.

    Args:
        key: The setting key.

    Returns:
        ``True`` when the stored value is a truthy token.
    """
    return (get_setting(key) or "").strip().lower() in _TRUE_VALUES


def get_general_settings() -> dict:
    """Return the platform-wide general settings.

    ``sms_provider`` is read from the deployment settings (env) and stays
    read-only: the SMS credentials never transit through the API.

    Returns:
        The general settings payload.
    """
    return {
        "platform_name": get_setting(SETTING_PLATFORM_NAME),
        "support_phone": get_setting(SETTING_SUPPORT_PHONE),
        "support_email": get_setting(SETTING_SUPPORT_EMAIL),
        "maintenance_mode": get_bool_setting(SETTING_MAINTENANCE_MODE),
        "sms_provider": settings.SMS_PROVIDER,
    }


def update_general_settings(data: dict) -> dict:
    """Persist a partial update of the general settings.

    Args:
        data: Validated subset of ``platform_name``, ``support_phone``,
            ``support_email`` and ``maintenance_mode``.

    Returns:
        The refreshed general settings payload.
    """
    text_keys = {
        "platform_name": SETTING_PLATFORM_NAME,
        "support_phone": SETTING_SUPPORT_PHONE,
        "support_email": SETTING_SUPPORT_EMAIL,
    }
    for field, key in text_keys.items():
        if field in data:
            set_setting(key, data[field] or "")

    if "maintenance_mode" in data:
        set_setting(
            SETTING_MAINTENANCE_MODE,
            "true" if data["maintenance_mode"] else "false",
        )
    return get_general_settings()


def get_global_commission_rate() -> Decimal:
    """Return the platform commission rate applied when a company has none.

    Falls back to the ``COMMISSION_RATE_DEFAULT`` deployment setting while the
    super admin has not overridden it (cf. business_rules.md §2).

    Returns:
        The global commission rate, in percent.
    """
    raw = get_setting(SETTING_GLOBAL_COMMISSION_RATE, default="")
    if raw:
        try:
            return Decimal(raw)
        except (InvalidOperation, ValueError):
            # Valeur corrompue : on retombe sur le defaut de deploiement.
            pass
    return Decimal(str(settings.COMMISSION_RATE_DEFAULT))


def set_global_commission_rate(rate) -> Decimal:
    """Store the platform-wide commission rate.

    Args:
        rate: The rate in percent (0–100).

    Returns:
        The stored rate.
    """
    value = Decimal(str(rate)).quantize(Decimal("0.01"))
    set_setting(
        SETTING_GLOBAL_COMMISSION_RATE,
        str(value),
        description="Taux de commission applique aux compagnies sans taux propre (%).",
    )
    return value


def get_payment_methods_config() -> list[dict]:
    """Return the platform-level activation state of each payment method.

    Returns:
        One entry per pilotable method: ``method``, ``method_display`` and
        ``is_active`` (default ``True``).
    """
    raw = get_setting(SETTING_PAYMENT_METHODS, default="")
    try:
        stored = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        stored = {}

    labels = dict(PaymentMethodChoice.choices)
    return [
        {
            "method": method,
            "method_display": labels[method],
            "is_active": bool(stored.get(method, True)),
        }
        for method in PLATFORM_PAYMENT_METHODS
    ]


def set_payment_methods_config(items: list[dict]) -> list[dict]:
    """Update the platform-level activation of payment methods.

    Unknown methods (and ``cash``, always available) are ignored.

    Args:
        items: Entries with ``method`` and ``is_active``.

    Returns:
        The refreshed configuration.
    """
    current = {entry["method"]: entry["is_active"] for entry in get_payment_methods_config()}
    for item in items:
        method = item.get("method")
        if method in current:
            current[method] = bool(item.get("is_active", True))

    set_setting(
        SETTING_PAYMENT_METHODS,
        json.dumps(current),
        description="Moyens de paiement actives au niveau plateforme.",
    )
    return get_payment_methods_config()


def _expired_subscription_filter(subscription_status, today):
    """Build the queryset filter matching an expired subscription.

    Args:
        subscription_status: The ``SubscriptionStatus`` choices class.
        today: The reference date.

    Returns:
        A ``Q`` object matching subscriptions flagged expired or whose period
        has lapsed while still marked active.
    """
    from django.db.models import Q

    return Q(status=subscription_status.EXPIRED) | Q(
        status=subscription_status.ACTIVE, end_date__lt=today
    )


def build_super_notifications(limit_per_source: int = 50) -> list[dict]:
    """Build the super admin supervision feed.

    Aggregates the events the platform team must react to: new company
    registration requests, expired subscriptions, urgent reports (speed reports
    and escalated claims) and technical incidents (failed offline syncs). The
    feed is computed on the fly — nothing is stored (cf. PROMPT_SUP A6).

    Args:
        limit_per_source: Maximum number of items read per source.

    Returns:
        Feed entries sorted by ``created_at`` descending.
    """
    # Imports locaux : evite un cycle d'import au chargement des apps.
    from django.utils import timezone

    from apps.claims.models import Claim, ClaimStatus
    from apps.companies.models import OPEN_REQUEST_STATUSES, Company
    from apps.speed_reports.models import SpeedReport, SpeedReportStatus
    from apps.subscriptions.models import Subscription, SubscriptionStatus
    from apps.sync.models import SyncLog, SyncStatus

    today = timezone.localdate()
    items: list[dict] = []

    for company in Company.objects.filter(status__in=OPEN_REQUEST_STATUSES)[
        :limit_per_source
    ]:
        items.append(
            {
                "type": "new_registration",
                "severity": "info",
                "title": "Nouvelle demande d'inscription",
                "body": f"La compagnie {company.name} attend une decision.",
                "reference_type": "company",
                "reference_id": company.id,
                "created_at": company.created_at,
            }
        )

    expired_subscriptions = Subscription.objects.select_related("company").filter(
        _expired_subscription_filter(SubscriptionStatus, today)
    )[:limit_per_source]
    for subscription in expired_subscriptions:
        items.append(
            {
                "type": "subscription_expired",
                "severity": "warning",
                "title": "Abonnement expire",
                "body": (
                    f"L'abonnement de {subscription.company.name} a expire le "
                    f"{subscription.end_date:%d/%m/%Y}."
                ),
                "reference_type": "subscription",
                "reference_id": subscription.id,
                "created_at": subscription.updated_at,
            }
        )

    for report in SpeedReport.objects.select_related("company").filter(
        status=SpeedReportStatus.PENDING
    )[:limit_per_source]:
        items.append(
            {
                "type": "urgent_report",
                "severity": "critical",
                "title": "Signalement d'exces de vitesse",
                "body": f"Signalement en attente concernant {report.company.name}.",
                "reference_type": "speed_report",
                "reference_id": report.id,
                "created_at": report.created_at,
            }
        )

    for claim in Claim.objects.select_related("company").filter(
        status=ClaimStatus.ESCALATED
    )[:limit_per_source]:
        items.append(
            {
                "type": "urgent_report",
                "severity": "critical",
                "title": "Reclamation escaladee",
                "body": f"{claim.subject} ({claim.company.name}).",
                "reference_type": "claim",
                "reference_id": claim.id,
                "created_at": claim.created_at,
            }
        )

    for sync_log in SyncLog.objects.select_related("agent").filter(
        status=SyncStatus.ERROR
    )[:limit_per_source]:
        items.append(
            {
                "type": "technical_incident",
                "severity": "warning",
                "title": "Echec de synchronisation hors ligne",
                "body": (
                    f"Synchronisation en erreur pour l'agent {sync_log.agent_id} "
                    f"({sync_log.errors_count} enregistrement(s) rejete(s))."
                ),
                "reference_type": "sync_log",
                "reference_id": sync_log.id,
                "created_at": sync_log.created_at,
            }
        )

    items.sort(key=lambda item: item["created_at"], reverse=True)
    return items


def is_payment_method_enabled(method: str) -> bool:
    """Tell whether a payment method is enabled platform-wide.

    Args:
        method: One of ``PaymentMethodChoice`` values.

    Applied by ``payments.services.initiate_payment``: a disabled method is
    refused with a 400 before any provider call.

    Returns:
        ``True`` for ``cash`` and for any method not explicitly disabled.
    """
    if method == PaymentMethodChoice.CASH:
        return True
    return next(
        (entry["is_active"] for entry in get_payment_methods_config() if entry["method"] == method),
        True,
    )
