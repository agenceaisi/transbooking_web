import factory
from factory.django import DjangoModelFactory

from apps.reviews.models import Review
from apps.trips.tests.factories import TripFactory
from apps.users.tests.factories import UserFactory


class ReviewFactory(DjangoModelFactory):
    class Meta:
        model = Review

    user = factory.SubFactory(UserFactory)
    trip = factory.SubFactory(TripFactory)
    company = factory.LazyAttribute(lambda obj: obj.trip.route.company)
    rating = 4
    comment = "Voyage confortable et chauffeur tres ponctuel."
