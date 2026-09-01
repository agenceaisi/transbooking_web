import pytest
from rest_framework.test import APIClient

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.companies.tests.factories import CompanyFactory
from apps.reviews.models import Review
from apps.trips.models import Trip
from apps.trips.tests.factories import TripFactory
from apps.users.models import Role, User

from .factories import ReviewFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Awa", nom="Ouedraogo", phone=phone, password="password123", role=role
    )


def _company_admin(company, phone="+22670004000") -> User:
    user = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = user
    company.save(update_fields=["admin_user", "updated_at"])
    return user


# --------------------------------------------------------------------------- #
# Public + voyageur
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_public_lists_reviews_by_company(api_client):
    review = ReviewFactory()
    ReviewFactory()  # autre compagnie
    flagged = ReviewFactory(company=review.company, is_flagged=True)

    response = api_client.get(f"/api/v1/reviews/?company_id={review.company_id}")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    ids = [r["id"] for r in results]
    assert review.id in ids
    # Les avis signales sont masques au public.
    assert flagged.id not in ids


@pytest.mark.django_db
def test_voyageur_posts_review_on_completed_trip(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001000")
    trip = TripFactory(status=Trip.TripStatus.COMPLETED)
    BookingFactory(user=voyageur, trip=trip, status=BookingStatus.PAID)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/reviews/",
        {"trip": trip.id, "rating": 5, "comment": "Excellent voyage."},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["rating"] == 5
    assert response.data["company"] == trip.route.company_id


@pytest.mark.django_db
def test_voyageur_review_blocked_without_completed_trip(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001001")
    trip = TripFactory(status=Trip.TripStatus.SCHEDULED)
    BookingFactory(user=voyageur, trip=trip, status=BookingStatus.PAID)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/reviews/",
        {"trip": trip.id, "rating": 5},
        format="json",
    )

    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_company_admin_responds_and_flags(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    review = ReviewFactory(company=company)
    api_client.force_authenticate(user=admin)

    respond = api_client.post(
        f"/api/v1/company/reviews/{review.id}/respond/",
        {"response": "Merci pour votre retour."},
        format="json",
    )
    assert respond.status_code == 200
    review.refresh_from_db()
    assert review.responded_at is not None

    flag = api_client.post(f"/api/v1/company/reviews/{review.id}/flag/")
    assert flag.status_code == 200
    review.refresh_from_db()
    assert review.is_flagged is True


@pytest.mark.django_db
def test_company_admin_cannot_delete_review(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    review = ReviewFactory(company=company)
    api_client.force_authenticate(user=admin)

    response = api_client.delete(f"/api/v1/company/reviews/{review.id}/")
    # Pas de DestroyModelMixin : suppression interdite.
    assert response.status_code == 405
    assert Review.objects.filter(pk=review.pk).exists()


@pytest.mark.django_db
def test_company_admin_word_cloud(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    ReviewFactory(company=company, comment="Chauffeur ponctuel et bus confortable")
    ReviewFactory(company=company, comment="Chauffeur tres ponctuel")
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/reviews/word-cloud/")

    assert response.status_code == 200
    assert response.data.get("chauffeur") == 2


@pytest.mark.django_db
def test_company_admin_sees_only_own_reviews(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    mine = ReviewFactory(company=company)
    ReviewFactory()  # autre compagnie
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/reviews/")

    results = response.data["results"] if "results" in response.data else response.data
    assert [r["id"] for r in results] == [mine.id]
