import pytest
from rest_framework.exceptions import ValidationError

from apps.bookings.tests.factories import BookingFactory
from apps.bookings.models import BookingStatus
from apps.reviews.models import Review
from apps.reviews.services import can_review, create_review, word_cloud
from apps.trips.models import Trip
from apps.trips.tests.factories import TripFactory
from apps.users.tests.factories import UserFactory

from .factories import ReviewFactory


@pytest.mark.django_db
def test_can_review_requires_completed_trip_and_paid_booking():
    user = UserFactory()
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)
    BookingFactory(user=user, trip=trip, status=BookingStatus.PAID)
    assert can_review(user, trip) is True


@pytest.mark.django_db
def test_can_review_false_when_trip_not_completed():
    user = UserFactory()
    trip = TripFactory(status=Trip.TripStatus.SCHEDULED)
    BookingFactory(user=user, trip=trip, status=BookingStatus.PAID)
    assert can_review(user, trip) is False


@pytest.mark.django_db
def test_create_review_blocked_without_paid_booking():
    user = UserFactory()
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)
    with pytest.raises(ValidationError):
        create_review({"trip": trip, "rating": 5}, user=user)


@pytest.mark.django_db
def test_create_review_blocked_when_duplicate():
    user = UserFactory()
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)
    BookingFactory(user=user, trip=trip, status=BookingStatus.PAID)
    create_review({"trip": trip, "rating": 5}, user=user)
    with pytest.raises(ValidationError):
        create_review({"trip": trip, "rating": 4}, user=user)


@pytest.mark.django_db
def test_word_cloud_counts_words_excluding_stopwords():
    company = ReviewFactory(comment="Bus confortable et chauffeur ponctuel").company
    ReviewFactory(company=company, comment="Chauffeur tres ponctuel, bus propre")

    cloud = word_cloud(Review.objects.filter(company=company))

    assert cloud.get("chauffeur") == 2
    assert cloud.get("ponctuel") == 2
    # Les mots vides ne sont pas comptes.
    assert "et" not in cloud
