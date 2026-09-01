"""Temoignages publics et curation super admin (cf. PROMPT_SUP A7)."""
import pytest
from rest_framework.test import APIClient

from apps.companies.tests.factories import CompanyFactory
from apps.reviews.models import Review
from apps.users.models import Role, User

from .factories import ReviewFactory


TESTIMONIALS_URL = "/api/v1/public/testimonials/"
SUPER_REVIEWS_URL = "/api/v1/super/reviews/"


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


@pytest.mark.django_db
def test_public_testimonials_list_only_selected_reviews(api_client):
    ReviewFactory(is_testimonial=True, comment="Service impeccable.")
    ReviewFactory(is_testimonial=False, comment="Avis ordinaire.")

    response = api_client.get(TESTIMONIALS_URL)

    assert response.status_code == 200
    comments = [item["comment"] for item in response.data["results"]]
    assert comments == ["Service impeccable."]


@pytest.mark.django_db
def test_flagged_review_never_appears_as_testimonial(api_client):
    ReviewFactory(is_testimonial=True, is_flagged=True)

    response = api_client.get(TESTIMONIALS_URL)

    assert response.data["count"] == 0


@pytest.mark.django_db
def test_testimonials_expose_only_the_author_initial(api_client):
    review = ReviewFactory(is_testimonial=True)
    review.user.prenom = "Awa"
    review.user.nom = "Ouedraogo"
    review.user.save(update_fields=["prenom", "nom"])

    response = api_client.get(TESTIMONIALS_URL)

    assert response.data["results"][0]["author"] == "Awa O."
    # L'identite complete n'est jamais exposee publiquement.
    assert "Ouedraogo" not in str(response.data["results"][0])


@pytest.mark.django_db
def test_testimonials_can_be_filtered_by_company(api_client):
    wanted = ReviewFactory(is_testimonial=True)
    ReviewFactory(is_testimonial=True)

    response = api_client.get(f"{TESTIMONIALS_URL}?company_id={wanted.company_id}")

    assert response.data["count"] == 1
    assert response.data["results"][0]["company"] == wanted.company_id


@pytest.mark.django_db
def test_testimonials_are_public(api_client):
    ReviewFactory(is_testimonial=True)

    # Aucun en-tete d'authentification : la route reste ouverte.
    assert api_client.get(TESTIMONIALS_URL).status_code == 200


@pytest.mark.django_db
def test_super_admin_selects_a_testimonial(api_client):
    review = ReviewFactory()
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22676000001")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"{SUPER_REVIEWS_URL}{review.id}/testimonial/",
        {"is_testimonial": True},
        format="json",
    )

    assert response.status_code == 200
    review.refresh_from_db()
    assert review.is_testimonial is True
    assert response.data["is_testimonial"] is True


@pytest.mark.django_db
def test_super_admin_removes_a_testimonial(api_client):
    review = ReviewFactory(is_testimonial=True)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22676000002")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"{SUPER_REVIEWS_URL}{review.id}/testimonial/",
        {"is_testimonial": False},
        format="json",
    )

    assert response.status_code == 200
    review.refresh_from_db()
    assert review.is_testimonial is False


@pytest.mark.django_db
def test_flagged_review_cannot_be_promoted(api_client):
    review = ReviewFactory(is_flagged=True)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22676000003")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"{SUPER_REVIEWS_URL}{review.id}/testimonial/",
        {"is_testimonial": True},
        format="json",
    )

    assert response.status_code == 400
    review.refresh_from_db()
    assert review.is_testimonial is False


@pytest.mark.django_db
def test_company_admin_cannot_select_testimonials(api_client):
    company = CompanyFactory()
    review = ReviewFactory(company=company)
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22676000004")
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"{SUPER_REVIEWS_URL}{review.id}/testimonial/",
        {"is_testimonial": True},
        format="json",
    )

    assert response.status_code == 403
    assert Review.objects.filter(is_testimonial=True).count() == 0


@pytest.mark.django_db
def test_super_reviews_require_authentication(api_client):
    assert api_client.get(SUPER_REVIEWS_URL).status_code == 401
