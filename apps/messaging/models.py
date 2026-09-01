from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class Message(TimeStampedModel):
    """Message direct entre deux utilisateurs (agent <-> client).

    Sert notamment a l'agent guichet pour contacter les passagers d'un voyage
    (cf. endpoint `passenger-list`).
    """

    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sent_messages",
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="received_messages",
    )
    subject = models.CharField(max_length=200, blank=True)
    body = models.TextField()
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Message"
        verbose_name_plural = "Messages"

    def __str__(self) -> str:
        return f"{self.subject or self.body[:30]} ({self.sender_id} -> {self.recipient_id})"
