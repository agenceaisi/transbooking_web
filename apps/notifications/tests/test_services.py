import pytest

from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import mark_all_read, notify
from apps.users.tests.factories import UserFactory

from .factories import NotificationFactory


@pytest.mark.django_db
def test_notify_creates_notification():
    user = UserFactory()
    notification = notify(
        user.id,
        type=NotificationType.BOOKING,
        title="Reservation confirmee",
        body="Votre siege A3 est reserve.",
        reference_id=42,
        reference_type="booking",
    )

    assert notification.pk is not None
    assert notification.user_id == user.id
    assert notification.is_read is False
    assert notification.reference_id == 42
    assert notification.reference_type == "booking"


@pytest.mark.django_db
def test_mark_all_read_marks_only_users_unread():
    user = UserFactory()
    other = UserFactory()
    NotificationFactory.create_batch(3, user=user, is_read=False)
    NotificationFactory(user=user, is_read=True)
    NotificationFactory(user=other, is_read=False)

    updated = mark_all_read(user)

    assert updated == 3
    assert Notification.objects.filter(user=user, is_read=False).count() == 0
    assert Notification.objects.filter(user=other, is_read=False).count() == 1
