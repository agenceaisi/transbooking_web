from django.db.models import Q

from apps.bookings.models import Booking, BookingStatus


def passenger_list(trip) -> list[dict]:
    """Return the list of passengers of a trip for message targeting.

    Only passengers holding a user account (i.e. who can receive an in-app
    message) and an active booking are returned, deduplicated by user.

    Args:
        trip: The trip whose passengers are requested.

    Returns:
        A list of ``{"id", "full_name", "phone"}`` dicts.
    """
    bookings = (
        Booking.objects.filter(trip=trip, user__isnull=False)
        .exclude(status=BookingStatus.CANCELLED)
        .select_related("user")
    )
    passengers: dict[int, dict] = {}
    for booking in bookings:
        user = booking.user
        # Premiere reservation rencontree par voyageur (deduplication).
        passengers.setdefault(
            user.id,
            {
                "id": user.id,
                "full_name": f"{user.prenom} {user.nom}".strip(),
                "phone": user.phone,
            },
        )
    return list(passengers.values())


def inbox_for(user):
    """Return the messages sent or received by a user, newest first.

    Args:
        user: The current user.

    Returns:
        A ``Message`` queryset scoped to the user's conversations.
    """
    from .models import Message

    return (
        Message.objects.filter(Q(sender=user) | Q(recipient=user))
        .select_related("sender", "recipient")
        .order_by("-created_at")
    )
