import pytest
from django.db import IntegrityError

from apps.reviews.models import Review

from .factories import ReviewFactory


@pytest.mark.django_db
def test_unique_review_per_user_trip():
    review = ReviewFactory()
    with pytest.raises(IntegrityError):
        Review.objects.create(
            company=review.company,
            user=review.user,
            trip=review.trip,
            rating=3,
        )
