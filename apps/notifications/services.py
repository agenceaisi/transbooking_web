from .models import Notification


def notify(
    user_id: int,
    type: str,
    title: str,
    body: str = "",
    reference_id: int | None = None,
    reference_type: str = "",
) -> Notification:
    """Create an in-app notification for a user.

    This is the single entry point other services (bookings, parcels, claims...)
    should use instead of creating ``Notification`` rows inline.

    Args:
        user_id: Primary key of the recipient user.
        type: Notification category (see ``NotificationType``).
        title: Short headline shown in the notification list.
        body: Optional longer description.
        reference_id: Optional primary key of the related object.
        reference_type: Optional label of the related object (e.g. ``"booking"``).

    Returns:
        The created notification.
    """
    return Notification.objects.create(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        reference_id=reference_id,
        reference_type=reference_type,
    )


def mark_all_read(user) -> int:
    """Mark every unread notification of a user as read.

    Args:
        user: The owner of the notifications.

    Returns:
        The number of notifications updated.
    """
    return Notification.objects.filter(user=user, is_read=False).update(is_read=True)
