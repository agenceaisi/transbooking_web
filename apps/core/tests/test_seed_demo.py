"""Tests de la commande de peuplement `seed_demo`.

Le jeu de donnees complet represente ~1200 reservations : pour rester rapide,
les tests reduisent les volumes en patchant les constantes de volumetrie du
module (fenetre temporelle et taux de remplissage). La structure verifiee reste
celle de la commande reelle : memes fonctions de seed, memes services metier.

Les assertions sont regroupees par domaine plutot qu'eclatees en un test par
verification : chaque test declenche un seed complet, les multiplier couterait
plusieurs minutes de suite de tests.
"""

from datetime import timedelta
from decimal import Decimal
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.claims.models import UNRESOLVED_STATUSES, Claim
from apps.companies.models import Company, CompanyStatus
from apps.core.management.commands import seed_demo as seed_module
from apps.core.models import ActivityLog
from apps.notifications.models import Notification
from apps.parcels.models import Parcel, ParcelStatus
from apps.payments.models import Payment, PaymentStatus
from apps.reviews.models import Review
from apps.speed_reports.models import SpeedReport
from apps.subscriptions.models import Subscription, SubscriptionStatus
from apps.trips.models import Trip
from apps.users.models import User
from apps.vehicles.models import Vehicle

pytestmark = pytest.mark.django_db


# Volumetrie reduite : quelques dizaines de reservations au lieu de ~1200.
# Le creneau « voyage complet » (1.00) est conserve, c'est lui qui produit un
# voyage sans siege disponible.
LIGHT_TODAY_PLAN = [
    (Trip.TripStatus.COMPLETED, Decimal("0.15"), 0),
    (Trip.TripStatus.COMPLETED, Decimal("0.12"), 0),
    (Trip.TripStatus.IN_PROGRESS, Decimal("0.15"), 0),
    (Trip.TripStatus.DELAYED, Decimal("0.12"), 45),
    (Trip.TripStatus.CANCELLED, Decimal("0.10"), 0),
    (Trip.TripStatus.SCHEDULED, Decimal("1.00"), 0),
    (Trip.TripStatus.SCHEDULED, Decimal("0.10"), 0),
    (Trip.TripStatus.SCHEDULED, Decimal("0.10"), 0),
]


@pytest.fixture
def light_volumes(monkeypatch):
    """Reduit la volumetrie du seed pour garder les tests rapides."""
    monkeypatch.setattr(seed_module, "PAST_DAYS", 6)
    monkeypatch.setattr(seed_module, "FUTURE_DAYS", 4)
    monkeypatch.setattr(seed_module, "TODAY_PLAN", LIGHT_TODAY_PLAN)
    monkeypatch.setattr(seed_module, "SECOND_COMPANY_FILL", Decimal("0.12"))
    monkeypatch.setattr(
        seed_module,
        "FILL_RATES",
        [Decimal("0.10"), Decimal("0.15"), Decimal("0.12"), Decimal("0.18"), Decimal("0.10")],
    )


def run_seed(**options) -> str:
    """Execute la commande et retourne sa sortie standard."""
    out = StringIO()
    call_command("seed_demo", stdout=out, **options)
    return out.getvalue()


@pytest.fixture
def seeded(light_volumes):
    """Execute le seed une fois, en levant le garde-fou DEBUG."""
    with override_settings(DEBUG=True):
        return run_seed(seed=42)


# ---------------------------------------------------------------------------
# Garde-fous et rejouabilite
# ---------------------------------------------------------------------------


@override_settings(DEBUG=False)
def test_refuse_de_sexecuter_hors_debug():
    """Sans --force, la commande refuse de toucher a une base hors DEBUG."""
    with pytest.raises(CommandError, match="DEBUG=False"):
        run_seed()

    assert Company.objects.count() == 0, "aucune ecriture ne doit avoir eu lieu"


@override_settings(DEBUG=False)
def test_force_leve_le_garde_fou(light_volumes):
    """--force autorise explicitement l'execution hors DEBUG."""
    run_seed(seed=42, force=True)

    assert Company.objects.exists()


def test_idempotent_et_reset(seeded):
    """Relancer sans --reset ne cree aucun doublon ; --reset regenere le jeu."""
    suivis = (
        Company, User, Vehicle, Trip, Booking, Payment,
        Parcel, Review, Claim, SpeedReport, Subscription,
    )
    avant = {model: model.objects.count() for model in suivis}
    assert all(count > 0 for count in avant.values())

    with override_settings(DEBUG=True):
        run_seed(seed=42)

    for model, count in avant.items():
        assert model.objects.count() == count, f"{model.__name__} duplique"

    # --reset purge puis reconstruit un jeu equivalent.
    with override_settings(DEBUG=True):
        run_seed(seed=42, reset=True)

    assert Company.objects.filter(status=CompanyStatus.ACTIVE).count() == 2
    assert User.objects.filter(role__name="voyageur").count() == 5
    assert Trip.objects.count() == avant[Trip]


# ---------------------------------------------------------------------------
# Comptes, compagnies, abonnements
# ---------------------------------------------------------------------------


def test_comptes_de_tous_les_roles(seeded):
    """Chaque role dispose d'un compte connectable avec le mot de passe affiche."""
    for role in ("super_admin", "company_admin", "agent_guichet", "controleur", "voyageur"):
        assert User.objects.filter(role__name=role).exists(), role
        assert role in seeded, f"{role} absent du recapitulatif"

    assert User.objects.filter(role__name="voyageur").count() == 5

    super_admin = User.objects.get(phone="+22670000001")
    assert super_admin.check_password("Demo1234!")
    assert "Demo1234!" in seeded and "+22670000001" in seeded
    assert "COMPTES DE DEMONSTRATION" in seeded and "VOLUMES CREES" in seeded

    # Les deux agents guichet de la compagnie principale tiennent des gares
    # differentes (indispensable pour tester le filtrage par gare).
    stations = User.objects.filter(
        role__name="agent_guichet", agent_profile__company__name__startswith="Rakieta"
    ).values_list("agent_profile__station_id", flat=True)
    assert len(set(stations)) == 2


def test_compagnies_demandes_et_abonnements(seeded):
    """Statuts de compagnie, demandes en instruction et etats d'abonnement."""
    assert Company.objects.filter(status=CompanyStatus.ACTIVE).count() == 2
    assert Company.objects.filter(status=CompanyStatus.SUSPENDED).count() == 1
    assert Company.objects.filter(status=CompanyStatus.PENDING).count() == 2
    assert Company.objects.filter(status=CompanyStatus.INFO_REQUESTED).count() == 1

    assert Company.objects.get(status=CompanyStatus.SUSPENDED).suspension_reason
    assert Company.objects.get(status=CompanyStatus.INFO_REQUESTED).info_request_message

    today = timezone.localdate()
    assert Subscription.objects.filter(status=SubscriptionStatus.EXPIRED).exists()
    assert Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        end_date__range=(today, today + timedelta(days=7)),
    ).exists(), "aucun abonnement proche de l'expiration"
    assert Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE, end_date__gt=today + timedelta(days=30)
    ).exists()


def test_isolation_multi_tenant(seeded):
    """Chaque compagnie active a sa propre flotte, ses gares et ses voyages."""
    principale, seconde = Company.objects.filter(status=CompanyStatus.ACTIVE).order_by("name")

    for company in (principale, seconde):
        assert company.vehicles.exists()
        assert company.stations.exists()
        assert Trip.objects.filter(route__company=company).exists()

    assert not set(principale.vehicles.values_list("pk", flat=True)) & set(
        seconde.vehicles.values_list("pk", flat=True)
    )
    assert not set(principale.stations.values_list("pk", flat=True)) & set(
        seconde.stations.values_list("pk", flat=True)
    )


# ---------------------------------------------------------------------------
# Offre de transport
# ---------------------------------------------------------------------------


def test_flotte_et_fenetre_de_voyages(seeded):
    """Flotte avec un vehicule immobilise, fenetre couvrant passe et avenir."""
    en_maintenance = Vehicle.objects.filter(status=Vehicle.VehicleStatus.MAINTENANCE)
    assert en_maintenance.count() == 1
    assert not Trip.objects.filter(vehicle__in=en_maintenance).exists()
    assert all(v.seat_plan.get("layout") for v in Vehicle.objects.all())

    now = timezone.now()
    assert Trip.objects.filter(departure_time__lt=now).exists()
    assert Trip.objects.filter(departure_time__gt=now).exists()
    assert Trip.objects.filter(status=Trip.TripStatus.COMPLETED).exists()
    assert Trip.objects.filter(available_seats=0).exists(), "aucun voyage complet"


def test_programme_du_jour_couvre_tous_les_statuts(seeded):
    """Le programme du jour contient tous les statuts, a des heures variees."""
    trips = Trip.objects.filter(departure_time__date=timezone.localdate())

    statuts = set(trips.values_list("status", flat=True))
    for attendu in (
        Trip.TripStatus.COMPLETED,
        Trip.TripStatus.IN_PROGRESS,
        Trip.TripStatus.DELAYED,
        Trip.TripStatus.CANCELLED,
        Trip.TripStatus.SCHEDULED,
    ):
        assert attendu in statuts, f"statut {attendu} absent du programme du jour"

    heures = {timezone.localtime(t.departure_time).hour for t in trips}
    assert len(heures) >= 5, "les departs du jour doivent s'etaler sur la journee"

    assert trips.filter(status=Trip.TripStatus.DELAYED, delay_minutes__gt=0).exists()
    assert trips.filter(status=Trip.TripStatus.CANCELLED).exclude(
        cancellation_reason=""
    ).exists()


# ---------------------------------------------------------------------------
# Reservations, paiements, billets
# ---------------------------------------------------------------------------


def test_billets_paiements_et_embarquements(seeded):
    """Billets au format officiel, paiements varies, embarquements traces."""
    annee = timezone.now().year
    bookings = Booking.objects.all()
    assert bookings.exists()

    for booking in bookings[:25]:
        assert booking.ticket_number.startswith(f"BF{annee}")
        assert len(booking.ticket_number) == len(f"BF{annee}") + 6
        assert booking.qr_code, "QR code manquant"
    assert bookings.values("ticket_number").distinct().count() == bookings.count()

    # Statuts de paiement : majorite payee, plus des etats non finalises.
    statuts = set(Payment.objects.values_list("status", flat=True))
    assert PaymentStatus.PAID in statuts
    assert Payment.objects.filter(status=PaymentStatus.PAID).count() > (
        Payment.objects.exclude(status=PaymentStatus.PAID).count()
    )
    assert len(statuts) >= 3
    assert statuts & {
        PaymentStatus.PENDING,
        PaymentStatus.OTP_REQUIRED,
        PaymentStatus.FAILED,
    }
    assert len(set(Payment.objects.values_list("method", flat=True))) >= 3

    payee = Booking.objects.filter(status=BookingStatus.PAID).first()
    assert payee.payments.filter(status=PaymentStatus.PAID).exists()
    assert payee.payment_method

    # Barre de progression de l'ecran embarquement.
    trip = (
        Trip.objects.filter(
            departure_time__date=timezone.localdate(),
            status__in=[Trip.TripStatus.IN_PROGRESS, Trip.TripStatus.COMPLETED],
        )
        .filter(bookings__status=BookingStatus.PAID)
        .first()
    )
    assert trip is not None
    embarques = trip.bookings.filter(boarding_validation__isnull=False).count()
    payes = trip.bookings.filter(status=BookingStatus.PAID).count()
    assert 0 < embarques <= payes


def test_voyageur_de_demonstration_a_un_historique_complet(seeded):
    """Le compte voyageur dedie couvre tous les ecrans de l'espace client."""
    rich = User.objects.get(phone="+22670000030")
    now = timezone.now()

    assert rich.bookings.filter(
        trip__departure_time__gt=now, status=BookingStatus.PAID
    ).exists(), "aucun voyage a venir"
    assert rich.bookings.filter(trip__departure_time__lt=now).exists(), "aucun voyage passe"
    assert rich.bookings.filter(status=BookingStatus.CANCELLED).exists(), "aucune annulation"
    assert rich.reviews.exists()
    assert rich.claims.exists()

    autres = User.objects.filter(role__name="voyageur").exclude(pk=rich.pk)
    assert rich.bookings.count() > max(u.bookings.count() for u in autres)


# ---------------------------------------------------------------------------
# Colis
# ---------------------------------------------------------------------------


def test_colis_tous_statuts_et_file_de_notification(seeded):
    """Chaque statut de colis est represente, dont des arrivees a notifier."""
    statuts = set(Parcel.objects.values_list("status", flat=True))
    for attendu in (
        ParcelStatus.REGISTERED,
        ParcelStatus.IN_TRANSIT,
        ParcelStatus.ARRIVED,
        ParcelStatus.NOTIFIED,
        ParcelStatus.COLLECTED,
    ):
        assert attendu in statuts, f"statut colis {attendu} absent"

    annee = timezone.now().year
    for parcel in Parcel.objects.all()[:10]:
        assert parcel.tracking_number.startswith(f"COL{annee}")
        assert parcel.qr_code
        assert parcel.tariff > 0
    assert Parcel.objects.filter(is_fragile=True).exists()

    # File de travail de l'ecran « Notification d'arrivee de colis ».
    agent = User.objects.get(phone="+22670000011")
    en_attente = Parcel.objects.filter(
        destination_station=agent.agent_profile.station,
        status=ParcelStatus.ARRIVED,
        notifications__isnull=True,
    )
    assert en_attente.count() >= 2
    assert Parcel.objects.filter(
        status=ParcelStatus.NOTIFIED, notifications__isnull=False
    ).exists()


# ---------------------------------------------------------------------------
# Relation client et supervision
# ---------------------------------------------------------------------------


def test_avis_reclamations_et_signalements(seeded):
    """Avis notes de 1 a 5, reclamations hors delai, signalements localises."""
    notes = set(Review.objects.values_list("rating", flat=True))
    assert Review.objects.count() >= 5
    assert len(notes) >= 3, "les notes doivent etre variees"
    assert min(notes) <= 2, "aucun avis negatif"
    assert max(notes) == 5
    assert Review.objects.exclude(response="").exists(), "aucun avis avec reponse"
    # Un avis ne porte que sur un voyage termine (business_rules.md §4).
    assert not Review.objects.exclude(trip__status=Trip.TripStatus.COMPLETED).exists()

    assert len(set(Claim.objects.values_list("status", flat=True))) >= 3
    limite = timezone.now() - timedelta(hours=48)
    en_retard = Claim.objects.filter(status__in=UNRESOLVED_STATUSES, created_at__lt=limite)
    assert en_retard.count() >= 2, "les reclamations en retard doivent ressortir en rouge"

    traitee = Claim.objects.exclude(response="").first()
    assert traitee.responded_by is not None and traitee.responded_at is not None

    assert SpeedReport.objects.count() >= 3
    for report in SpeedReport.objects.all():
        assert report.latitude is not None and report.longitude is not None
        assert report.reported_at is not None and report.description


def test_notifications_et_journal_dactivite(seeded):
    """Le super admin dispose de notifications et d'un journal d'audit."""
    super_admin = User.objects.get(phone="+22670000001")

    assert Notification.objects.filter(user=super_admin).exists()
    assert ActivityLog.objects.filter(user=super_admin).count() >= 3
    assert ActivityLog.objects.exclude(entity_type="").exists()
