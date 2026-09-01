import pytest

from apps.users.models import AgentProfile, Role

from .factories import UserFactory


@pytest.mark.django_db
def test_agent_profile_can_be_bootstrapped_without_company():
    role = Role.objects.create(name=Role.RoleName.AGENT_GUICHET)
    user = UserFactory(role=role)

    profile = AgentProfile.objects.create(
        user=user,
        agent_type=AgentProfile.AgentType.GUICHET,
    )

    assert profile.company is None
    assert profile.agent_type == AgentProfile.AgentType.GUICHET
