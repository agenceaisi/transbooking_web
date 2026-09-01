import pytest
from rest_framework.test import APIClient

from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import StationFactory
from apps.users.models import AgentProfile, Role, User


@pytest.fixture
def api_client():
    return APIClient()


@pytest.mark.django_db
def test_register_voyageur(api_client):
    response = api_client.post(
        "/api/v1/auth/register/",
        {
            "prenom": "Awa",
            "nom": "Ouedraogo",
            "phone": "+22670000001",
            "email": "awa@example.com",
            "password": "password123",
        },
        format="json",
    )

    assert response.status_code == 201
    user = User.objects.get(phone="+22670000001")
    assert user.role.name == Role.RoleName.VOYAGEUR
    assert user.check_password("password123")
    assert response.data["role"] == Role.RoleName.VOYAGEUR


@pytest.mark.django_db
def test_register_rejects_duplicate_phone(api_client):
    Role.objects.create(name=Role.RoleName.VOYAGEUR)
    User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000002",
        password="password123",
    )

    response = api_client.post(
        "/api/v1/auth/register/",
        {
            "prenom": "Awa",
            "nom": "Ouedraogo",
            "phone": "+22670000002",
            "password": "password123",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_register_rejects_invalid_phone_format(api_client):
    response = api_client.post(
        "/api/v1/auth/register/",
        {
            "prenom": "Awa",
            "nom": "Ouedraogo",
            "phone": "07000",
            "password": "password123",
        },
        format="json",
    )

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_login_rejects_wrong_password(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000003",
        password="password123",
        role=role,
    )

    response = api_client.post(
        "/api/v1/auth/login/",
        {"phone": "+22670000003", "password": "bad-password"},
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_profile_update_allows_phone_and_email_only(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000004",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.patch(
        "/api/v1/users/me/",
        {
            "phone": "+22670000005",
            "email": "new@example.com",
            "prenom": "Ignored",
        },
        format="json",
    )

    user.refresh_from_db()
    assert response.status_code == 200
    assert user.phone == "+22670000005"
    assert user.email == "new@example.com"
    assert user.prenom == "Awa"


@pytest.mark.django_db
def test_password_change_updates_password(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000007",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/v1/auth/password/change/",
        {"old_password": "password123", "new_password": "TransBooking2026"},
        format="json",
    )

    user.refresh_from_db()
    assert response.status_code == 200
    assert response.data["detail"] == "Mot de passe modifie avec succes."
    assert user.check_password("TransBooking2026")


@pytest.mark.django_db
def test_password_change_rejects_wrong_old_password(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000008",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/v1/auth/password/change/",
        {"old_password": "mauvais-mot-de-passe", "new_password": "TransBooking2026"},
        format="json",
    )

    user.refresh_from_db()
    assert response.status_code == 400
    assert "old_password" in response.data
    assert user.check_password("password123")


@pytest.mark.django_db
def test_password_change_rejects_weak_new_password(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000009",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/v1/auth/password/change/",
        {"old_password": "password123", "new_password": "12345678"},
        format="json",
    )

    user.refresh_from_db()
    assert response.status_code == 400
    assert "new_password" in response.data
    assert user.check_password("password123")


@pytest.mark.django_db
def test_password_change_rejects_identical_password(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000012",
        password="TransBooking2026",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/v1/auth/password/change/",
        {"old_password": "TransBooking2026", "new_password": "TransBooking2026"},
        format="json",
    )

    assert response.status_code == 400
    assert "new_password" in response.data


@pytest.mark.django_db
def test_password_change_requires_authentication(api_client):
    response = api_client.post(
        "/api/v1/auth/password/change/",
        {"old_password": "password123", "new_password": "TransBooking2026"},
        format="json",
    )

    assert response.status_code == 401


@pytest.mark.django_db
def test_me_hides_company_and_station_for_voyageur(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000010",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.get("/api/v1/users/me/")

    assert response.status_code == 200
    assert response.data["company_name"] is None
    assert response.data["station"] is None


@pytest.mark.django_db
def test_me_exposes_agent_company_and_station(api_client):
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = User.objects.create_user(
        prenom="Issa",
        nom="Kabore",
        phone="+22670000011",
        password="password123",
        role=role,
    )
    company = CompanyFactory(name="Faso Express")
    station = StationFactory(company=company, name="Gare de Ouaga")
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
        station=station,
    )
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/users/me/")

    assert response.status_code == 200
    assert response.data["company_name"] == "Faso Express"
    assert response.data["station"] == {"id": station.id, "name": "Gare de Ouaga"}


@pytest.mark.django_db
def test_me_exposes_administered_company_for_company_admin(api_client):
    role, _ = Role.objects.get_or_create(name=Role.RoleName.COMPANY_ADMIN)
    admin = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000013",
        password="password123",
        role=role,
    )
    company = CompanyFactory(name="Rakieta", admin_user=admin)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/users/me/")

    assert response.status_code == 200
    assert response.data["company_name"] == company.name
    assert response.data["station"] is None


@pytest.mark.django_db
def test_logout_rejects_invalid_refresh_token(api_client):
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    user = User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000006",
        password="password123",
        role=role,
    )
    api_client.force_authenticate(user=user)

    response = api_client.post(
        "/api/v1/auth/logout/",
        {"refresh": "not-a-real-token"},
        format="json",
    )

    assert response.status_code == 400
    assert "refresh" in response.data
