"""Helpers building dashboard test fixtures (roles, paid bookings, agents)."""
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.companies.tests.factories import CompanyFactory
from apps.payments.models import PaymentMethod, PaymentStatus
from apps.payments.tests.factories import PaymentFactory
from apps.routes.tests.factories import RouteFactory
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role
from apps.users.tests.factories import UserFactory
from apps.vehicles.tests.factories import VehicleFactory


def make_company_admin(company=None, phone="+22670001000"):
    """Create a company_admin user wired to ``company`` via ``admin_user``."""
    role, _ = Role.objects.get_or_create(name=Role.RoleName.COMPANY_ADMIN)
    admin = UserFactory(role=role, phone=phone)
    company = company or CompanyFactory()
    company.admin_user = admin
    company.save(update_fields=["admin_user"])
    return admin, company


def make_super_admin(phone="+22670002000"):
    """Create a super_admin user."""
    role, _ = Role.objects.get_or_create(name=Role.RoleName.SUPER_ADMIN)
    return UserFactory(role=role, phone=phone)


def make_voyageur(phone="+22670003000"):
    """Create a voyageur user."""
    role, _ = Role.objects.get_or_create(name=Role.RoleName.VOYAGEUR)
    return UserFactory(role=role, phone=phone)


def make_agent(company, station=None, vehicle=None, phone="+22670004000"):
    """Create an agent guichet bound to ``company`` with its profile."""
    role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
    agent = UserFactory(role=role, phone=phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
        station=station,
        vehicle=vehicle,
    )
    return agent


def make_company_trip(company, total_seats=30, **trip_kwargs):
    """Create a trip whose route/vehicle belong to ``company``."""
    route = RouteFactory(company=company)
    vehicle = VehicleFactory(company=company, total_seats=total_seats)
    trip_kwargs.setdefault("departure_time", timezone.now())
    trip_kwargs.setdefault("available_seats", total_seats)
    return TripFactory(route=route, vehicle=vehicle, **trip_kwargs)


def make_paid_payment(
    company,
    amount=5000,
    commission=500,
    method=PaymentMethod.CASH,
    when=None,
    trip=None,
    agent=None,
):
    """Create a paid booking + payment attached to ``company``.

    Returns the created :class:`Payment`.
    """
    when = when or timezone.now()
    trip = trip or make_company_trip(company)
    booking = BookingFactory(
        trip=trip, amount=amount, status=BookingStatus.PAID, agent=agent
    )
    return PaymentFactory(
        booking=booking,
        amount=amount,
        commission=commission,
        method=method,
        status=PaymentStatus.PAID,
        paid_at=when,
    )
