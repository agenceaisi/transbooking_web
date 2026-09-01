import factory
from factory.django import DjangoModelFactory

from apps.notifications.models import Notification, NotificationType
from apps.users.tests.factories import UserFactory


class NotificationFactory(DjangoModelFactory):
    class Meta:
        model = Notification

    user = factory.SubFactory(UserFactory)
    type = NotificationType.SYSTEM
    title = factory.Sequence(lambda n: f"Notification {n}")
    body = "Corps de la notification."
    is_read = False
