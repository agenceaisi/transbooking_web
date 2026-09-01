from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from rest_framework.test import APIClient

from apps.bookings.tests.factories import BookingFactory
from apps.claims.models import ClaimStatus
from apps.companies.tests.factories import CompanyFactory
from apps.users.models import Role, User

from .factories import ClaimFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


def _company_admin(company, phone="+22670004000") -> User:
    user = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = user
    company.save(update_fields=["admin_user", "updated_at"])
    return user


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_voyageur_submits_claim(api_client):
    company = CompanyFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001000")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/claims/",
        {
            "company": company.id,
            "claim_type": "retard",
            "subject": "Retard important",
            "description": "Deux heures de retard.",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["status"] == ClaimStatus.SUBMITTED
    assert response.data["company"] == company.id


@pytest.mark.django_db
def test_claim_company_derived_from_booking(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001001")
    booking = BookingFactory(user=voyageur)
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/claims/",
        {
            "booking": booking.id,
            "claim_type": "perte_bagage",
            "subject": "Bagage perdu",
            "description": "Mon sac n'est jamais arrive.",
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["company"] == booking.trip.route.company_id


@pytest.mark.django_db
def test_voyageur_cannot_claim_on_others_booking(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001002")
    booking = BookingFactory()  # appartient a un autre voyageur
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/claims/",
        {
            "booking": booking.id,
            "claim_type": "autre",
            "subject": "Probleme",
            "description": "Description.",
        },
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_voyageur_lists_only_own_claims(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001003")
    mine = ClaimFactory(user=voyageur)
    ClaimFactory()  # autre voyageur
    api_client.force_authenticate(user=voyageur)

    response = api_client.get("/api/v1/claims/")

    results = response.data["results"] if "results" in response.data else response.data
    assert [c["id"] for c in results] == [mine.id]


# --------------------------------------------------------------------------- #
# Pieces jointes (photo / recu / PDF, 10 Mo max)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_voyageur_submits_claim_with_attachment(api_client):
    company = CompanyFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001010")
    api_client.force_authenticate(user=voyageur)
    pdf = SimpleUploadedFile(
        "recu.pdf", b"%PDF-1.4 contenu du recu", content_type="application/pdf"
    )

    response = api_client.post(
        "/api/v1/claims/",
        {
            "company": company.id,
            "claim_type": "retard",
            "subject": "Retard important",
            "description": "Deux heures de retard.",
            "attachment": pdf,
        },
        format="multipart",
    )

    assert response.status_code == 201
    assert len(response.data["attachments"]) == 1
    attachment = response.data["attachments"][0]
    assert attachment["content_type"] == "application/pdf"
    assert attachment["original_name"] == "recu.pdf"


@pytest.mark.django_db
def test_voyageur_adds_attachment_to_existing_claim(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001011")
    claim = ClaimFactory(user=voyageur)
    api_client.force_authenticate(user=voyageur)
    photo = SimpleUploadedFile(
        "billet.png", b"\x89PNG\r\n fake", content_type="image/png"
    )

    response = api_client.post(
        f"/api/v1/claims/{claim.id}/attachment/",
        {"file": photo},
        format="multipart",
    )

    assert response.status_code == 201
    assert len(response.data["attachments"]) == 1
    assert claim.attachments.count() == 1


@pytest.mark.django_db
def test_claim_attachment_rejects_unsupported_type(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001012")
    claim = ClaimFactory(user=voyageur)
    api_client.force_authenticate(user=voyageur)
    text = SimpleUploadedFile("note.txt", b"texte", content_type="text/plain")

    response = api_client.post(
        f"/api/v1/claims/{claim.id}/attachment/",
        {"file": text},
        format="multipart",
    )

    assert response.status_code == 400
    assert claim.attachments.count() == 0


@pytest.mark.django_db
def test_claim_attachment_rejects_oversize(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001013")
    claim = ClaimFactory(user=voyageur)
    api_client.force_authenticate(user=voyageur)
    # 10 Mo + 1 octet : au-dela de la limite autorisee.
    oversized = SimpleUploadedFile(
        "gros.pdf", b"%PDF" + b"0" * (10 * 1024 * 1024), content_type="application/pdf"
    )

    response = api_client.post(
        f"/api/v1/claims/{claim.id}/attachment/",
        {"file": oversized},
        format="multipart",
    )

    assert response.status_code == 400
    assert claim.attachments.count() == 0


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_company_admin_sees_only_own_company_claims(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    mine = ClaimFactory(company=company)
    ClaimFactory()  # autre compagnie
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/claims/")

    results = response.data["results"] if "results" in response.data else response.data
    assert [c["id"] for c in results] == [mine.id]


@pytest.mark.django_db
def test_company_admin_responds_to_claim(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    claim = ClaimFactory(company=company)
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"/api/v1/company/claims/{claim.id}/respond/",
        {"response": "Nous vous presentons nos excuses.", "status": "resolved"},
        format="json",
    )

    assert response.status_code == 200
    claim.refresh_from_db()
    assert claim.status == ClaimStatus.RESOLVED
    assert claim.responded_by_id == admin.id
    assert claim.responded_at is not None


@pytest.mark.django_db
def test_company_admin_claim_stats(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    resolved = ClaimFactory(company=company, status=ClaimStatus.RESOLVED)
    type(resolved).objects.filter(pk=resolved.pk).update(
        created_at=timezone.now() - timedelta(hours=4),
        responded_at=timezone.now() - timedelta(hours=2),
    )
    ClaimFactory(company=company, status=ClaimStatus.SUBMITTED)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/claims/stats/")

    assert response.status_code == 200
    assert response.data["total"] == 2
    assert response.data["resolved"] == 1
    assert response.data["resolution_rate"] == 50.0
    assert response.data["avg_response_hours"] == pytest.approx(2.0, abs=0.1)


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_super_admin_lists_unresolved_across_companies(api_client):
    superadmin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670009000")
    ClaimFactory(status=ClaimStatus.SUBMITTED)
    ClaimFactory(status=ClaimStatus.RESOLVED)
    api_client.force_authenticate(user=superadmin)

    response = api_client.get("/api/v1/super/claims/unresolved/")

    results = response.data["results"] if "results" in response.data else response.data
    assert len(results) == 1
    assert results[0]["status"] == ClaimStatus.SUBMITTED


@pytest.mark.django_db
def test_super_admin_escalates_and_closes(api_client):
    superadmin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670009001")
    claim = ClaimFactory(status=ClaimStatus.SUBMITTED)
    api_client.force_authenticate(user=superadmin)

    escalate = api_client.post(f"/api/v1/super/claims/{claim.id}/escalate/")
    assert escalate.status_code == 200
    claim.refresh_from_db()
    assert claim.status == ClaimStatus.ESCALATED

    close = api_client.post(f"/api/v1/super/claims/{claim.id}/close/")
    assert close.status_code == 200
    claim.refresh_from_db()
    assert claim.status == ClaimStatus.CLOSED


@pytest.mark.django_db
def test_company_admin_cannot_access_super_endpoint(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/super/claims/unresolved/")
    assert response.status_code == 403
