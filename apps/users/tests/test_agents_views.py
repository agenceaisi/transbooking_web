"""Gestion des agents par le company admin (cf. PROMPT_SUP A4)."""
import pytest
from rest_framework.test import APIClient

from apps.bookings.tests.factories import BookingFactory
from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import StationFactory
from apps.users.models import AgentProfile, Role, User


AGENTS_URL = "/api/v1/company/agents/"
INVITE_URL = "/api/v1/company/agents/invite/"


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "apps.users.services.send_sms",
        lambda phone, message: sent.append((phone, message)),
    )
    return sent


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test",
        nom="User",
        phone=phone,
        password="password123",
        role=role,
    )


def _make_company_admin(company, phone: str) -> User:
    admin = _make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    return admin


def _make_agent(company, phone: str, role_name=Role.RoleName.AGENT_GUICHET) -> User:
    agent = _make_user(role_name, phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=(
            AgentProfile.AgentType.GUICHET
            if role_name == Role.RoleName.AGENT_GUICHET
            else AgentProfile.AgentType.CONTROLEUR
        ),
    )
    return agent


# --------------------------------------------------------------------------- #
# Creation et liste
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_admin_creates_agent_with_sms_password(api_client, _mute_sms):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000001")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        AGENTS_URL,
        {
            "prenom": "Issa",
            "nom": "Kabore",
            "phone": "+22670000100",
            "role": Role.RoleName.AGENT_GUICHET,
        },
        format="json",
    )

    assert response.status_code == 201
    agent = User.objects.get(phone="+22670000100")
    assert agent.role.name == Role.RoleName.AGENT_GUICHET
    assert agent.agent_profile.company_id == company.id
    assert agent.agent_profile.agent_type == AgentProfile.AgentType.GUICHET
    assert agent.is_active is True
    # Le mot de passe temporaire part par SMS et n'est jamais renvoye par l'API.
    assert any("mot de passe temporaire" in msg for _, msg in _mute_sms)
    assert "password" not in response.data


@pytest.mark.django_db
def test_create_controleur_maps_to_controleur_profile(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000002")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        AGENTS_URL,
        {
            "prenom": "Awa",
            "nom": "Sawadogo",
            "phone": "+22670000101",
            "role": Role.RoleName.CONTROLEUR,
        },
        format="json",
    )

    assert response.status_code == 201
    assert response.data["agent_type"] == AgentProfile.AgentType.CONTROLEUR


@pytest.mark.django_db
def test_create_agent_rejects_duplicate_phone(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000003")
    _make_agent(company, "+22670000102")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        AGENTS_URL,
        {
            "prenom": "Issa",
            "nom": "Kabore",
            "phone": "+22670000102",
            "role": Role.RoleName.AGENT_GUICHET,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_create_agent_rejects_non_agent_role(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000004")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        AGENTS_URL,
        {
            "prenom": "Issa",
            "nom": "Kabore",
            "phone": "+22670000103",
            "role": Role.RoleName.COMPANY_ADMIN,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "role" in response.data


@pytest.mark.django_db
def test_create_agent_rejects_station_of_another_company(api_client):
    company = CompanyFactory()
    other_station = StationFactory()
    admin = _make_company_admin(company, "+22672000005")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        AGENTS_URL,
        {
            "prenom": "Issa",
            "nom": "Kabore",
            "phone": "+22670000104",
            "role": Role.RoleName.AGENT_GUICHET,
            "station": other_station.id,
        },
        format="json",
    )

    assert response.status_code == 400
    assert "station" in response.data


@pytest.mark.django_db
def test_agent_list_is_isolated_by_company(api_client):
    mine = CompanyFactory(name="Ma compagnie")
    other = CompanyFactory(name="Autre compagnie")
    _make_agent(mine, "+22670000110")
    _make_agent(other, "+22670000111")
    admin = _make_company_admin(mine, "+22672000006")
    api_client.force_authenticate(user=admin)

    response = api_client.get(AGENTS_URL)

    assert response.status_code == 200
    assert response.data["count"] == 1
    assert response.data["results"][0]["phone"] == "+22670000110"


@pytest.mark.django_db
def test_agent_of_another_company_returns_404(api_client):
    mine = CompanyFactory()
    other = CompanyFactory()
    foreign_agent = _make_agent(other, "+22670000112")
    admin = _make_company_admin(mine, "+22672000007")
    api_client.force_authenticate(user=admin)

    assert api_client.get(f"{AGENTS_URL}{foreign_agent.id}/").status_code == 404
    assert (
        api_client.patch(
            f"{AGENTS_URL}{foreign_agent.id}/", {"is_active": False}, format="json"
        ).status_code
        == 404
    )


# --------------------------------------------------------------------------- #
# Modification / desactivation / suppression
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_company_admin_deactivates_agent(api_client):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000120")
    admin = _make_company_admin(company, "+22672000010")
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        f"{AGENTS_URL}{agent.id}/", {"is_active": False}, format="json"
    )

    assert response.status_code == 200
    agent.refresh_from_db()
    assert agent.is_active is False
    assert response.data["is_active"] is False


@pytest.mark.django_db
def test_company_admin_changes_agent_role(api_client):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000121")
    admin = _make_company_admin(company, "+22672000011")
    api_client.force_authenticate(user=admin)

    response = api_client.patch(
        f"{AGENTS_URL}{agent.id}/",
        {"role": Role.RoleName.CONTROLEUR, "prenom": "Moussa"},
        format="json",
    )

    assert response.status_code == 200
    agent.refresh_from_db()
    assert agent.role.name == Role.RoleName.CONTROLEUR
    assert agent.prenom == "Moussa"
    assert agent.agent_profile.agent_type == AgentProfile.AgentType.CONTROLEUR


@pytest.mark.django_db
def test_agent_without_activity_can_be_deleted(api_client):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000122")
    admin = _make_company_admin(company, "+22672000012")
    api_client.force_authenticate(user=admin)

    response = api_client.delete(f"{AGENTS_URL}{agent.id}/")

    assert response.status_code == 204
    assert not User.objects.filter(pk=agent.pk).exists()


@pytest.mark.django_db
def test_agent_with_activity_cannot_be_deleted(api_client):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000123")
    BookingFactory(agent=agent)
    admin = _make_company_admin(company, "+22672000013")
    api_client.force_authenticate(user=admin)

    response = api_client.delete(f"{AGENTS_URL}{agent.id}/")

    assert response.status_code == 400
    assert User.objects.filter(pk=agent.pk).exists()

    # Seule la desactivation reste possible.
    patch = api_client.patch(f"{AGENTS_URL}{agent.id}/", {"is_active": False}, format="json")
    assert patch.status_code == 200


# --------------------------------------------------------------------------- #
# Reinitialisation du mot de passe et invitation
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_reset_password_sends_new_temporary_password(api_client, _mute_sms):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000130")
    previous_hash = agent.password
    admin = _make_company_admin(company, "+22672000020")
    api_client.force_authenticate(user=admin)

    response = api_client.post(f"{AGENTS_URL}{agent.id}/reset-password/")

    assert response.status_code == 200
    agent.refresh_from_db()
    assert agent.password != previous_hash
    assert any(phone == "+22670000130" for phone, _ in _mute_sms)
    assert "password" not in response.data


@pytest.mark.django_db
def test_reset_password_on_foreign_agent_returns_404(api_client):
    mine = CompanyFactory()
    other = CompanyFactory()
    foreign_agent = _make_agent(other, "+22670000131")
    admin = _make_company_admin(mine, "+22672000021")
    api_client.force_authenticate(user=admin)

    response = api_client.post(f"{AGENTS_URL}{foreign_agent.id}/reset-password/")

    assert response.status_code == 404


@pytest.mark.django_db
def test_invite_agent_sends_sms_link(api_client, _mute_sms):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000022")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        INVITE_URL,
        {"phone": "+22670000140", "role": Role.RoleName.CONTROLEUR, "prenom": "Awa"},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["phone"] == "+22670000140"
    assert response.data["invite_url"].startswith("http")
    # Aucun compte n'est cree tant que l'agent n'a pas suivi le lien.
    assert not User.objects.filter(phone="+22670000140").exists()
    assert any(phone == "+22670000140" for phone, _ in _mute_sms)


@pytest.mark.django_db
def test_invite_rejects_existing_phone(api_client):
    company = CompanyFactory()
    _make_agent(company, "+22670000141")
    admin = _make_company_admin(company, "+22672000023")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        INVITE_URL,
        {"phone": "+22670000141", "role": Role.RoleName.AGENT_GUICHET},
        format="json",
    )

    assert response.status_code == 400
    assert "phone" in response.data


@pytest.mark.django_db
def test_invite_rejects_invalid_phone_format(api_client):
    company = CompanyFactory()
    admin = _make_company_admin(company, "+22672000024")
    api_client.force_authenticate(user=admin)

    response = api_client.post(
        INVITE_URL, {"phone": "0700", "role": Role.RoleName.AGENT_GUICHET}, format="json"
    )

    assert response.status_code == 400
    assert "phone" in response.data


# --------------------------------------------------------------------------- #
# Permissions
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_cannot_manage_agents(api_client):
    company = CompanyFactory()
    agent = _make_agent(company, "+22670000150")
    api_client.force_authenticate(user=agent)

    assert api_client.get(AGENTS_URL).status_code == 403
    assert (
        api_client.post(
            AGENTS_URL,
            {
                "prenom": "X",
                "nom": "Y",
                "phone": "+22670000151",
                "role": Role.RoleName.AGENT_GUICHET,
            },
            format="json",
        ).status_code
        == 403
    )


@pytest.mark.django_db
def test_super_admin_is_not_a_company_agent_manager(api_client):
    super_admin = _make_user(Role.RoleName.SUPER_ADMIN, "+22672000030")
    api_client.force_authenticate(user=super_admin)

    assert api_client.get(AGENTS_URL).status_code == 403


@pytest.mark.django_db
def test_agents_require_authentication(api_client):
    assert api_client.get(AGENTS_URL).status_code == 401
