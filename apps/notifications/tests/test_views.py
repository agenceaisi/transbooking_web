import pytest
from rest_framework.test import APIClient

from apps.notifications.models import Notification
from apps.users.models import Role, User

from .factories import NotificationFactory


@pytest.fixture
def api_client():
    return APIClient()


def _make_user(role_name: str, phone: str) -> User:
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password="password123", role=role
    )


@pytest.mark.django_db
def test_list_returns_only_own_notifications_unread_first(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670001000")
    read = NotificationFactory(user=user, is_read=True)
    unread = NotificationFactory(user=user, is_read=False)
    NotificationFactory()  # autre utilisateur
    api_client.force_authenticate(user=user)

    response = api_client.get("/api/v1/notifications/")

    assert response.status_code == 200
    results = response.data["results"] if "results" in response.data else response.data
    ids = [n["id"] for n in results]
    assert ids == [unread.id, read.id]


@pytest.mark.django_db
def test_read_marks_single_notification(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670001001")
    notification = NotificationFactory(user=user, is_read=False)
    api_client.force_authenticate(user=user)

    response = api_client.post(f"/api/v1/notifications/{notification.id}/read/")

    assert response.status_code == 200
    notification.refresh_from_db()
    assert notification.is_read is True


@pytest.mark.django_db
def test_read_all_marks_every_notification(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670001002")
    NotificationFactory.create_batch(4, user=user, is_read=False)
    api_client.force_authenticate(user=user)

    response = api_client.post("/api/v1/notifications/read-all/")

    assert response.status_code == 200
    assert response.data["updated"] == 4
    assert Notification.objects.filter(user=user, is_read=False).count() == 0


@pytest.mark.django_db
def test_cannot_read_another_users_notification(api_client):
    user = _make_user(Role.RoleName.VOYAGEUR, "+22670001003")
    other_notification = NotificationFactory(is_read=False)
    api_client.force_authenticate(user=user)

    response = api_client.post(
        f"/api/v1/notifications/{other_notification.id}/read/"
    )

    assert response.status_code == 404
    other_notification.refresh_from_db()
    assert other_notification.is_read is False


@pytest.mark.django_db
def test_anonymous_cannot_list(api_client):
    response = api_client.get("/api/v1/notifications/")
    assert response.status_code in (401, 403)
