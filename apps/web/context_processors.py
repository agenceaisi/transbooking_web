"""Context processors partages par les gabarits de l'espace voyageur."""
from django.http import HttpRequest


def notifications_non_lues(request: HttpRequest) -> dict:
    """Expose the traveler's unread notification count to every template.

    Computed here rather than threaded through each view: the bell icon lives
    in the shared header (`templates/espace/base_espace.html`), rendered on
    every authenticated page.

    Args:
        request: The incoming request.

    Returns:
        A dict with ``notifications_non_lues`` (0 when not authenticated).
    """
    if not request.user.is_authenticated:
        return {"notifications_non_lues": 0}
    return {"notifications_non_lues": request.user.notifications.filter(is_read=False).count()}
