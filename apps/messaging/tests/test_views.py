import pytest
from rest_framework.test import APIClient

from apps.bookings.tests.factories import BookingFactory
from apps.companies.tests.factories import CompanyFactory
from apps.users.models import Role, User
from apps.users.tests.factories import UserFactory

from .factories import MessageFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


# --------------------------------------------------------------------------- #
# Messagerie
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_list_returns_sent_and_received(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670002000")
    sent = MessageFactory(sender=user)
    received = MessageFactory(recipient=user)
    MessageFactory()  # ni envoye ni recu
    api_client.force_authenticate(user=user)

    response = api_client.get("/api/v1/messages/")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    ids = {m["id"] for m in results}
    assert ids == {sent.id, received.id}


@pytest.mark.django_db
def test_voyageur_sends_message_without_subject(api_client):
    sender = _make_user(Role.RoleName.VOYAGEUR, "+22670002001")
    recipient = UserFactory()
    api_client.force_authenticate(user=sender)

    response = api_client.post(
        "/api/v1/messages/",
        {"recipient": recipient.id, "body": "Bonjour, une question."},
        format="json",
    )

    assert response.status_code == 201
    assert response.data["sender"] == sender.id
    assert response.data["recipient"] == recipient.id


@pytest.mark.django_db
def test_agent_must_provide_subject(api_client):
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670002002")
    recipient = UserFactory()
    api_client.force_authenticate(user=agent)

    response = api_client.post(
        "/api/v1/messages/",
        {"recipient": recipient.id, "body": "Votre bus part dans 1h."},
        format="json",
    )

    assert response.status_code == 400
    assert "subject" in response.data


@pytest.mark.django_db
def test_retrieve_marks_received_message_read(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670002003")
    message = MessageFactory(recipient=user, is_read=False)
    api_client.force_authenticate(user=user)

    response = api_client.get(f"/api/v1/messages/{message.id}/")

    assert response.status_code == 200
    message.refresh_from_db()
    assert message.is_read is True


@pytest.mark.django_db
def test_retrieve_does_not_mark_sent_message_read(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670002004")
    message = MessageFactory(sender=user, is_read=False)
    api_client.force_authenticate(user=user)

    response = api_client.get(f"/api/v1/messages/{message.id}/")

    assert response.status_code == 200
    message.refresh_from_db()
    assert message.is_read is False


# --------------------------------------------------------------------------- #
# Liste des passagers (ciblage des messages)
# --------------------------------------------------------------------------- #


@pytest.mark.django_db
def test_agent_gets_trip_passenger_list(api_client):
    company = CompanyFactory()
    agent = _make_user(Role.RoleName.AGENT_GUICHET, "+22670002005")

    voyageur = UserFactory()
    booking = BookingFactory(user=voyageur)
    # Le voyage doit appartenir a la compagnie de l'agent.
    booking.trip.route.company = company
    booking.trip.route.save(update_fields=["company"])
    _attach_agent_company(agent, company)
    api_client.force_authenticate(user=agent)

    response = api_client.get(
        f"/api/v1/agent/trips/{booking.trip_id}/passenger-list/"
    )

    assert response.status_code == 200
    assert response.data == [
        {
            "id": voyageur.id,
            "full_name": f"{voyageur.prenom} {voyageur.nom}",
            "phone": voyageur.phone,
        }
    ]


@pytest.mark.django_db
def test_voyageur_cannot_access_passenger_list(api_client):
    booking = BookingFactory()
    voyageur = _make_user(Role.RoleName.VOYAGEUR, "+22670002006")
    api_client.force_authenticate(user=voyageur)

    response = api_client.get(
        f"/api/v1/agent/trips/{booking.trip_id}/passenger-list/"
    )

    assert response.status_code == 403


def _attach_agent_company(agent, company):
    """Attach an AgentProfile so the agent is scoped to ``company``."""
    from apps.users.models import AgentProfile

    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
