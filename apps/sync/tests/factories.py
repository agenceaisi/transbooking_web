import factory
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.routes.tests.factories import RouteFactory
from apps.sync.models import SyncConflict, SyncConflictType, SyncLog
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role
from apps.users.tests.factories import UserFactory
from apps.vehicles.tests.factories import VehicleFactory


class SyncLogFactory(DjangoModelFactory):
    class Meta:
        model = SyncLog

    agent = factory.SubFactory(UserFactory)


class SyncConflictFactory(DjangoModelFactory):
    class Meta:
        model = SyncConflict

    sync_log = factory.SubFactory(SyncLogFactory)
    conflict_type = SyncConflictType.SEAT_CONFLICT
    reference = "BF2026000001"
    original_seat = "A3"
    assigned_seat = "B7"
    resolution = "Siege A3 deja attribue. Nouveau siege attribue : B7."
    resolved = True


def make_guichet_agent(company, phone="+22670009000"):
    """Create an agent guichet bound to a company, with its profile."""
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = UserFactory(role=role, phone=phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
    )
    return agent


def make_company_trip(company=None, total_seats=10, **trip_kwargs):
    """Create a trip whose route belongs to ``company`` (created if omitted)."""
    company = company or CompanyFactory()
    route = RouteFactory(company=company)
    vehicle = VehicleFactory(company=company, total_seats=total_seats)
    trip_kwargs.setdefault("available_seats", total_seats)
    return TripFactory(route=route, vehicle=vehicle, **trip_kwargs)
