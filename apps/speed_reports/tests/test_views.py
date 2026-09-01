import pytest
from rest_framework.test import APIClient

from apps.companies.tests.factories import CompanyFactory
from apps.speed_reports.models import SpeedReportStatus
from apps.trips.tests.factories import TripFactory
from apps.users.models import Role, User

from .factories import SpeedReportFactory


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
# Voyageur
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_voyageur_submits_speed_report_with_trip(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001000")
    trip = TripFactory()
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/speed-reports/",
        {"trip": trip.id, "estimated_speed": 130, "description": "Trop vite."},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["company"] == trip.route.company_id
    # Horodatage pose automatiquement.
    assert response.data["reported_at"] is not None


@pytest.mark.django_db
def test_voyageur_report_persists_severity(api_client):
    # La maquette fait choisir une gravite (Faible / Moyenne / Grave) : elle doit
    # etre stockee structuree, pas repliee dans la description.
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001003")
    trip = TripFactory()
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/speed-reports/",
        {"trip": trip.id, "severity": "high", "description": "Conduite dangereuse."},
        format="json",
    )

    assert response.status_code == 201
    # Reponse en lecture : id + gravite exploitable.
    assert response.data["id"] is not None
    assert response.data["severity"] == "high"
    assert response.data["severity_display"] == "Grave"


@pytest.mark.django_db
def test_voyageur_report_severity_is_optional(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001004")
    trip = TripFactory()
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/speed-reports/",
        {"trip": trip.id, "estimated_speed": 130},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["severity"] is None
    assert response.data["severity_display"] is None


@pytest.mark.django_db
def test_voyageur_report_requires_company_or_trip(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001001")
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/speed-reports/",
        {"estimated_speed": 130},
        format="json",
    )

    assert response.status_code == 400


@pytest.mark.django_db
def test_voyageur_submits_speed_report_with_company(api_client):
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670001002")
    company = CompanyFactory()
    api_client.force_authenticate(user=voyageur)

    response = api_client.post(
        "/api/v1/speed-reports/",
        {"company": company.id, "estimated_speed": 110},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["company"] == company.id


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_company_admin_sees_only_own_reports(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    mine = SpeedReportFactory(company=company)
    SpeedReportFactory()  # autre compagnie
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/speed-reports/")

    results = response.data["results"] if "results" in response.data else response.data
    assert [r["id"] for r in results] == [mine.id]


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_super_admin_lists_all_and_updates_status(api_client):
    superadmin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670009000")
    report = SpeedReportFactory()
    SpeedReportFactory()
    api_client.force_authenticate(user=superadmin)

    listing = api_client.get("/api/v1/super/speed-reports/")
    results = (
        listing.data["results"] if "results" in listing.data else listing.data
    )
    assert len(results) == 2

    patch = api_client.patch(
        f"/api/v1/super/speed-reports/{report.id}/",
        {"status": SpeedReportStatus.REVIEWED},
        format="json",
    )
    assert patch.status_code == 200
    report.refresh_from_db()
    assert report.status == SpeedReportStatus.REVIEWED


@pytest.mark.django_db
def test_company_admin_cannot_access_super_listing(api_client):
    company = CompanyFactory()
    admin = _company_admin(company)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/super/speed-reports/")
    assert response.status_code == 403
