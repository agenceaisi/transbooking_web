"""Tests d'integration du cycle de vie d'une compagnie.

Couvre :
1. Demande de creation -> approbation super admin -> login admin -> creation
   d'un trajet puis d'un voyage.
2. Suspension par le super admin -> l'admin de la compagnie est refuse (403).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from apps.companies.models import Company, CompanyStatus
from apps.routes.models import Route
from apps.trips.models import Trip
from tests.factories import (
    CityFactory,
    CompanyFactory,
    VehicleFactory,
    make_company_admin,
    make_super_admin,
)


def _login(api_client, phone, password="password123") -> str:
    """Log in via the JWT endpoint and return the access token."""
    response = api_client.post(
        "/api/v1/auth/login/", {"phone": phone, "password": password}, format="json"
    )
    assert response.status_code == 200, response.data
    return response.data["access"]


# --------------------------------------------------------------------------- #
# 1. Demande -> approbation -> login -> creation trajet + voyage
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_registration_approval_then_admin_creates_route_and_trip(api_client, sms_outbox):
    # La compagnie soumet sa demande (en attente) avec son futur administrateur.
    company = CompanyFactory(status=CompanyStatus.PENDING)
    admin, company = make_company_admin(company=company, phone="+22670020000")

    # Le super admin approuve la demande.
    super_admin = make_super_admin("+22670020001")
    api_client.force_authenticate(user=super_admin)
    approve = api_client.post(
        f"/api/v1/super/company-requests/{company.id}/approve/"
    )
    assert approve.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.ACTIVE
    api_client.force_authenticate(user=None)

    # L'admin se connecte reellement (JWT) et travaille avec son jeton.
    token = _login(api_client, admin.phone)
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    # Il cree un trajet.
    origin = CityFactory(name="Ouagadougou")
    destination = CityFactory(name="Bobo-Dioulasso")
    route_response = api_client.post(
        "/api/v1/company/routes/",
        {
            "origin_city": origin.id,
            "destination_city": destination.id,
            "distance_km": 360,
            "base_price": 6000,
            "duration_minutes": 300,
        },
        format="json",
    )
    assert route_response.status_code == 201
    route_id = route_response.data["id"]
    route = Route.objects.get(pk=route_id)
    assert route.company == company

    # Puis un voyage sur ce trajet.
    vehicle = VehicleFactory(company=company, total_seats=40)
    trip_response = api_client.post(
        "/api/v1/company/trips/",
        {
            "route": route_id,
            "vehicle": vehicle.id,
            "departure_time": (timezone.now() + timedelta(days=1)).isoformat(),
        },
        format="json",
    )
    assert trip_response.status_code == 201
    trip = Trip.objects.get(pk=trip_response.data["id"])
    assert trip.route == route
    assert trip.available_seats == 40  # initialise depuis la capacite du vehicule
    assert trip.price == 6000  # repris de route.base_price


# --------------------------------------------------------------------------- #
# 2. Suspension -> l'admin de la compagnie est refuse (403)
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_suspended_company_admin_is_forbidden(api_client, sms_outbox):
    admin, company = make_company_admin(phone="+22670021000")
    super_admin = make_super_admin("+22670021001")

    # Avant suspension : l'admin accede a ses parametres.
    api_client.force_authenticate(user=admin)
    assert api_client.get("/api/v1/company/settings/").status_code == 200

    # Le super admin suspend la compagnie.
    api_client.force_authenticate(user=super_admin)
    suspend = api_client.post(
        f"/api/v1/super/companies/{company.id}/suspend/",
        {"reason": "Impayes"},
        format="json",
    )
    assert suspend.status_code == 200
    company.refresh_from_db()
    assert company.status == CompanyStatus.SUSPENDED

    # Apres suspension : l'admin de la compagnie est refuse partout.
    api_client.force_authenticate(user=admin)
    assert api_client.get("/api/v1/company/settings/").status_code == 403
    assert api_client.get("/api/v1/company/dashboard/").status_code == 403

    # La compagnie suspendue disparait aussi de la vitrine publique.
    public = api_client.get("/api/v1/public/companies/")
    assert public.status_code == 200
    assert company.id not in [c["id"] for c in public.data["results"]]
