from datetime import timedelta

import pytest
from django.core.cache import cache
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.bookings.models import BookingStatus
from apps.bookings.tests.factories import BookingFactory

from .factories import (
    make_agent,
    make_company_admin,
    make_company_trip,
    make_paid_payment,
    make_super_admin,
    make_voyageur,
)


@pytest.fixture
def api_client():
    return APIClient()


@pytest.fixture(autouse=True)
def _clear_cache():
    """Vide le cache entre chaque test (cache_page partage en LocMem)."""
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_traveler_dashboard_returns_counts(api_client):
    voyageur = make_voyageur()
    _, company = make_company_admin()
    trip = make_company_trip(company)
    BookingFactory(trip=trip, user=voyageur, status=BookingStatus.PAID)
    api_client.force_authenticate(user=voyageur)

    response = api_client.get("/api/v1/dashboard/traveler/")

    assert response.status_code == 200
    assert response.data["active_bookings_count"] == 1
    assert "recent_notifications" in response.data


@pytest.mark.django_db
def test_agent_dashboard_returns_departures(api_client):
    _, company = make_company_admin()
    agent = make_agent(company)
    make_company_trip(company)
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/agent/dashboard/")

    assert response.status_code == 200
    assert "next_departures" in response.data
    assert response.data["connection_status"] == "online"
    assert "today_stats" in response.data
    assert response.data["today_stats"]["passengers_registered"] >= 0


@pytest.mark.django_db
def test_agent_dashboard_departures_expose_registration_closes_at(api_client):
    _, company = make_company_admin()
    agent = make_agent(company)
    trip = make_company_trip(
        company, departure_time=timezone.now() + timedelta(hours=1)
    )
    api_client.force_authenticate(user=agent)

    response = api_client.get("/api/v1/agent/dashboard/")

    assert response.status_code == 200
    departure = response.data["next_departures"][0]
    assert parse_datetime(departure["registration_closes_at"]) == trip.departure_time


@pytest.mark.django_db
def test_company_dashboard_returns_revenue(api_client):
    admin, company = make_company_admin()
    make_paid_payment(company, amount=5000)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/dashboard/")

    assert response.status_code == 200
    assert response.data["revenue_total"] == 5000.0


@pytest.mark.django_db
def test_company_dashboard_isolates_tenants(api_client):
    """L'admin de la compagnie A ne voit jamais les recettes de la compagnie B."""
    admin_a, company_a = make_company_admin(phone="+22670001111")
    _, company_b = make_company_admin(phone="+22670002222")
    make_paid_payment(company_b, amount=12345)
    api_client.force_authenticate(user=admin_a)

    response = api_client.get("/api/v1/company/dashboard/")

    assert response.status_code == 200
    assert response.data["revenue_total"] == 0.0


@pytest.mark.django_db
def test_voyageur_cannot_access_company_dashboard(api_client):
    voyageur = make_voyageur()
    api_client.force_authenticate(user=voyageur)

    response = api_client.get("/api/v1/company/dashboard/")

    assert response.status_code == 403


@pytest.mark.django_db
def test_company_dashboard_export_excel(api_client):
    admin, company = make_company_admin()
    make_paid_payment(company, amount=5000)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/dashboard/export/?format=excel")

    assert response.status_code == 200
    assert "spreadsheetml" in response["Content-Type"]
    assert response["Content-Disposition"].endswith('dashboard.xlsx"')


@pytest.mark.django_db
@pytest.mark.parametrize(
    "path",
    [
        "/api/v1/company/dashboard/revenue-chart/",
        "/api/v1/company/dashboard/fill-rate-by-route/",
        "/api/v1/company/dashboard/payment-breakdown/",
        "/api/v1/company/dashboard/top-routes/",
        "/api/v1/company/dashboard/agent-activity/",
        "/api/v1/company/dashboard/alerts/",
    ],
)
def test_company_dashboard_sub_endpoints_ok(api_client, path):
    admin, company = make_company_admin()
    agent = make_agent(company)
    make_paid_payment(company, amount=5000, agent=agent)
    api_client.force_authenticate(user=admin)

    response = api_client.get(path)

    assert response.status_code == 200


@pytest.mark.django_db
def test_company_dashboard_export_pdf(api_client):
    admin, company = make_company_admin()
    make_paid_payment(company, amount=5000)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/dashboard/export/?format=pdf")

    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"


@pytest.mark.django_db
def test_super_bookings_chart_ok(api_client):
    admin = make_super_admin()
    _, company = make_company_admin()
    trip = make_company_trip(company)
    BookingFactory(trip=trip, status=BookingStatus.PAID)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/super/dashboard/bookings-chart/")

    assert response.status_code == 200


@pytest.mark.django_db
def test_company_dashboard_invalid_custom_period(api_client):
    admin, _ = make_company_admin()
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/company/dashboard/?period=custom")

    assert response.status_code == 400


@pytest.mark.django_db
def test_super_dashboard_returns_totals(api_client):
    admin = make_super_admin()
    _, company = make_company_admin()
    make_paid_payment(company, amount=5000, commission=500)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/super/dashboard/")

    assert response.status_code == 200
    assert response.data["total_commission_revenue"] == 500.0


@pytest.mark.django_db
def test_super_revenue_by_company(api_client):
    admin = make_super_admin()
    _, company = make_company_admin()
    make_paid_payment(company, amount=5000, commission=500)
    api_client.force_authenticate(user=admin)

    response = api_client.get("/api/v1/super/dashboard/revenue-by-company/")

    assert response.status_code == 200
    assert response.data[0]["revenue"] == 5000.0
    assert response.data[0]["commission"] == 500.0


@pytest.mark.django_db
def test_company_dashboard_requires_auth(api_client):
    response = api_client.get("/api/v1/company/dashboard/")
    assert response.status_code in (401, 403)
