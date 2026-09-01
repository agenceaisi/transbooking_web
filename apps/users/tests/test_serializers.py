import pytest

from apps.users.models import Role, User
from apps.users.serializers import UserRegistrationSerializer


@pytest.mark.django_db
def test_registration_serializer_rejects_duplicate_phone():
    role = Role.objects.create(name=Role.RoleName.VOYAGEUR)
    User.objects.create_user(
        prenom="Awa",
        nom="Ouedraogo",
        phone="+22670000000",
        password="password123",
        role=role,
    )

    serializer = UserRegistrationSerializer(
        data={
            "prenom": "Paul",
            "nom": "Kabore",
            "phone": "+22670000000",
            "password": "password123",
        }
    )

    assert not serializer.is_valid()
    assert "phone" in serializer.errors
