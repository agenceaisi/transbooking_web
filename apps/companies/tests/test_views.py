import pytest
from rest_framework.test import APIClient

from apps.companies.models import Company, CompanyStatus
from apps.users.models import Role, User

from .factories import CompanyFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test",
        nom="User",
        phone=phone,
        password="password123",
        role=role,
    )


@pytest.mark.django_db
def test_public_companies_lists_only_active(api_client):
    CompanyFactory(status=CompanyStatus.ACTIVE, name="Active Co")
    CompanyFactory(status=CompanyStatus.PENDING, name="Pending Co")

    response = api_client.get("/api/v1/public/companies/")

    assert response.status_code == 200
    names = [c["name"] for c in response.data["results"]]
    assert "Active Co" in names
    assert "Pending Co" not in names


@pytest.mark.django_db
def test_public_company_detail_exposes_routes_and_rating_breakdown(api_client):
    from apps.reviews.tests.factories import ReviewFactory
    from apps.routes.tests.factories import RouteFactory

    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    route = RouteFactory(company=company, base_price=8500, duration_minutes=315)
    RouteFactory(company=company, is_active=False)  # inactif => exclu
    ReviewFactory(company=company, rating=5)
    ReviewFactory(company=company, rating=3)

    response = api_client.get(f"/api/v1/public/companies/{company.id}/")

    assert response.status_code == 200
    # Section « Trajets desservis » : seuls les trajets actifs.
    assert len(response.data["routes"]) == 1
    summary = response.data["routes"][0]
    assert summary["id"] == route.id
    assert summary["origin_city_name"] == route.origin_city.name
    assert summary["destination_city_name"] == route.destination_city.name
    assert summary["duration_minutes"] == 315
    # Agregat serveur des notes.
    assert response.data["rating"] == 4.0
    assert response.data["reviews_count"] == 2
    assert response.data["rating_breakdown"]["5"] == 1
    assert response.data["rating_breakdown"]["3"] == 1
    assert response.data["rating_breakdown"]["1"] == 0


@pytest.mark.django_db
def test_super_admin_can_suspend_company(api_client):
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000010")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        f"/api/v1/super/companies/{company.id}/suspend/",
        {"reason": "Impayes"},
        format="json",
    )

    assert response.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.SUSPENDED


@pytest.mark.django_db
def test_company_requests_lists_pending_and_approves(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000011")
    api_client.force_authenticate(user=admin)

    list_response = api_client.get("/api/v1/super/company-requests/")
    assert list_response.status_code == 200
    assert any(c["id"] == company.id for c in list_response.data["results"])

    approve_response = api_client.post(
        f"/api/v1/super/company-requests/{company.id}/approve/"
    )
    assert approve_response.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_company_admin_cannot_access_other_company_settings(api_client):
    company_a = CompanyFactory(name="Company A")
    company_b = CompanyFactory(name="Company B")

    admin_a = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000020")
    company_a.admin_user = admin_a
    company_a.save(update_fields=["admin_user"])

    admin_b = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000021")
    company_b.admin_user = admin_b
    company_b.save(update_fields=["admin_user"])

    api_client.force_authenticate(user=admin_a)
    response = api_client.get("/api/v1/company/settings/")

    assert response.status_code == 200
    # L'admin A ne voit QUE sa propre compagnie, jamais celle de B.
    assert response.data["name"] == "Company A"
    assert response.data["name"] != "Company B"


@pytest.mark.django_db
def test_company_admin_without_company_gets_404(api_client):
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000022")
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/settings/")
    assert response.status_code == 404


@pytest.mark.django_db
def test_voyageur_cannot_access_super_companies(api_client):
    CompanyFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670000030")
    api_client.force_authenticate(user=voyageur)

    response = api_client.get("/api/v1/super/companies/")
    assert response.status_code == 403


@pytest.mark.django_db
def test_company_admin_updates_payment_methods(api_client):
    company = CompanyFactory()
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000040")
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        "/api/v1/company/settings/payment-methods/",
        {"payment_methods": [{"method": "orange_money", "is_active": True}]},
        format="json",
    )

    assert response.status_code == 200
    assert company.payment_methods.filter(method="orange_money", is_active=True).exists()


# --------------------------------------------------------------------------- #
# Demande publique d'inscription d'une compagnie
# --------------------------------------------------------------------------- #
COMPANY_REGISTER_URL = "/api/v1/auth/company/register/"

VALID_REQUEST_PAYLOAD = {
    "company_name": "Transport Sahel",
    "manager_name": "Awa Ouedraogo",
    "phone": "+22670000050",
    "email": "contact@sahel.bf",
    "city": "Ouagadougou",
}


@pytest.mark.django_db
def test_company_register_creates_pending_request(api_client):
    response = api_client.post(COMPANY_REGISTER_URL, VALID_REQUEST_PAYLOAD, format="json")

    assert response.status_code == 201
    company = Company.objects.get(name="Transport Sahel")
    assert company.status == CompanyStatus.PENDING
    assert company.responsible_name == "Awa Ouedraogo"
    assert company.responsible_phone == "+22670000050"
    assert company.city == "Ouagadougou"
    assert response.data["status"] == CompanyStatus.PENDING
    assert response.data["company_name"] == "Transport Sahel"


@pytest.mark.django_db
def test_company_register_creates_no_user_and_no_active_company(api_client):
    users_before = User.objects.count()

    response = api_client.post(COMPANY_REGISTER_URL, VALID_REQUEST_PAYLOAD, format="json")

    assert response.status_code == 201
    # Aucun compte n'est cree tant que le super admin n'a pas approuve.
    assert User.objects.count() == users_before
    company = Company.objects.get(name="Transport Sahel")
    assert company.admin_user is None
    assert not Company.objects.filter(status=CompanyStatus.ACTIVE).exists()


@pytest.mark.django_db
def test_company_register_appears_in_super_admin_requests(api_client):
    api_client.post(COMPANY_REGISTER_URL, VALID_REQUEST_PAYLOAD, format="json")

    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000051")
    api_client.force_authenticate(user=admin)
    response = api_client.get("/api/v1/super/company-requests/")

    assert response.status_code == 200
    assert "Transport Sahel" in [c["name"] for c in response.data["results"]]


@pytest.mark.django_db
def test_company_register_rejects_duplicate_name(api_client):
    CompanyFactory(name="Transport Sahel")

    response = api_client.post(COMPANY_REGISTER_URL, VALID_REQUEST_PAYLOAD, format="json")

    assert response.status_code == 400
    assert "company_name" in response.data


@pytest.mark.django_db
def test_company_register_rejects_invalid_phone(api_client):
    payload = {**VALID_REQUEST_PAYLOAD, "phone": "07000"}

    response = api_client.post(COMPANY_REGISTER_URL, payload, format="json")

    assert response.status_code == 400
    assert "phone" in response.data
    assert not Company.objects.filter(name="Transport Sahel").exists()


@pytest.mark.django_db
def test_company_register_requires_mandatory_fields(api_client):
    response = api_client.post(
        COMPANY_REGISTER_URL,
        {"company_name": "Transport Sahel"},
        format="json",
    )

    assert response.status_code == 400
    for field in ("manager_name", "phone", "email", "city"):
        assert field in response.data


# --------------------------------------------------------------------------- #
# Demande d'informations complementaires (A2)
# --------------------------------------------------------------------------- #
def _request_info_url(company_id: int) -> str:
    return f"/api/v1/super/company-requests/{company_id}/request-info/"


@pytest.mark.django_db
def test_super_admin_requests_additional_info(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000060")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        _request_info_url(company.id),
        {"message": "Merci de fournir le RCCM et l'agrement."},
        format="json",
    )

    assert response.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.INFO_REQUESTED
    assert company.info_request_message == "Merci de fournir le RCCM et l'agrement."
    assert response.data["status"] == CompanyStatus.INFO_REQUESTED
    assert response.data["info_request_message"] == "Merci de fournir le RCCM et l'agrement."


@pytest.mark.django_db
def test_request_info_keeps_request_in_the_super_admin_queue(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000061")
    api_client.force_authenticate(user=admin)

    api_client.post(_request_info_url(company.id), {"message": "RCCM manquant."}, format="json")

    response = api_client.get("/api/v1/super/company-requests/")
    assert response.status_code == 200
    assert any(c["id"] == company.id for c in response.data["results"])


@pytest.mark.django_db
def test_request_info_then_approve_completes_the_cycle(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000062")
    api_client.force_authenticate(user=admin)

    api_client.post(_request_info_url(company.id), {"message": "RCCM manquant."}, format="json")
    response = api_client.post(f"/api/v1/super/company-requests/{company.id}/approve/")

    assert response.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE


@pytest.mark.django_db
def test_request_info_rejects_empty_message(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000063")
    api_client.force_authenticate(user=admin)

    response = api_client.post(_request_info_url(company.id), {"message": "  "}, format="json")

    assert response.status_code == 400
    assert "message" in response.data
    company.refresh_from_db()
    assert company.status == CompanyStatus.PENDING


@pytest.mark.django_db
def test_request_info_on_closed_request_returns_404(api_client):
    company = CompanyFactory(status=CompanyStatus.ACTIVE)
    admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22670000064")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        _request_info_url(company.id),
        {"message": "RCCM manquant."},
        format="json",
    )

    # Une compagnie active n'est plus une demande : elle sort du queryset.
    assert response.status_code == 404


@pytest.mark.django_db
def test_request_info_forbidden_for_company_admin(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)
    other = CompanyFactory(status=CompanyStatus.ACTIVE, name="Autre compagnie")
    company_admin = _make_user(Role.RoleName.COMPANY_ADMIN, "+22670000065")
    other.admin_user = company_admin
    other.save(update_fields=["admin_user"])
    api_client.force_authenticate(user=company_admin)

    response = api_client.post(
        _request_info_url(company.id),
        {"message": "RCCM manquant."},
        format="json",
    )

    assert response.status_code == 403
    company.refresh_from_db()
    assert company.status == CompanyStatus.PENDING


@pytest.mark.django_db
def test_request_info_requires_authentication(api_client):
    company = CompanyFactory(status=CompanyStatus.PENDING)

    response = api_client.post(
        _request_info_url(company.id),
        {"message": "RCCM manquant."},
        format="json",
    )

    assert response.status_code == 401
