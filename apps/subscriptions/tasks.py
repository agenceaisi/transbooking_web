"""Taches Celery de l'app subscriptions (cycle de vie des abonnements)."""
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from utils.sms import send_sms
from utils.tasks import log_task_errors

from .models import Subscription, SubscriptionStatus

# Delai de prevenance avant expiration d'un abonnement.
EXPIRY_WARNING_DAYS = 7


def _notify_company(company, title: str, body: str) -> None:
    """Send an in-app notification and an SMS to a company about its plan.

    Args:
        company: The company to notify.
        title: Notification headline.
        body: Notification / SMS body.
    """
    # Import local : evite un cycle d'import au chargement des apps.
    from apps.notifications.services import notify
    from apps.notifications.models import NotificationType

    if company.admin_user_id:
        notify(
            user_id=company.admin_user_id,
            type=NotificationType.SYSTEM,
            title=title,
            body=body,
        )
    if company.responsible_phone:
        send_sms(company.responsible_phone, body)


@shared_task
@log_task_errors
def check_expiring_subscriptions() -> dict:
    """Warn, renew or suspend companies according to subscription expiry.

    Daily Celery beat task. For active subscriptions it:
      * sends a one-time reminder 7 days before ``end_date`` (gated by
        ``expiry_reminder_sent`` for idempotence);
      * once expired, renews when ``auto_renew`` is set, otherwise marks the
        subscription expired and suspends the company.

    Returns:
        A summary dict ``{"reminded", "renewed", "suspended"}`` for logging.
    """
    # Import local : la suspension vit dans l'app companies.
    from apps.companies.services import suspend_company

    from .services import expire_subscription, renew_subscription

    today = timezone.localdate()
    warning_threshold = today + timedelta(days=EXPIRY_WARNING_DAYS)
    summary = {"reminded": 0, "renewed": 0, "suspended": 0}

    # 1. Rappel : abonnements actifs expirant dans les 7 jours, non encore prevenus.
    expiring = Subscription.objects.select_related("company").filter(
        status=SubscriptionStatus.ACTIVE,
        end_date__gt=today,
        end_date__lte=warning_threshold,
        expiry_reminder_sent=False,
    )
    for subscription in expiring:
        _notify_company(
            subscription.company,
            "Abonnement bientot expire",
            f"Votre abonnement TransBooking BF expire le "
            f"{subscription.end_date:%d/%m/%Y}. Pensez a le renouveler.",
        )
        subscription.expiry_reminder_sent = True
        subscription.save(update_fields=["expiry_reminder_sent", "updated_at"])
        summary["reminded"] += 1

    # 2. Expiration : abonnements actifs dont la date de fin est passee.
    expired = Subscription.objects.select_related("company", "plan").filter(
        status=SubscriptionStatus.ACTIVE,
        end_date__lt=today,
    )
    for subscription in expired:
        company = subscription.company
        if subscription.auto_renew:
            renew_subscription(subscription, today)
            _notify_company(
                company,
                "Abonnement renouvele",
                f"Votre abonnement TransBooking BF a ete renouvele jusqu'au "
                f"{subscription.end_date:%d/%m/%Y}.",
            )
            summary["renewed"] += 1
        else:
            expire_subscription(subscription)
            # Suspension de la compagnie (notifie deja le responsable par SMS).
            suspend_company(
                company,
                f"Abonnement expire le {subscription.end_date:%d/%m/%Y}.",
            )
            summary["suspended"] += 1

    return summary
