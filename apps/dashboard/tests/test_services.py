from datetime import date, timedelta

import pytest
from django.utils import timezone

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.claims.models import ClaimStatus
from apps.claims.tests.factories import ClaimFactory
from apps.companies.tests.factories import CompanyFactory
from apps.dashboard import services
from apps.geography.tests.factories import StationFactory
from apps.parcels.models import ParcelStatus
from apps.parcels.tests.factories import ParcelFactory
from apps.payments.models import PaymentMethod, PaymentStatus
from apps.payments.tests.factories import PaymentFactory
from apps.reviews.tests.factories import ReviewFactory
from apps.routes.tests.factories import RouteFactory
from apps.speed_reports.tests.factories import SpeedReportFactory
from apps.trips.tests.factories import TripFactory
from apps.users.models import Role
from apps.users.tests.factories import UserFactory
from apps.vehicles.tests.factories import VehicleFactory

from .factories import (
    make_agent,
    make_company_admin,
    make_company_trip,
    make_paid_payment,
    make_voyageur,
)


@pytest.mark.django_db
class TestResolvePeriod:
    def test_today_window_is_one_day(self):
        period = services.resolve_period("today")
        assert (period.end - period.start) == timedelta(days=1)
        # La fenetre de comparaison est la veille, de meme duree.
        assert period.previous_end == period.start
        assert (period.previous_start - period.previous_end) == -timedelta(days=1)

    def test_custom_requires_both_bounds(self):
        with pytest.raises(ValueError):
            services.resolve_period("custom", start_date=date(2026, 1, 1))

    def test_custom_includes_full_end_day(self):
        period = services.resolve_period(
            "custom",
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 7),
        )
        # 7 jours pleins (borne haute exclusive au 8 janvier).
        assert (period.end - period.start) == timedelta(days=7)

    def test_year_groups_by_week(self):
        period = services.resolve_period("year")
        assert period.group_by_week is True


@pytest.mark.django_db
class TestCompanyOverview:
    def test_revenue_sums_only_paid_payments_of_company(self):
        admin, company = make_company_admin()
        make_paid_payment(company, amount=5000)
        make_paid_payment(company, amount=3000)
        # Paiement d'une autre compagnie : ne doit pas etre compte.
        _, other = make_company_admin(phone="+22670009999")
        make_paid_payment(other, amount=99999)
        # Paiement en attente : exclu.
        trip = make_company_trip(company)
        booking = BookingFactory(trip=trip, amount=7000, status=BookingStatus.PAID)
        PaymentFactory(
            booking=booking, amount=7000, status=PaymentStatus.PENDING
        )

        period = services.resolve_period("month")
        overview = services.company_overview(company, period)

        assert overview["revenue_total"] == 8000.0

    def test_delta_against_previous_period(self):
        _, company = make_company_admin()
        now = timezone.now()
        make_paid_payment(company, amount=5000, when=now)
        # Recette de la periode precedente (mois dernier).
        period = services.resolve_period("month")
        make_paid_payment(
            company, amount=2000, when=period.previous_start + timedelta(days=1)
        )

        overview = services.company_overview(company, period)

        assert overview["revenue_total"] == 5000.0
        assert overview["vs_previous_period"]["revenue_total"] == 3000.0

    def test_avg_rating_is_null_without_reviews(self):
        _, company = make_company_admin()
        overview = services.company_overview(
            company, services.resolve_period("month")
        )
        assert overview["avg_rating"] is None

    def test_fill_rate_avg(self):
        _, company = make_company_admin()
        trip = make_company_trip(company, total_seats=10)
        # 4 reservations actives sur 10 sieges => 40 %.
        for _ in range(4):
            BookingFactory(trip=trip, status=BookingStatus.PAID)
        # Une annulee ne compte pas.
        BookingFactory(trip=trip, status=BookingStatus.CANCELLED)

        overview = services.company_overview(
            company, services.resolve_period("month")
        )
        assert overview["fill_rate_avg"] == 40.0


@pytest.mark.django_db
class TestCompanyBreakdowns:
    def test_payment_breakdown_percentages_sum_to_100(self):
        _, company = make_company_admin()
        make_paid_payment(company, amount=6000, method=PaymentMethod.CASH)
        make_paid_payment(
            company, amount=4000, method=PaymentMethod.ORANGE_MONEY
        )

        breakdown = services.company_payment_breakdown(
            company, services.resolve_period("month")
        )

        assert sum(row["pct"] for row in breakdown) == 100.0
        cash = next(r for r in breakdown if r["method"] == "cash")
        assert cash["pct"] == 60.0

    def test_top_routes_limited_to_five(self):
        _, company = make_company_admin()
        for _ in range(6):
            make_paid_payment(company, amount=1000)
        routes = services.company_top_routes(
            company, services.resolve_period("month")
        )
        assert len(routes) == 5

    def test_alerts_counts(self):
        _, company = make_company_admin()
        ClaimFactory(company=company, status=ClaimStatus.SUBMITTED)
        ClaimFactory(company=company, status=ClaimStatus.RESOLVED)
        ParcelFactory(company=company, status=ParcelStatus.ARRIVED)
        ParcelFactory(company=company, status=ParcelStatus.COLLECTED)
        SpeedReportFactory(company=company)

        alerts = services.company_alerts(company)

        assert alerts["unresolved_claims"] == 1
        assert alerts["unreturned_parcels"] == 1
        assert alerts["speed_reports_pending"] == 1


@pytest.mark.django_db
class TestAgentActivity:
    def test_agent_activity_counts_today(self):
        _, company = make_company_admin()
        agent = make_agent(company)
        trip = make_company_trip(company)
        BookingFactory(trip=trip, agent=agent, status=BookingStatus.PAID)
        BookingFactory(trip=trip, agent=agent, status=BookingStatus.PAID)
        ParcelFactory(company=company, registered_by=agent)

        activity = services.company_agent_activity(company)

        assert len(activity) == 1
        assert activity[0]["bookings_today"] == 2
        assert activity[0]["parcels_today"] == 1


@pytest.mark.django_db
class TestTravelerDashboard:
    def test_counts_and_next_trips(self):
        voyageur = make_voyageur()
        _, company = make_company_admin()
        trip = make_company_trip(
            company, departure_time=timezone.now() + timedelta(days=2)
        )
        BookingFactory(trip=trip, user=voyageur, status=BookingStatus.PAID)
        BookingFactory(
            trip=make_company_trip(company),
            user=voyageur,
            status=BookingStatus.PENDING,
        )

        data = services.traveler_dashboard(voyageur)

        assert data["active_bookings_count"] == 1
        assert data["pending_count"] == 1
        assert len(data["next_trips"]) >= 1
        assert data["recent_notifications"] == []

    def test_next_trips_carry_company(self):
        voyageur = make_voyageur()
        _, company = make_company_admin()
        company.name = "Faso Express"
        company.sigle = "FE"
        company.save(update_fields=["name", "sigle"])
        trip = make_company_trip(
            company, departure_time=timezone.now() + timedelta(days=2)
        )
        BookingFactory(trip=trip, user=voyageur, status=BookingStatus.PAID)

        data = services.traveler_dashboard(voyageur)

        assert data["next_trips"][0]["company_name"] == "Faso Express"
        assert data["next_trips"][0]["company_sigle"] == "FE"

    def test_paid_and_cancelled_counters(self):
        voyageur = make_voyageur()
        _, company = make_company_admin()
        trip = make_company_trip(company)
        BookingFactory(trip=trip, user=voyageur, status=BookingStatus.PAID)
        BookingFactory(trip=trip, user=voyageur, status=BookingStatus.CANCELLED)
        BookingFactory(trip=trip, user=voyageur, status=BookingStatus.REFUNDED)

        data = services.traveler_dashboard(voyageur)

        assert data["paid_count"] == 1
        # Annules = annule (1) + rembourse (1).
        assert data["cancelled_count"] == 2

    def test_recent_notifications_carry_type(self):
        from apps.notifications.models import NotificationType
        from apps.notifications.tests.factories import NotificationFactory

        voyageur = make_voyageur()
        NotificationFactory(user=voyageur, type=NotificationType.BOOKING)

        data = services.traveler_dashboard(voyageur)

        assert data["recent_notifications"][0]["type"] == "booking"
        assert data["recent_notifications"][0]["type_display"] == "Reservation"


@pytest.mark.django_db
class TestAgentDashboard:
    def test_next_departures_carry_vehicle_type_and_total_seats(self):
        company = CompanyFactory()
        agent = make_agent(company)
        trip = make_company_trip(
            company,
            total_seats=25,
            departure_time=timezone.now() + timedelta(hours=2),
        )
        trip.vehicle.vehicle_type = "vip"
        trip.vehicle.save(update_fields=["vehicle_type"])

        data = services.agent_dashboard(agent)

        departure = data["next_departures"][0]
        assert departure["vehicle_type"] == "vip"
        assert departure["total_seats"] == 25

    def test_today_stats_counts_passengers_parcels_and_departures(self):
        company = CompanyFactory()
        route = RouteFactory(company=company)
        station = StationFactory(company=company, city=route.origin_city)
        route.origin_station = station
        route.save(update_fields=["origin_station"])
        agent = make_agent(company, station=station)
        vehicle = VehicleFactory(company=company, total_seats=30)
        trip = TripFactory(route=route, vehicle=vehicle, departure_time=timezone.now())
        BookingFactory(trip=trip, status=BookingStatus.PAID)
        BookingFactory(trip=trip, status=BookingStatus.CANCELLED)
        ParcelFactory(company=company, origin_station=station)

        data = services.agent_dashboard(agent)

        stats = data["today_stats"]
        assert stats["passengers_registered"] == 1
        assert stats["parcels_registered"] == 1
        assert stats["upcoming_departures"] == 1
        assert stats["passengers_registered_yesterday"] == 0

    def test_today_stats_defaults_to_zero_without_agent_profile(self):
        role, _ = Role.objects.get_or_create(name=Role.RoleName.AGENT_GUICHET)
        agent = UserFactory(role=role, phone="+22670006000")

        data = services.agent_dashboard(agent)

        assert data["today_stats"]["passengers_registered"] == 0
        assert data["next_departures"] == []


@pytest.mark.django_db
class TestSuperOverview:
    def test_commission_revenue_sums_paid_payments(self):
        _, company_a = make_company_admin()
        _, company_b = make_company_admin(phone="+22670008888")
        make_paid_payment(company_a, amount=5000, commission=500)
        make_paid_payment(company_b, amount=3000, commission=300)

        overview = services.super_overview()

        assert overview["total_commission_revenue"] == 800.0
        assert overview["total_companies"] >= 2
