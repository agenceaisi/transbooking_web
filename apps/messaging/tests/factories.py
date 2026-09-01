import factory
from factory.django import DjangoModelFactory

from apps.messaging.models import Message
from apps.users.tests.factories import UserFactory


class MessageFactory(DjangoModelFactory):
    class Meta:
        model = Message

    sender = factory.SubFactory(UserFactory)
    recipient = factory.SubFactory(UserFactory)
    subject = "Information voyage"
    body = "Votre voyage part a l'heure prevue."
    is_read = False
