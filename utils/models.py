from django.db import models


class TimeStampedModel(models.Model):
    """Abstract base model adding self-managed timestamp fields.

    Attributes:
        created_at: Set once when the row is first inserted.
        updated_at: Refreshed on every save.
    """

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True
