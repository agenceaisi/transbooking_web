import factory
from factory.django import DjangoModelFactory

from apps.users.models import Role, User


class RoleFactory(DjangoModelFactory):
    class Meta:
        model = Role
        django_get_or_create = ("name",)

    name = Role.RoleName.VOYAGEUR


class UserFactory(DjangoModelFactory):
    class Meta:
        model = User
        skip_postgeneration_save = True

    prenom = "Awa"
    nom = "Ouedraogo"
    email = factory.Sequence(lambda n: f"user{n}@example.com")
    phone = factory.Sequence(lambda n: f"+2267{n:07d}")
    role = factory.SubFactory(RoleFactory)
    password = factory.PostGenerationMethodCall("set_password", "password123")
