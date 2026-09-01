import re
from collections import Counter

from django.db.models import Avg, Count, FloatField, OuterRef, Subquery
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.bookings.models import Booking, BookingStatus
from apps.trips.models import Trip

from .models import Review

# Mots vides (francais) exclus du nuage de mots.
STOP_WORDS = {
    "le", "la", "les", "un", "une", "des", "de", "du", "et", "a", "au", "aux",
    "en", "est", "il", "elle", "ils", "elles", "je", "tu", "nous", "vous",
    "pour", "par", "sur", "avec", "sans", "mais", "ou", "que", "qui", "ce",
    "cette", "ces", "son", "sa", "ses", "mon", "ma", "mes", "ne", "pas",
    "plus", "tres", "trop", "dans", "se", "ete", "etait", "y",
}


def can_review(user, trip: Trip) -> bool:
    """Return whether a user may review a trip (cf. business_rules.md §4).

    Args:
        user: The traveller wishing to review.
        trip: The trip being reviewed.

    Returns:
        True if the trip is completed and the user has a paid booking on it.
    """
    return (
        trip.status == Trip.TripStatus.COMPLETED
        and Booking.objects.filter(
            user=user, trip=trip, status=BookingStatus.PAID
        ).exists()
    )


def create_review(validated_data: dict, user) -> Review:
    """Create a review after enforcing the eligibility rules.

    Args:
        validated_data: Cleaned fields containing ``trip``, ``rating`` and
            optionally ``comment``.
        user: The authenticated traveller leaving the review.

    Returns:
        The created review.

    Raises:
        ValidationError: If the trip is not completed, the user has no paid
            booking on it, or the user already reviewed this trip.
    """
    trip = validated_data["trip"]
    if not can_review(user, trip):
        raise ValidationError(
            "Vous ne pouvez noter que les voyages termines pour lesquels vous "
            "avez une reservation payee."
        )
    if Review.objects.filter(user=user, trip=trip).exists():
        raise ValidationError("Vous avez deja depose un avis pour ce voyage.")

    return Review.objects.create(
        company=trip.route.company,
        user=user,
        trip=trip,
        rating=validated_data["rating"],
        comment=validated_data.get("comment", ""),
    )


def respond_to_review(review: Review, response: str) -> Review:
    """Record a company response to a review.

    Args:
        review: The review being answered.
        response: The textual response.

    Returns:
        The updated review.
    """
    review.response = response
    review.responded_at = timezone.now()
    review.save(update_fields=["response", "responded_at", "updated_at"])
    return review


def flag_review(review: Review) -> Review:
    """Flag a review as inappropriate (company admin action).

    Only the super admin can delete a flagged review (cf. business_rules.md §4).

    Args:
        review: The review to flag.

    Returns:
        The updated review.
    """
    review.is_flagged = True
    review.save(update_fields=["is_flagged", "updated_at"])
    return review


def company_rating_subquery(company_field: str = "company_id") -> Subquery:
    """Build a subquery yielding a company's average public review score.

    Only non-flagged reviews (those visible to the public) count, so the score
    matches what travellers can actually read. Use it to annotate any queryset
    whose rows relate to a company, avoiding a per-row aggregation query::

        Trip.objects.annotate(
            company_rating=company_rating_subquery("route__company_id")
        )

    Args:
        company_field: ``OuterRef`` path to the company id on the outer row.

    Returns:
        A ``Subquery`` producing a float average, or ``NULL`` when the company
        has no reviews.
    """
    return Subquery(
        Review.objects.filter(is_flagged=False, company_id=OuterRef(company_field))
        .values("company_id")
        .annotate(avg=Avg("rating"))
        .values("avg")[:1],
        output_field=FloatField(),
    )


def company_rating_stats(company) -> dict:
    """Aggregate the public rating figures of a single company.

    Flagged reviews are excluded so the stats mirror the public review list.

    Args:
        company: The company whose reviews are aggregated.

    Returns:
        A dict with ``rating`` (average rounded to one decimal, or ``None`` when
        there is no review), ``reviews_count`` (total non-flagged reviews) and
        ``rating_breakdown`` (``{"1": n, …, "5": n}`` counts per star level).
    """
    queryset = Review.objects.filter(company=company, is_flagged=False)
    aggregates = queryset.aggregate(avg=Avg("rating"), count=Count("id"))

    breakdown = {str(star): 0 for star in range(1, 6)}
    for row in queryset.values("rating").annotate(count=Count("id")):
        breakdown[str(row["rating"])] = row["count"]

    avg = aggregates["avg"]
    return {
        "rating": round(float(avg), 1) if avg is not None else None,
        "reviews_count": aggregates["count"],
        "rating_breakdown": breakdown,
    }


def word_cloud(queryset) -> dict:
    """Build a word frequency map from the comments of a set of reviews.

    Args:
        queryset: Reviews to aggregate (already scoped to a company).

    Returns:
        A ``{word: count}`` dict, stop words and short tokens excluded,
        ordered from most to least frequent.
    """
    counter: Counter = Counter()
    for comment in queryset.values_list("comment", flat=True):
        if not comment:
            continue
        for token in re.findall(r"\b[\wàâçéèêëîïôûùüÿñæœ]+\b", comment.lower()):
            if len(token) > 2 and token not in STOP_WORDS:
                counter[token] += 1
    return dict(counter.most_common())
