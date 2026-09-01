"""Fabriques factory_boy partagees pour les tests d'integration.

Ce module reexporte les fabriques par app (source de verite) et ajoute des
helpers de haut niveau pour construire rapidement des acteurs (voyageur,
company_admin, agent, controleur, super_admin) et des scenarios complets
(voyage d'une compagnie, paiement encaisse). Les tests d'integration croisent
plusieurs apps : centraliser ces helpers evite de dupliquer le cablage
role/compagnie/profil dans chaque fichier de test.
"""
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.companies.tests.factories import CompanyFactory
from apps.geography.tests.factories import CityFactory, StationFactory
from apps.parcels.models import ParcelStatus
from apps.parcels.tests.factories import ParcelFactory
from apps.payments.models import PaymentMethod, PaymentStatus
from apps.payments.tests.factories import PaymentFactory
from apps.routes.tests.factories import RouteFactory
from apps.trips.tests.factories import TripFactory
from apps.users.models import AgentProfile, Role, User
from apps.users.tests.factories import UserFactory
from apps.vehicles.tests.factories import VehicleFactory

__all__ = [
    "BookingFactory",
    "CompanyFactory",
    "CityFactory",
    "StationFactory",
    "ParcelFactory",
    "PaymentFactory",
    "RouteFactory",
    "TripFactory",
    "UserFactory",
    "VehicleFactory",
    "ParcelStatus",
    "PaymentMethod",
    "PaymentStatus",
    "BookingStatus",
    "make_user",
    "make_voyageur",
    "make_super_admin",
    "make_company_admin",
    "make_guichet_agent",
    "make_controleur",
    "make_company_trip",
    "make_paid_payment",
]


def make_user(role_name: str, phone: str, password: str = "password123") -> User:
    """Create an authenticated-capable user carrying ``role_name``.

    Args:
        role_name: One of :class:`~apps.users.models.Role.RoleName` values.
        phone: Unique phone number (Burkina format).
        password: Plain password (usable for a real JWT login).

    Returns:
        The persisted user with its role and hashed password.
    """
    role, _ = Role.objects.get_or_create(name=role_name)
    return User.objects.create_user(
        prenom="Test", nom="User", phone=phone, password=password, role=role
    )


def make_voyageur(phone: str = "+22670003000") -> User:
    """Create a voyageur user."""
    return make_user(Role.RoleName.VOYAGEUR, phone)


def make_super_admin(phone: str = "+22670002000") -> User:
    """Create a super_admin user."""
    return make_user(Role.RoleName.SUPER_ADMIN, phone)


def make_company_admin(company=None, phone: str = "+22670001000"):
    """Create a company_admin wired to ``company`` via ``admin_user``.

    Args:
        company: An existing company, or ``None`` to create one.
        phone: Unique phone number for the admin.

    Returns:
        A ``(admin, company)`` tuple.
    """
    admin = make_user(Role.RoleName.COMPANY_ADMIN, phone)
    company = company or CompanyFactory()
    company.admin_user = admin
    company.save(update_fields=["admin_user", "updated_at"])
    return admin, company


def make_guichet_agent(company, station=None, phone: str = "+22670009000") -> User:
    """Create an agent guichet bound to ``company`` with its profile."""
    agent = make_user(Role.RoleName.AGENT_GUICHET, phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.GUICHET,
        station=station,
    )
    return agent


def make_controleur(company, phone: str = "+22670008000") -> User:
    """Create a controleur bound to ``company`` with its profile."""
    agent = make_user(Role.RoleName.CONTROLEUR, phone)
    AgentProfile.objects.create(
        user=agent,
        company=company,
        agent_type=AgentProfile.AgentType.CONTROLEUR,
    )
    return agent


def make_company_trip(company=None, total_seats: int = 30, **trip_kwargs):
    """Create a trip whose route and vehicle belong to ``company``.

    Args:
        company: The owning company, or ``None`` to create one.
        total_seats: Vehicle capacity (also seeds ``available_seats``).
        **trip_kwargs: Overrides forwarded to :class:`TripFactory`.

    Returns:
        The created trip.
    """
    company = company or CompanyFactory()
    route = trip_kwargs.pop("route", None) or RouteFactory(company=company)
    vehicle = VehicleFactory(company=company, total_seats=total_seats)
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

    Args:
        company: The owning company.
        amount: Booking/payment amount in FCFA.
        commission: Frozen platform commission.
        method: Payment method.
        when: ``paid_at`` timestamp (defaults to now).
        trip: An existing trip, or ``None`` to create one.
        agent: The agent who collected the payment, or ``None``.

    Returns:
        The created :class:`~apps.payments.models.Payment`.
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
