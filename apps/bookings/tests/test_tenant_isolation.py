"""Preuve d'isolation multi-tenant (audit V03).

Ce module PROUVE qu'aucune donnee d'une compagnie n'est accessible depuis le
compte d'une autre compagnie, meme en connaissant un `id` valide (cf.
`docs/specs/security.md` §3 et CLAUDE.md « isolation multi-tenant stricte »).

Scenario general :
1. On construit deux mondes complets et etanches (Compagnie A et Compagnie B),
   chacun avec un `company_admin`, un `agent_guichet`, un `controleur`, une gare,
   un trajet, un vehicule, un voyage, une reservation et un colis.
2. On s'authentifie reellement (JWT) en tant qu'acteur de la Compagnie A.
3. On tente d'atteindre chaque ressource de la Compagnie B via son `id`.
4. Toute tentative croisee DOIT renvoyer 403 ou 404 — jamais 200 avec les
   donnees de B. Des controles positifs verifient que l'acces intra-compagnie
   fonctionne, pour garantir que le 404 traduit bien l'isolation et non une
   panne globale.

Placement : ce test transverse est loge dans l'app `bookings`, ressource
multi-tenant de reference dans `docs/specs/security.md`.
"""
from dataclasses import dataclass

import pytest
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.companies.models import Company
from apps.parcels.models import Parcel
from apps.routes.models import Route
from apps.trips.models import Trip
from apps.users.models import User
from apps.vehicles.models import Vehicle
from tests.factories import (
    BookingFactory,
    CompanyFactory,
    ParcelFactory,
    StationFactory,
    make_company_admin,
    make_company_trip,
    make_controleur,
    make_guichet_agent,
    make_paid_payment,
)

# Tout module qui a fait ``from utils.sms import send_sms`` garde sa propre
# reference : on neutralise chacun pour ne jamais toucher un vrai fournisseur.
_SMS_TARGETS = [
    "apps.bookings.services.send_sms",
    "apps.bookings.tasks.send_sms",
    "apps.parcels.services.send_sms",
    "apps.parcels.tasks.send_sms",
    "apps.payments.services.send_sms",
    "apps.companies.services.send_sms",
]


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def _mute_sms(monkeypatch):
    for target in _SMS_TARGETS:
        monkeypatch.setattr(target, lambda *a, **k: None)


@pytest.fixture(autouse=True)
def _clear_cache():
    # Les tableaux de bord utilisent ``cache_page`` : on isole chaque test.
    from django.core.cache import cache

    cache.clear()
    yield
    cache.clear()


# --------------------------------------------------------------------------- #
# Construction d'un « monde » etanche par compagnie
# --------------------------------------------------------------------------- #
@dataclass
class CompanyWorld:
    company: Company
    admin: User
    agent: User
    controleur: User
    station: object
    route: Route
    vehicle: Vehicle
    trip: Trip
    booking: Booking
    parcel: Parcel


def build_world(prefix: int) -> CompanyWorld:
    """Cree une compagnie active et tout son graphe d'objets isolables.

    Args:
        prefix: Entier (1, 2, ...) rendant uniques les numeros de telephone
            (format burkinabe +226XXXXXXXX) des acteurs de ce monde.

    Returns:
        Le :class:`CompanyWorld` complet et persiste.
    """
    company = CompanyFactory()
    admin, company = make_company_admin(
        company=company, phone=f"+2267{prefix}000001"
    )
    station = StationFactory(company=company)
    agent = make_guichet_agent(
        company, station=station, phone=f"+2267{prefix}000002"
    )
    controleur = make_controleur(company, phone=f"+2267{prefix}000003")

    trip = make_company_trip(company=company, total_seats=30)
    booking = BookingFactory(trip=trip)
    parcel = ParcelFactory(company=company, destination_station=station)

    return CompanyWorld(
        company=company,
        admin=admin,
        agent=agent,
        controleur=controleur,
        station=station,
        route=trip.route,
        vehicle=trip.vehicle,
        trip=trip,
        booking=booking,
        parcel=parcel,
    )


def _auth(api_client: APIClient, user: User) -> None:
    """Authentifie ``user`` via un vrai jeton JWT Bearer.

    On passe par ``/auth/login/`` (et non ``force_authenticate``) pour que
    l'en-tete ``Authorization`` soit present : les tableaux de bord sont mis en
    cache avec ``vary_on_headers("Authorization")`` — un vrai jeton garantit
    qu'aucune reponse en cache n'est partagee entre deux compagnies.
    """
    response = api_client.post(
        "/api/v1/auth/login/",
        {"phone": user.phone, "password": "password123"},
        format="json",
    )
    assert response.status_code == 200, response.data
    api_client.credentials(HTTP_AUTHORIZATION=f"Bearer {response.data['access']}")


def _assert_no_leak(response, forbidden_marker: str) -> None:
    """Verifie qu'une reponse ne fuit jamais une donnee de l'autre compagnie."""
    assert response.status_code in (403, 404), (
        f"FUITE MULTI-TENANT : statut {response.status_code} attendu 403/404. "
        f"Corps : {getattr(response, 'data', response.content)!r}"
    )
    body = response.content.decode(errors="ignore")
    assert forbidden_marker not in body, (
        f"FUITE MULTI-TENANT : la donnee '{forbidden_marker}' apparait dans la "
        f"reponse {response.request['PATH_INFO']}."
    )


# --------------------------------------------------------------------------- #
# 1. company_admin — ressources CRUD scopees par compagnie
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_admin_cannot_touch_other_company_resources(api_client):
    """A's admin ne peut ni lire, ni modifier, ni supprimer les objets de B."""
    world_a = build_world(1)
    world_b = build_world(2)
    _auth(api_client, world_a.admin)

    # (url, marqueur unique de B qui ne doit JAMAIS apparaitre dans la reponse)
    detail_targets = [
        (f"/api/v1/company/routes/{world_b.route.id}/", str(world_b.route.distance_km)),
        (f"/api/v1/company/vehicles/{world_b.vehicle.id}/", world_b.vehicle.registration),
        (f"/api/v1/company/trips/{world_b.trip.id}/", str(world_b.trip.id)),
        (f"/api/v1/company/stations/{world_b.station.id}/", world_b.station.name),
    ]
    for url, marker in detail_targets:
        for method in ("get", "patch", "delete"):
            response = getattr(api_client, method)(url, {}, format="json")
            _assert_no_leak(response, marker)

    # Le colis admin n'expose que GET/PATCH (pas de suppression cote API).
    parcel_url = f"/api/v1/company/parcels/{world_b.parcel.id}/"
    for method in ("get", "patch"):
        response = getattr(api_client, method)(parcel_url, {}, format="json")
        _assert_no_leak(response, world_b.parcel.tracking_number)

    # Controle positif : l'admin de A accede bien a SES propres objets.
    own = api_client.get(f"/api/v1/company/routes/{world_a.route.id}/")
    assert own.status_code == 200
    assert own.data["id"] == world_a.route.id


@pytest.mark.django_db
def test_company_bookings_list_never_shows_other_company(api_client):
    """La liste des reservations de A n'inclut jamais celle de B, et le detail
    d'une reservation de B est introuvable."""
    world_a = build_world(1)
    world_b = build_world(2)
    _auth(api_client, world_a.admin)

    listing = api_client.get("/api/v1/company/bookings/")
    assert listing.status_code == 200
    tickets = [row["ticket_number"] for row in listing.data["results"]]
    assert world_a.booking.ticket_number in tickets
    assert world_b.booking.ticket_number not in tickets

    # Aucune route de detail n'est exposee (viewset liste seule) -> 404.
    detail = api_client.get(f"/api/v1/company/bookings/{world_b.booking.id}/")
    assert detail.status_code == 404


@pytest.mark.django_db
def test_company_agents_management_endpoint_is_absent(api_client):
    """Aucun endpoint /company/agents/{id}/ n'est implemente : l'URL ne resout
    pas (404). Aucune fuite possible faute de surface d'attaque."""
    world_a = build_world(1)
    world_b = build_world(2)
    _auth(api_client, world_a.admin)

    response = api_client.get(f"/api/v1/company/agents/{world_b.agent.id}/")
    assert response.status_code == 404
    body = response.content.decode(errors="ignore")
    assert world_b.agent.phone not in body


@pytest.mark.django_db
def test_company_dashboard_reflects_only_own_figures(api_client):
    """Le tableau de bord de A ne compte que les chiffres de A (jamais B)."""
    company_a = CompanyFactory()
    admin_a, company_a = make_company_admin(
        company=company_a, phone="+22671000001"
    )
    company_b = CompanyFactory()

    # A : 3 paiements encaisses (3 reservations, 15 000 FCFA).
    for _ in range(3):
        make_paid_payment(company_a, amount=5000)
    # B : 2 paiements encaisses (10 000 FCFA) — ne doivent jamais compter pour A.
    for _ in range(2):
        make_paid_payment(company_b, amount=5000)

    _auth(api_client, admin_a)
    response = api_client.get("/api/v1/company/dashboard/")
    assert response.status_code == 200
    # Isolation stricte : uniquement les 3 reservations et 15 000 FCFA de A.
    assert response.data["bookings_count"] == 3
    assert response.data["revenue_total"] == 15000.0


# --------------------------------------------------------------------------- #
# 2. agent_guichet — perimetre par compagnie via le profil agent
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_agent_guichet_cannot_reach_other_company_data(api_client):
    """L'agent de A ne voit ni le colis, ni le billet, ni les gares/vehicules de B."""
    world_a = build_world(1)
    world_b = build_world(2)
    _auth(api_client, world_a.agent)

    # Colis de B via son id -> hors perimetre.
    parcel = api_client.get(f"/api/v1/agent/parcels/{world_b.parcel.id}/")
    _assert_no_leak(parcel, world_b.parcel.tracking_number)

    # Billet de B via son ticket_number -> hors perimetre.
    ticket = api_client.get(
        f"/api/v1/agent/bookings/{world_b.booking.ticket_number}/"
    )
    _assert_no_leak(ticket, world_b.booking.passenger_name)

    # Les gares et vehicules sont reserves au company_admin : mauvais role -> 403.
    assert (
        api_client.get(f"/api/v1/company/stations/{world_b.station.id}/").status_code
        == 403
    )
    assert (
        api_client.get(f"/api/v1/company/vehicles/{world_b.vehicle.id}/").status_code
        == 403
    )

    # Controle positif : l'agent de A accede a SON propre colis.
    own = api_client.get(f"/api/v1/agent/parcels/{world_a.parcel.id}/")
    assert own.status_code == 200
    assert own.data["tracking_number"] == world_a.parcel.tracking_number


# --------------------------------------------------------------------------- #
# 3. controleur — scan et embarquement scopes par compagnie
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_controleur_cannot_scan_or_board_other_company(api_client):
    """Le controleur de A ne peut ni scanner, ni embarquer les billets/voyages de B."""
    world_a = build_world(1)
    world_b = build_world(2)
    _auth(api_client, world_a.controleur)

    # Scan du billet de B -> introuvable dans le perimetre de A.
    scan = api_client.post(
        "/api/v1/agent/scan/",
        {"ticket_number": world_b.booking.ticket_number},
        format="json",
    )
    _assert_no_leak(scan, world_b.booking.passenger_name)

    # Verrouillage d'embarquement sur le voyage de B -> voyage introuvable.
    validate = api_client.post(
        f"/api/v1/agent/trips/{world_b.trip.id}/boarding/validate/", {}, format="json"
    )
    assert validate.status_code == 404

    # Pointage d'un passager de B sur le voyage de B -> introuvable.
    checkin = api_client.post(
        f"/api/v1/agent/trips/{world_b.trip.id}/boarding/{world_b.booking.id}/",
        {},
        format="json",
    )
    assert checkin.status_code == 404

    # Controle positif : le controleur de A scanne bien SON propre billet.
    own = api_client.post(
        "/api/v1/agent/scan/",
        {"ticket_number": world_a.booking.ticket_number},
        format="json",
    )
    assert own.status_code == 200
    assert own.data["booking"]["ticket_number"] == world_a.booking.ticket_number
