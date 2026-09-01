from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models

from utils.models import TimeStampedModel


class Review(TimeStampedModel):
    """Avis depose par un voyageur sur un voyage termine.

    Conditions de depot (cf. business_rules.md §4) : `trip.status == completed`
    ET le voyageur possede une reservation payee sur ce voyage. La verification
    est faite dans `services.create_review()`.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews",
    )
    trip = models.ForeignKey(
        "trips.Trip",
        on_delete=models.CASCADE,
        related_name="reviews",
    )

    rating = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    comment = models.TextField(blank=True)

    # Reponse de la compagnie (facultative).
    response = models.TextField(blank=True)
    responded_at = models.DateTimeField(null=True, blank=True)

    # Signale par l'admin compagnie ; seul le super admin peut supprimer.
    is_flagged = models.BooleanField(default=False)

    # Temoignage mis en avant sur la page d'accueil publique. La selection est
    # faite par le super admin (curation plateforme), jamais par la compagnie.
    is_testimonial = models.BooleanField(default=False)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Avis"
        verbose_name_plural = "Avis"
        constraints = [
            # Un voyageur ne laisse qu'un seul avis par voyage.
            models.UniqueConstraint(
                fields=["user", "trip"],
                name="unique_review_per_user_trip",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.company.name} - {self.rating}/5"
