"""Peuple la base avec un jeu de donnees de demonstration realiste.

Objectif : pouvoir se connecter avec n'importe quel role et trouver des ecrans
remplis (tableau de bord agent, espace voyageur, supervision super admin...),
sans jamais toucher a une base de production.

Usage :
    python manage.py seed_demo
    python manage.py seed_demo --reset            # purge d'abord les donnees de demo
    python manage.py seed_demo --seed 7           # autre graine aleatoire
    python manage.py seed_demo --force            # autorise l'execution si DEBUG=False

Idempotence : les objets sont crees sur des cles naturelles stables
(telephone, nom de compagnie, immatriculation, couple route/horaire), donc une
relance sans `--reset` ne cree pas de doublons. Les voyages sont ancres sur des
creneaux horaires fixes de la journee : relancer le meme jour est un no-op,
relancer le lendemain fait glisser la fenetre J-30 / J+15.
"""

import random
from collections import Counter
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.bookings.models import (
    BoardingMethod,
    BoardingValidation,
    Booking,
    BookingStatus,
    Gender,
    IdType,
    ScanLog,
    ScanResult,
)
from apps.bookings.services import cancel_booking, create_booking
from apps.claims.models import Claim, ClaimStatus, ClaimType
from apps.companies.models import (
    Company,
    CompanyNotificationSettings,
    CompanyPaymentMethod,
    CompanyStatus,
    PaymentMethodChoice,
)
from apps.core.services import log_activity
from apps.geography.models import City, Station
from apps.messaging.models import Message
from apps.notifications.models import Notification, NotificationType
from apps.notifications.services import notify
from apps.parcels.models import Parcel, ParcelNotification, ParcelStatus
from apps.parcels.services import calculate_tariff, generate_tracking_number
from apps.payments.models import Payment, PaymentMethod, PaymentOtp, PaymentStatus
from apps.payments.services import compute_commission
from apps.reviews.models import Review
from apps.routes.models import Route, RouteStop
from apps.speed_reports.models import SpeedReport, SpeedReportStatus
from apps.subscriptions.models import (
    Subscription,
    SubscriptionInvoice,
    SubscriptionPlan,
    SubscriptionStatus,
)
from apps.trips.models import Trip
from apps.users.models import AgentProfile, Role, User
from apps.vehicles.models import Vehicle
from apps.vehicles.services import get_available_seats
from utils.qr import generate_qr

from ._seed_data import (
    BRANDS,
    CITIES,
    CITY_COORDS,
    CLAIM_RESPONSES,
    CLAIM_TEMPLATES,
    COMPANY_REQUESTS,
    DEMO_PHONE_PREFIX,
    DEMO_USERS,
    DRIVER_NAMES,
    FRAGILE_NATURES,
    MAIN_COMPANY,
    MAIN_ROUTES,
    MAIN_STATIONS,
    NOMS,
    PARCEL_NATURES,
    PLANS,
    PRENOMS,
    REVIEW_COMMENTS,
    REVIEW_RESPONSES,
    ROUTE_STOPS,
    SECOND_COMPANY,
    SECOND_ROUTES,
    SECOND_STATIONS,
    SPEED_REPORT_TEMPLATES,
    STOP_CITIES,
    SUSPENDED_COMPANY,
    TRIP_CANCELLATION_REASONS,
    VOYAGEUR_KEYS,
)

# Fenetre temporelle couverte par les voyages generes.
PAST_DAYS = 30
FUTURE_DAYS = 15

# Creneaux horaires des departs du jour : garantit « plusieurs voyages
# aujourd'hui a des heures differentes » quelle que soit l'heure d'execution.
TODAY_HOURS = [5, 7, 9, 11, 13, 15, 17, 19]
# Creneaux utilises pour les journees passees et a venir.
PAST_HOURS = [6, 13]
FUTURE_HOURS = [7, 15]

# Index dans MAIN_ROUTES de la ligne phare (les deux sens de
# Ouagadougou <-> Bobo-Dioulasso) : c'est la ligne la plus empruntee du reseau
# reel, la premiere que montre la page d'accueil, et donc celle sur laquelle
# retombe le plus souvent une recherche de demonstration. Le round-robin des
# autres lignes la laissait sans aucun depart a venir la plupart des jours ;
# elle est desormais desservie tous les jours de la fenetre future, en plus de
# la rotation appliquee aux autres lignes.
FLAGSHIP_ROUTE_INDEXES = (0, 1)
# Creneaux additionnels, tard le soir, garantissant a la ligne phare un depart
# encore reservable aujourd'hui : son unique creneau dans TODAY_HOURS est
# volontairement marque `completed` par TODAY_PLAN (position 0) pour illustrer
# un voyage termine, ce qui laisserait sinon une recherche « aujourd'hui » sur
# le trajet le plus evident a essayer en demo sans aucun resultat.
FLAGSHIP_TODAY_HOURS = (20, 21)

# Taux de remplissage cibles, pour que les graphiques du dashboard soient
# parlants (certains voyages a 30 %, d'autres presque complets).
FILL_RATES = [Decimal("0.30"), Decimal("0.45"), Decimal("0.60"), Decimal("0.80"), Decimal("0.95")]

# Programme du jour : un voyage par creneau de TODAY_HOURS, sous la forme
# (statut final, taux de remplissage, retard en minutes). Tous les statuts que
# le front doit savoir afficher y figurent, dont un voyage complet (100 %).
TODAY_PLAN = [
    (Trip.TripStatus.COMPLETED, Decimal("0.85"), 0),
    (Trip.TripStatus.COMPLETED, Decimal("0.60"), 0),
    (Trip.TripStatus.IN_PROGRESS, Decimal("0.90"), 0),
    (Trip.TripStatus.DELAYED, Decimal("0.70"), 45),
    (Trip.TripStatus.CANCELLED, Decimal("0.40"), 0),
    (Trip.TripStatus.SCHEDULED, Decimal("1.00"), 0),  # voyage complet
    (Trip.TripStatus.SCHEDULED, Decimal("0.55"), 0),
    (Trip.TripStatus.SCHEDULED, Decimal("0.30"), 0),
]

# Remplissage des voyages de la seconde compagnie.
SECOND_COMPANY_FILL = Decimal("0.50")

# Repartition des statuts de paiement sur les voyages a venir / recents.
# La majorite est payee, le reste couvre tous les autres etats du modele.
PAYMENT_MIX = (
    [PaymentStatus.PAID] * 68
    + [PaymentStatus.PENDING] * 10
    + [PaymentStatus.OTP_REQUIRED] * 8
    + [PaymentStatus.FAILED] * 7
    + [PaymentStatus.REFUNDED] * 7
)

# Part des ventes realisees en ligne depuis un compte voyageur. Le reste part
# au guichet (passagers walk-in sans compte), ce qui correspond a la realite du
# terrain et evite de gonfler artificiellement l'historique des 5 comptes de
# demonstration.
ONLINE_ACCOUNT_SHARE = 0.08
# Part de ces ventes en ligne attribuee au voyageur de demonstration, afin que
# son espace personnel soit nettement plus fourni que celui des autres.
RICH_VOYAGEUR_SHARE = 0.5

# Moyens de paiement Mobile Money proposes aux voyageurs.
MOBILE_METHODS = [
    PaymentMethod.ORANGE_MONEY,
    PaymentMethod.MOOV_MONEY,
    PaymentMethod.CORIS_MONEY,
    PaymentMethod.TELECEL_MONEY,
]


class Command(BaseCommand):
    help = (
        "Peuple la base avec un jeu de donnees de demonstration realiste "
        "(comptes de tous les roles, voyages, reservations, colis, avis)."
    )

    # ------------------------------------------------------------------ #
    # CLI
    # ------------------------------------------------------------------ #

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Purge les donnees de demo avant de les recreer.",
        )
        parser.add_argument(
            "--seed",
            type=int,
            default=42,
            help="Graine aleatoire pour un jeu de donnees reproductible (defaut : 42).",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="Autorise l'execution meme si DEBUG=False (jamais sur une base de production).",
        )
        parser.add_argument(
            "--password",
            default="Demo1234!",
            help="Mot de passe commun a tous les comptes de demo (defaut : Demo1234!).",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "DEBUG=False : refus de peupler une base potentiellement de "
                "production. Relancez avec --force si vous savez ce que vous faites."
            )

        self.rng = random.Random(options["seed"])
        self.password = options["password"]
        self.stats = Counter()
        self.accounts = []

        if options["reset"]:
            self.reset_demo_data()

        self.stdout.write(self.style.MIGRATE_HEADING("Seed TransBooking BF"))

        ctx = {}
        ctx["cities"] = self.seed_geography()
        ctx["plans"] = self.seed_plans()
        self.seed_companies(ctx)
        self.seed_subscriptions(ctx)
        self.seed_users(ctx)
        self.seed_fleet(ctx)
        self.seed_trips(ctx)
        self.seed_bookings(ctx)
        self.seed_parcels(ctx)
        self.seed_feedback(ctx)

        self.print_recap()

    # ------------------------------------------------------------------ #
    # Purge (uniquement sous --reset)
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def reset_demo_data(self) -> None:
        """Supprime les donnees de demo, des feuilles vers la racine.

        La purge est strictement limitee aux objets de demo : les compagnies
        du jeu de donnees, leurs dependances, et les comptes du roster
        `DEMO_USERS`. Les villes et les roles, qui sont des donnees de
        reference partagees, sont conserves.
        """
        self.stdout.write(self.style.WARNING("Purge des donnees de demo..."))

        names = [MAIN_COMPANY["name"], SECOND_COMPANY["name"], SUSPENDED_COMPANY["name"]]
        names += [req["name"] for req in COMPANY_REQUESTS]
        companies = Company.objects.filter(name__in=names)
        phones = [u["phone"] for u in DEMO_USERS]
        users = User.objects.filter(phone__in=phones)

        bookings = Booking.objects.filter(trip__route__company__in=companies)
        parcels = Parcel.objects.filter(company__in=companies)

        # Les FK vers Trip/Route/Vehicle/Company sont en PROTECT : on part des
        # feuilles (scans, embarquements, paiements) vers la racine.
        ScanLog.objects.filter(booking__in=bookings).delete()
        BoardingValidation.objects.filter(booking__in=bookings).delete()
        PaymentOtp.objects.filter(payment__booking__in=bookings).delete()
        Payment.objects.filter(booking__in=bookings).delete()
        Payment.objects.filter(parcel__in=parcels).delete()
        ParcelNotification.objects.filter(parcel__in=parcels).delete()
        parcels.delete()
        bookings.delete()
        Trip.objects.filter(route__company__in=companies).delete()
        RouteStop.objects.filter(route__company__in=companies).delete()
        Route.objects.filter(company__in=companies).delete()
        Vehicle.objects.filter(company__in=companies).delete()

        Review.objects.filter(company__in=companies).delete()
        Claim.objects.filter(company__in=companies).delete()
        SpeedReport.objects.filter(company__in=companies).delete()
        SubscriptionInvoice.objects.filter(subscription__company__in=companies).delete()
        Subscription.objects.filter(company__in=companies).delete()
        CompanyPaymentMethod.objects.filter(company__in=companies).delete()
        CompanyNotificationSettings.objects.filter(company__in=companies).delete()

        Message.objects.filter(sender__in=users).delete()
        Message.objects.filter(recipient__in=users).delete()
        Notification.objects.filter(user__in=users).delete()

        # Les profils agents sont en PROTECT vers la compagnie : ils doivent
        # tous partir, y compris ceux de comptes hors roster (jeu de demo plus
        # ancien), sans quoi la suppression des compagnies echoue. Les comptes
        # correspondants sont supprimes avec eux pour ne pas laisser d'agents
        # orphelins sans compagnie.
        stale_agents = list(
            AgentProfile.objects.filter(company__in=companies)
            .exclude(user__in=users)
            .values_list("user_id", flat=True)
        )
        AgentProfile.objects.filter(company__in=companies).delete()
        AgentProfile.objects.filter(user__in=users).delete()
        Station.objects.filter(company__in=companies).delete()
        companies.delete()
        users.delete()
        User.objects.filter(pk__in=stale_agents, is_superuser=False).delete()

        # Comptes residuels du bloc de demonstration (jeu de donnees genere par
        # une version anterieure de la commande). Les superutilisateurs sont
        # epargnes : un administrateur reel a pu s'y glisser.
        User.objects.filter(phone__startswith=DEMO_PHONE_PREFIX).exclude(
            is_superuser=True
        ).delete()

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #

    def _at(self, day, hour: int, minute: int = 0):
        """Retourne un datetime aware au jour et a l'heure locale demandes."""
        naive = datetime.combine(day, time(hour, minute))
        return timezone.make_aware(naive, timezone.get_current_timezone())

    @staticmethod
    def _backdate(model, pk: int, moment) -> None:
        """Force `created_at` d'une ligne deja inseree.

        `created_at` est en `auto_now_add` : sans cette retouche, une
        reclamation « en retard depuis 48h » ou un log d'activite passe
        porteraient la date d'execution du seed et ne remonteraient pas dans
        les ecrans qui filtrent sur l'anciennete.
        """
        model.objects.filter(pk=pk).update(created_at=moment)

    def _person(self) -> tuple[str, str]:
        """Retourne un couple (prenom, nom) burkinabe tire au sort."""
        return self.rng.choice(PRENOMS), self.rng.choice(NOMS)

    def _walkin_phone(self) -> str:
        """Numero d'un passager walk-in sans compte (+226 7X XX XX XX)."""
        return f"+2267{self.rng.randint(1000000, 9999999)}"

    @staticmethod
    def _seat_plan(total: int) -> dict:
        """Construit un plan de sieges en rangees de 4, sieges 1 et 2 reserves."""
        layout, seat = [], 1
        while seat <= total:
            layout.append(list(range(seat, min(seat + 4, total + 1))))
            seat += 4
        # Sieges de l'equipage (chauffeur, receveur) non commercialisables.
        return {"layout": layout, "reserved": [1, 2]}

    def _track(self, key: str, created: bool) -> None:
        """Incremente le compteur `key` si l'objet vient d'etre cree."""
        if created:
            self.stats[key] += 1

    # ------------------------------------------------------------------ #
    # 1. Geographie
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_geography(self) -> dict:
        """Cree les villes burkinabe desservies (et les villes d'escale).

        Returns:
            Les villes indexees par nom.
        """
        cities = {}
        for name, region in {**CITIES, **STOP_CITIES}.items():
            city, created = City.objects.get_or_create(
                name=name, defaults={"region": region}
            )
            cities[name] = city
            self._track("Villes", created)
        self.stdout.write(f"  Villes            : {len(cities)}")
        return cities

    # ------------------------------------------------------------------ #
    # 2. Compagnies et forfaits
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_plans(self) -> dict:
        """Cree les forfaits d'abonnement (mensuels et annuel).

        Returns:
            Les forfaits indexes par nom.
        """
        plans = {}
        for spec in PLANS:
            plan, created = SubscriptionPlan.objects.get_or_create(
                name=spec["name"],
                defaults={
                    "price": spec["price"],
                    "duration_months": spec["duration_months"],
                    "description": spec["description"],
                    "features": spec["features"],
                    "is_active": True,
                },
            )
            plans[spec["name"]] = plan
            self._track("Forfaits", created)
        return plans

    def _create_company(self, spec: dict, status: str, **extra) -> tuple:
        """Cree (ou recupere) une compagnie sur son nom, cle naturelle unique."""
        sigle = spec["sigle"]
        defaults = {
            "sigle": sigle,
            "description": spec["description"],
            "welcome_message": spec.get("welcome_message", ""),
            "primary_color": spec.get("primary_color", ""),
            "city": spec["city"],
            "address": f"Avenue de la Nation, {spec['city']}",
            "phone": f"+2262{self.rng.randint(1000000, 9999999)}",
            "email": f"contact@{sigle.lower()}.bf",
            "rccm": f"BF-{sigle}-{self.rng.randint(2015, 2024)}-B-{self.rng.randint(1000, 9999)}",
            "ifu": str(self.rng.randint(10000000, 99999999)),
            "commission_rate": spec.get("commission_rate"),
            "status": status,
            **extra,
        }
        company, created = Company.objects.get_or_create(name=spec["name"], defaults=defaults)
        return company, created

    @transaction.atomic
    def seed_companies(self, ctx: dict) -> None:
        """Cree les 3 compagnies et les demandes d'inscription en instruction.

        Une compagnie active complete (jeu de test principal), une deuxieme
        active plus petite (verification de l'isolation multi-tenant), une
        suspendue (ecran « compte suspendu » et 403), plus trois demandes en
        cours d'instruction pour l'ecran super admin.
        """
        cities = ctx["cities"]

        for key, spec, status, extra in (
            ("main", MAIN_COMPANY, CompanyStatus.ACTIVE, {}),
            ("second", SECOND_COMPANY, CompanyStatus.ACTIVE, {}),
            (
                "suspended",
                SUSPENDED_COMPANY,
                CompanyStatus.SUSPENDED,
                {"suspension_reason": SUSPENDED_COMPANY["suspension_reason"]},
            ),
        ):
            ctx[key], created = self._create_company(spec, status, **extra)
            self._track("Compagnies", created)

        # Demandes d'inscription : lignes Company sans flotte ni admin.
        for req in COMPANY_REQUESTS:
            _, created = self._create_company(
                {**req, "commission_rate": None},
                req["status"],
                responsible_name=req["responsible_name"],
                responsible_phone=f"+2267{self.rng.randint(1000000, 9999999)}",
                info_request_message=req.get("info_request_message", ""),
            )
            self._track("Demandes d'inscription", created)

        # Moyens de paiement et preferences SMS des deux compagnies actives.
        for company in (ctx["main"], ctx["second"]):
            for method in (
                PaymentMethodChoice.CASH,
                PaymentMethodChoice.ORANGE_MONEY,
                PaymentMethodChoice.MOOV_MONEY,
                PaymentMethodChoice.CORIS_MONEY,
                PaymentMethodChoice.TELECEL_MONEY,
            ):
                _, created = CompanyPaymentMethod.objects.get_or_create(
                    company=company, method=method, defaults={"is_active": True}
                )
                self._track("Moyens de paiement", created)
            CompanyNotificationSettings.objects.get_or_create(company=company)

        # Gares.
        ctx["main_stations"] = self._create_stations(ctx["main"], MAIN_STATIONS, cities)
        ctx["second_stations"] = self._create_stations(
            ctx["second"], SECOND_STATIONS, cities
        )
        self.stdout.write(
            f"  Compagnies        : 3 actives/suspendue + "
            f"{len(COMPANY_REQUESTS)} demandes"
        )

    def _create_stations(self, company: Company, specs: list, cities: dict) -> list:
        """Cree les gares d'une compagnie (cle naturelle : compagnie + nom)."""
        stations = []
        for city_name, name, address in specs:
            station, created = Station.objects.get_or_create(
                company=company,
                name=name,
                defaults={
                    "city": cities[city_name],
                    "address": address,
                    "localisation": city_name,
                },
            )
            stations.append(station)
            self._track("Gares", created)
        return stations

    @transaction.atomic
    def seed_subscriptions(self, ctx: dict) -> None:
        """Attribue un abonnement a chaque compagnie : actif, proche expiration, expire.

        La compagnie principale est confortablement abonnee, la deuxieme arrive
        a echeance dans 5 jours (banniere de relance), la suspendue a un
        abonnement expire depuis 40 jours (cause de la suspension).
        """
        today = timezone.localdate()
        plans = ctx["plans"]

        specs = [
            # (compagnie, forfait, debut, fin, statut, renouvellement auto)
            (
                ctx["main"],
                plans["Premium Annuel"],
                today - timedelta(days=90),
                today + timedelta(days=275),
                SubscriptionStatus.ACTIVE,
                True,
            ),
            (
                ctx["second"],
                plans["Pro Mensuel"],
                today - timedelta(days=25),
                today + timedelta(days=5),
                SubscriptionStatus.ACTIVE,
                False,
            ),
            (
                ctx["suspended"],
                plans["Essentiel Mensuel"],
                today - timedelta(days=70),
                today - timedelta(days=40),
                SubscriptionStatus.EXPIRED,
                False,
            ),
        ]

        for company, plan, start, end, status, auto_renew in specs:
            subscription, created = Subscription.objects.get_or_create(
                company=company,
                plan=plan,
                start_date=start,
                defaults={
                    "end_date": end,
                    "status": status,
                    "auto_renew": auto_renew,
                    # Le rappel « expire dans 7 jours » n'a pas encore ete emis
                    # pour l'abonnement proche de l'echeance : la tache Celery
                    # doit pouvoir le declencher lors d'une demo.
                    "expiry_reminder_sent": False,
                },
            )
            self._track("Abonnements", created)

            invoice, inv_created = SubscriptionInvoice.objects.get_or_create(
                subscription=subscription,
                amount=plan.price,
                defaults={
                    # La facture de la compagnie suspendue reste impayee.
                    "paid_at": None
                    if status == SubscriptionStatus.EXPIRED
                    else self._at(start, 10),
                },
            )
            self._track("Factures", inv_created)
            if inv_created:
                self._backdate(SubscriptionInvoice, invoice.pk, self._at(start, 9))

    # ------------------------------------------------------------------ #
    # 3. Utilisateurs
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_users(self, ctx: dict) -> None:
        """Cree les comptes de tous les roles a partir du roster fige.

        Le telephone est le `USERNAME_FIELD` : il sert de cle naturelle, ce qui
        rend la fonction idempotente. Les profils agents rattachent chaque agent
        a sa compagnie et a sa gare.
        """
        roles = {}
        for value, _label in Role.RoleName.choices:
            roles[value], _ = Role.objects.get_or_create(name=value)

        companies = {"main": ctx["main"], "second": ctx["second"]}
        stations = {"main": ctx["main_stations"], "second": ctx["second_stations"]}
        users = {}

        for spec in DEMO_USERS:
            user = User.objects.filter(phone=spec["phone"]).first()
            if user is None:
                is_super = spec["role"] == "super_admin"
                manager = (
                    User.objects.create_superuser if is_super else User.objects.create_user
                )
                user = manager(
                    phone=spec["phone"],
                    password=self.password,
                    prenom=spec["prenom"],
                    nom=spec["nom"],
                    email=spec["email"],
                    role=roles[spec["role"]],
                )
                self.stats["Comptes utilisateurs"] += 1
            users[spec["key"]] = user

            # Profil agent (guichet ou controleur) rattache a une gare.
            if spec["role"] in ("agent_guichet", "controleur"):
                agent_type = (
                    AgentProfile.AgentType.GUICHET
                    if spec["role"] == "agent_guichet"
                    else AgentProfile.AgentType.CONTROLEUR
                )
                AgentProfile.objects.get_or_create(
                    user=user,
                    defaults={
                        "company": companies[spec["company"]],
                        "agent_type": agent_type,
                        "station": stations[spec["company"]][spec["station"]],
                    },
                )

            self.accounts.append(
                (spec["role"], spec["phone"], f"{spec['prenom']} {spec['nom']}", spec["label"])
            )

        # Rattachement du compte proprietaire a sa compagnie.
        for key, company in (("main_admin", ctx["main"]), ("second_admin", ctx["second"])):
            if company.admin_user_id != users[key].pk:
                company.admin_user = users[key]
                company.responsible_name = f"{users[key].prenom} {users[key].nom}"
                company.responsible_phone = users[key].phone
                company.save(
                    update_fields=[
                        "admin_user",
                        "responsible_name",
                        "responsible_phone",
                        "updated_at",
                    ]
                )

        ctx["users"] = users
        ctx["voyageurs"] = [users[key] for key in VOYAGEUR_KEYS]
        ctx["rich"] = users["voyageur_riche"]
        ctx["other_voyageurs"] = [u for u in ctx["voyageurs"] if u.pk != ctx["rich"].pk]
        self.stdout.write(f"  Comptes           : {len(DEMO_USERS)}")

    # ------------------------------------------------------------------ #
    # 4. Flotte
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_fleet(self, ctx: dict) -> None:
        """Cree les vehicules avec leur plan de sieges (dont un en maintenance).

        Les capacites sont volontairement variees pour que les taux de
        remplissage affiches aient du relief. Le vehicule en maintenance ne
        recoit aucun voyage (cf. `vehicles.services.ensure_vehicle_assignable`).

        `vehicle_type` couvre les trois niveaux de confort attendus par le
        badge/filtre Standard·VIP·VVIP du programme et du tableau de bord
        agent (cf. requetes agent module §4) : chaque compagnie active en
        propose au moins deux, pour que le filtre ait un effet visible en demo.
        """
        # (compagnie, immatriculation, capacite, type, statut)
        specs = [
            ("main", "11 AK 4821 BF", 55, "standard", Vehicle.VehicleStatus.ACTIVE),
            ("main", "11 BL 7734 BF", 45, "vip", Vehicle.VehicleStatus.ACTIVE),
            ("main", "22 AM 1290 BF", 33, "vvip", Vehicle.VehicleStatus.ACTIVE),
            ("main", "22 BN 6612 BF", 70, "standard", Vehicle.VehicleStatus.ACTIVE),
            ("main", "33 AL 3345 BF", 30, "vip", Vehicle.VehicleStatus.MAINTENANCE),
            ("second", "44 BM 9087 BF", 33, "standard", Vehicle.VehicleStatus.ACTIVE),
            ("second", "44 AN 2216 BF", 45, "vip", Vehicle.VehicleStatus.ACTIVE),
        ]

        fleet = {"main": [], "second": []}
        for key, registration, seats, vehicle_type, status in specs:
            brand, model = self.rng.choice(BRANDS)
            vehicle, created = Vehicle.objects.get_or_create(
                registration=registration,
                defaults={
                    "company": ctx[key],
                    "brand": brand,
                    "model": model,
                    "vehicle_type": vehicle_type,
                    "total_seats": seats,
                    "status": status,
                    "seat_plan": self._seat_plan(seats),
                },
            )
            self._track("Vehicules", created)
            if not created and vehicle.vehicle_type != vehicle_type:
                # `get_or_create` ne remplit `defaults` qu'a la creation : un
                # vehicule deja seede avant une evolution de `vehicle_type`
                # (ex : ancien jeu de donnees en `bus`/`minibus`) resterait
                # sinon bloque sur l'ancienne valeur, invisible pour le
                # toggle Standard/VIP/VVIP (`VehicleTypeToggle.normalize`
                # cote Flutter ne reconnait que les trois valeurs actuelles).
                vehicle.vehicle_type = vehicle_type
                vehicle.save(update_fields=["vehicle_type", "updated_at"])
            if status == Vehicle.VehicleStatus.ACTIVE:
                fleet[key].append(vehicle)

        ctx["fleet"] = fleet
        self.stdout.write(f"  Vehicules         : {len(specs)} (1 en maintenance)")

    # ------------------------------------------------------------------ #
    # 5. Lignes et voyages
    # ------------------------------------------------------------------ #

    def _create_routes(self, company: Company, specs: list, stations: list, cities: dict) -> list:
        """Cree les lignes commerciales d'une compagnie et leurs escales."""
        by_city = {station.city.name: station for station in stations}
        routes = []
        for origin, destination, distance, price, duration in specs:
            route, created = Route.objects.get_or_create(
                company=company,
                origin_city=cities[origin],
                destination_city=cities[destination],
                defaults={
                    "origin_station": by_city.get(origin),
                    "destination_station": by_city.get(destination),
                    "distance_km": Decimal(distance),
                    "base_price": Decimal(price),
                    "duration_minutes": duration,
                    "is_active": True,
                },
            )
            self._track("Lignes", created)

            for order, (stop_city, stop_price) in enumerate(
                ROUTE_STOPS.get((origin, destination), []), start=1
            ):
                _, stop_created = RouteStop.objects.get_or_create(
                    route=route,
                    stop_order=order,
                    defaults={
                        "city": cities[stop_city],
                        "display_name": f"Arret de {stop_city}",
                        "stop_price": Decimal(stop_price),
                    },
                )
                self._track("Escales", stop_created)
            routes.append(route)
        return routes

    def _create_trip(self, route: Route, vehicle: Vehicle, departure) -> tuple:
        """Cree un voyage sur un creneau donne (cle naturelle : ligne + horaire).

        Le voyage est toujours cree en `scheduled` : `create_booking` refuse
        les voyages annules ou termines, le statut definitif n'est applique
        qu'une fois les reservations posees. `registration_closes_at` est
        provisoirement place loin dans le futur (au lieu du defaut =
        `departure_time`) pour les voyages passes : sinon `create_booking`
        les considererait deja clos avant meme que `_fill_trip` ait pu les
        remplir (cf. requetes agent module §1). `_apply_final_status` le
        ramene a `departure_time` une fois les reservations posees.
        """
        duration = timedelta(minutes=route.duration_minutes or 240)
        trip, created = Trip.objects.get_or_create(
            route=route,
            departure_time=departure,
            defaults={
                "vehicle": vehicle,
                "driver_name": self.rng.choice(DRIVER_NAMES),
                "arrival_time": departure + duration,
                "price": route.base_price,
                "available_seats": len(get_available_seats(vehicle)),
                "status": Trip.TripStatus.SCHEDULED,
                "registration_closes_at": timezone.now() + timedelta(days=365),
            },
        )
        self._track("Voyages", created)
        return trip, created

    @transaction.atomic
    def seed_trips(self, ctx: dict) -> None:
        """Genere les voyages de J-30 a J+15, dont plusieurs aujourd'hui.

        Les horaires sont ancres sur des creneaux fixes de la journee, donc
        deterministes : relancer la commande le meme jour retombe sur les
        memes voyages. Le statut definitif de chaque voyage (termine, en
        cours, retarde, annule) est stocke dans `ctx["trip_specs"]` et
        applique apres la creation des reservations.
        """
        cities = ctx["cities"]
        ctx["main_routes"] = self._create_routes(
            ctx["main"], MAIN_ROUTES, ctx["main_stations"], cities
        )
        ctx["second_routes"] = self._create_routes(
            ctx["second"], SECOND_ROUTES, ctx["second_stations"], cities
        )

        today = timezone.localdate()
        specs = []  # (trip, statut final, taux de remplissage, delai)

        specs += self._seed_past_trips(ctx, today)
        specs += self._seed_today_trips(ctx, today)
        specs += self._seed_future_trips(ctx, today)
        specs += self._seed_second_company_trips(ctx, today)

        ctx["trip_specs"] = specs
        self.stdout.write(f"  Voyages           : {len(specs)}")

    def _seed_past_trips(self, ctx: dict, today) -> list:
        """Voyages termines de J-30 a J-1 (statistiques des dashboards).

        `J-1` (hier) est toujours inclus explicitement, meme si la foulee de 3
        jours ne l'atteint pas : c'est la seule reference d'« hier » que
        `today_stats.upcoming_departures_yesterday` du tableau de bord agent
        peut afficher (cf. requetes agent module §6).
        """
        routes = ctx["main_routes"]
        vehicles = ctx["fleet"]["main"]
        specs = []
        # Un jour sur trois, pour garder un volume de donnees raisonnable.
        offsets = list(range(PAST_DAYS, 0, -3))
        if PAST_DAYS >= 1 and 1 not in offsets:
            offsets.append(1)
        for offset in offsets:
            day = today - timedelta(days=offset)
            for index, hour in enumerate(PAST_HOURS):
                route = routes[(offset + index) % len(routes)]
                vehicle = vehicles[(offset + index) % len(vehicles)]
                trip, _ = self._create_trip(route, vehicle, self._at(day, hour))
                fill = FILL_RATES[(offset + index) % len(FILL_RATES)]
                specs.append((trip, Trip.TripStatus.COMPLETED, fill, 0))
        return specs

    def _seed_today_trips(self, ctx: dict, today) -> list:
        """Programme du jour : un voyage par creneau, tous statuts representes.

        Les statuts speciaux sont attribues par position dans la grille
        horaire (et non par comparaison a l'heure courante) afin que le
        programme du jour contienne toujours un voyage en cours, un retarde,
        un annule et un complet, quelle que soit l'heure d'execution.
        """
        routes = ctx["main_routes"]
        vehicles = ctx["fleet"]["main"]
        specs = []
        for index, hour in enumerate(TODAY_HOURS):
            route = routes[index % len(routes)]
            vehicle = vehicles[index % len(vehicles)]
            trip, _ = self._create_trip(route, vehicle, self._at(today, hour))
            status, fill, delay = TODAY_PLAN[index % len(TODAY_PLAN)]
            specs.append((trip, status, fill, delay))

        for route_index, hour in zip(FLAGSHIP_ROUTE_INDEXES, FLAGSHIP_TODAY_HOURS):
            route = routes[route_index]
            vehicle = vehicles[route_index % len(vehicles)]
            trip, _ = self._create_trip(route, vehicle, self._at(today, hour))
            specs.append((trip, Trip.TripStatus.SCHEDULED, Decimal("0.35"), 0))

        ctx["today_trips"] = [spec[0] for spec in specs]
        return specs

    def _seed_future_trips(self, ctx: dict, today) -> list:
        """Voyages a venir de J+1 a J+15 (recherche et reservation en ligne).

        La ligne phare (`FLAGSHIP_ROUTE_INDEXES`) roule tous les jours de la
        fenetre, dans les deux sens ; les autres lignes tournent un jour sur
        deux pour garder un volume de donnees raisonnable.
        """
        routes = ctx["main_routes"]
        vehicles = ctx["fleet"]["main"]
        flagship = [routes[i] for i in FLAGSHIP_ROUTE_INDEXES]
        others = [r for i, r in enumerate(routes) if i not in FLAGSHIP_ROUTE_INDEXES]
        specs = []

        for offset in range(1, FUTURE_DAYS + 1):
            day = today + timedelta(days=offset)
            for route, hour in zip(flagship, FUTURE_HOURS):
                vehicle = vehicles[(offset + hour) % len(vehicles)]
                trip, _ = self._create_trip(route, vehicle, self._at(day, hour))
                fill = FILL_RATES[(offset + hour) % len(FILL_RATES)] / 2
                specs.append((trip, Trip.TripStatus.SCHEDULED, fill, 0))

        for offset in range(1, FUTURE_DAYS + 1, 2):
            day = today + timedelta(days=offset)
            for index, hour in enumerate(FUTURE_HOURS):
                route = others[(offset + index) % len(others)]
                vehicle = vehicles[(offset + index) % len(vehicles)]
                trip, _ = self._create_trip(route, vehicle, self._at(day, hour))
                fill = FILL_RATES[(offset + index) % len(FILL_RATES)] / 2
                specs.append((trip, Trip.TripStatus.SCHEDULED, fill, 0))
        return specs

    def _seed_second_company_trips(self, ctx: dict, today) -> list:
        """Quelques voyages de la 2e compagnie (test d'isolation multi-tenant)."""
        routes = ctx["second_routes"]
        vehicles = ctx["fleet"]["second"]
        specs = []
        for offset in (-6, -2, 0, 3, 9):
            day = today + timedelta(days=offset)
            route = routes[abs(offset) % len(routes)]
            vehicle = vehicles[abs(offset) % len(vehicles)]
            trip, _ = self._create_trip(route, vehicle, self._at(day, 8))
            status = (
                Trip.TripStatus.COMPLETED if offset < 0 else Trip.TripStatus.SCHEDULED
            )
            specs.append((trip, status, SECOND_COMPANY_FILL, 0))
        return specs

    # ------------------------------------------------------------------ #
    # 6. Reservations, paiements, billets
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_bookings(self, ctx: dict) -> None:
        """Remplit les voyages de reservations, paiements et embarquements.

        Les billets sont produits par `bookings.services.create_booking` :
        numero au format BF<annee><sequence>, QR encodant le numero de billet
        et decrement du stock de sieges sous verrou, exactement comme en
        production. Le statut definitif du voyage n'est applique qu'ensuite,
        `create_booking` refusant les voyages annules ou termines.
        """
        agents = [ctx["users"]["main_agent_ouaga"], ctx["users"]["main_agent_bobo"]]
        second_agent = ctx["users"]["second_agent"]
        controleur = ctx["users"]["main_controleur"]
        now = timezone.now()

        for trip, final_status, fill, delay in ctx["trip_specs"]:
            is_second = trip.route.company_id == ctx["second"].pk
            trip_agents = [second_agent] if is_second else agents
            # Garde d'idempotence : un voyage deja rempli n'est pas re-seede.
            if not trip.bookings.exists():
                self._fill_trip(ctx, trip, fill, trip_agents, controleur, final_status, now)

            self._apply_final_status(trip, final_status, delay)

        self._seed_rich_voyageur_history(ctx)
        self._seed_agent_counter_cancellation(ctx)

    def _seed_agent_counter_cancellation(self, ctx: dict) -> None:
        """Annule un billet paye au guichet, par l'agent lui-meme (pas un admin).

        Demontre le nouveau perimetre de `cancel_booking` pour un
        `agent_guichet` : periemetre compagnie (pas de restriction
        proprietaire) et sans le delai de 2h reserve au voyageur (cf. requetes
        agent module §1). Idempotent sur le motif, cle stable de la demo.
        """
        reason = "Client absent au guichet."
        if Booking.objects.filter(cancellation_reason=reason).exists():
            return

        candidate = (
            Booking.objects.filter(
                trip__route__company=ctx["main"],
                trip__status=Trip.TripStatus.SCHEDULED,
                # Exclut le voyage volontairement complet (`available_seats=0`)
                # de la demo « programme du jour » : l'annulation ne doit pas
                # lui rendre un siege et casser cette vitrine.
                trip__available_seats__gt=0,
                status=BookingStatus.PAID,
            )
            .order_by("trip__departure_time")
            .first()
        )
        if candidate is None:
            return

        cancel_booking(candidate, ctx["users"]["main_agent_ouaga"], reason)
        self.stats["Reservations annulees au guichet"] += 1

    def _fill_trip(self, ctx, trip, fill, agents, controleur, final_status, now) -> None:
        """Cree les reservations d'un voyage jusqu'au taux de remplissage vise."""
        capacity = len(get_available_seats(trip.vehicle))
        target = int(capacity * fill)
        is_past = final_status in (
            Trip.TripStatus.COMPLETED,
            Trip.TripStatus.IN_PROGRESS,
            Trip.TripStatus.DELAYED,
        )

        for _ in range(target):
            booking = self._create_one_booking(ctx, trip, agents, is_past)
            if booking is None:
                break  # plus de siege disponible
            payment_status = self._draw_payment_status(is_past)
            self._create_payment(ctx, booking, payment_status, is_past, now)

            # Passagers deja embarques : alimente la barre de progression de
            # l'ecran embarquement pour les voyages du jour et passes.
            # Un voyage termine a embarque presque tout le monde ; un voyage en
            # cours n'en est qu'a la moitie (barre de progression partielle).
            taux = 0.95 if final_status == Trip.TripStatus.COMPLETED else 0.55
            if (
                is_past
                and booking.status == BookingStatus.PAID
                and self.rng.random() < taux
            ):
                self._board(booking, controleur, trip)

        # Quelques annulations, via le service pour liberer le siege proprement.
        if final_status == Trip.TripStatus.SCHEDULED and self.rng.random() < 0.35:
            candidate = trip.bookings.filter(status=BookingStatus.PENDING).first()
            if candidate is not None:
                cancel_booking(
                    candidate,
                    ctx["users"]["main_admin"],
                    "Annulation a la demande du passager.",
                )
                self.stats["Reservations annulees"] += 1

    def _create_one_booking(self, ctx, trip, agents, is_past):
        """Cree une reservation via le service metier, ou None si le bus est plein."""
        # Vente en ligne depuis un compte voyageur, ou vente au guichet a un
        # passager de passage (sans compte). Le voyageur de demonstration
        # concentre la moitie des ventes en ligne.
        if self.rng.random() < ONLINE_ACCOUNT_SHARE:
            agent = None
            voyageur = (
                ctx["rich"]
                if self.rng.random() < RICH_VOYAGEUR_SHARE
                else self.rng.choice(ctx["other_voyageurs"])
            )
        else:
            agent = self.rng.choice(agents)
            voyageur = None

        if voyageur is not None:
            prenom, nom, phone = voyageur.prenom, voyageur.nom, voyageur.phone
        else:
            prenom, nom = self._person()
            phone = self._walkin_phone()

        try:
            booking = create_booking(
                {
                    "trip": trip,
                    "user": voyageur,
                    "first_name": prenom,
                    "last_name": nom,
                    "phone": phone,
                    "amount": trip.price,
                },
                agent=agent,
            )
        except Exception:
            # TripFull / SeatTaken : le vehicule est complet.
            return None

        self._decorate_booking(booking, trip, is_past)
        self.stats["Reservations"] += 1
        return booking

    def _decorate_booking(self, booking, trip, is_past) -> None:
        """Complete les champs facultatifs du passager (identite, bagages)."""
        booking.gender = self.rng.choice([Gender.MALE, Gender.FEMALE])
        booking.origin_city = trip.route.origin_city
        booking.destination_city = trip.route.destination_city
        booking.has_luggage = self.rng.random() < 0.45
        booking.luggage_qty = self.rng.randint(1, 3) if booking.has_luggage else None
        # Piece d'identite renseignee sur une partie des ventes guichet.
        if self.rng.random() < 0.4:
            booking.id_type = self.rng.choice([IdType.CNIB, IdType.PASSPORT])
            booking.id_number = f"B{self.rng.randint(10000000, 99999999)}"
        booking.save(
            update_fields=[
                "gender", "origin_city", "destination_city", "has_luggage",
                "luggage_qty", "id_type", "id_number", "updated_at",
            ]
        )
        # La reservation est anterieure au depart : on recale sa date de
        # creation pour que les statistiques par periode soient credibles.
        created = trip.departure_time - timedelta(days=self.rng.randint(1, 10))
        self._backdate(Booking, booking.pk, created)

    def _draw_payment_status(self, is_past) -> str:
        """Tire un statut de paiement (les voyages passes sont surtout payes)."""
        if is_past:
            return self.rng.choice([PaymentStatus.PAID] * 9 + [PaymentStatus.REFUNDED])
        return self.rng.choice(PAYMENT_MIX)

    def _create_payment(self, ctx, booking, status, is_past, now) -> None:
        """Cree le paiement d'une reservation et aligne le statut du billet."""
        method = self.rng.choice([PaymentMethod.CASH] * 3 + MOBILE_METHODS)
        is_cash = method == PaymentMethod.CASH
        # Le flux OTP ne concerne que le Mobile Money (cf. payments.models).
        if status == PaymentStatus.OTP_REQUIRED and is_cash:
            method = self.rng.choice(MOBILE_METHODS)
            is_cash = False

        paid = status in (PaymentStatus.PAID, PaymentStatus.REFUNDED)
        payment = Payment.objects.create(
            booking=booking,
            amount=booking.amount,
            method=method,
            status=status,
            transaction_ref=""
            if is_cash or not paid
            else f"MM{self.rng.randint(100000000, 999999999)}",
            provider_ref=""
            if is_cash
            else f"PR{self.rng.randint(100000, 999999)}",
            phone="" if is_cash else booking.phone,
            commission=compute_commission(booking.amount, booking.trip.route.company)
            if paid
            else None,
            paid_at=booking.created_at + timedelta(minutes=5) if paid else None,
            agent=booking.agent,
        )
        self.stats["Paiements"] += 1
        self._backdate(Payment, payment.pk, booking.created_at)

        # Code de confirmation en attente de saisie par le payeur.
        if status == PaymentStatus.OTP_REQUIRED:
            PaymentOtp.objects.create(
                payment=payment,
                code_hash="",  # le fournisseur genere et verifie le code
                expires_at=now + timedelta(minutes=5),
                attempts=0,
            )
            self.stats["Codes OTP"] += 1

        booking.payment_method = method
        if status == PaymentStatus.PAID:
            booking.status = BookingStatus.PAID
        elif status == PaymentStatus.REFUNDED:
            booking.status = BookingStatus.REFUNDED
        booking.save(update_fields=["status", "payment_method", "updated_at"])

        # Impression du billet au guichet pour une partie des ventes payees.
        if booking.status == BookingStatus.PAID and booking.agent_id and self.rng.random() < 0.5:
            Booking.objects.filter(pk=booking.pk).update(
                printed_at=booking.created_at + timedelta(minutes=6), print_count=1
            )

    def _board(self, booking, controleur, trip) -> None:
        """Enregistre l'embarquement d'un passager et trace le scan du QR."""
        boarded_at = trip.departure_time - timedelta(minutes=self.rng.randint(5, 40))
        _, created = BoardingValidation.objects.get_or_create(
            booking=booking,
            defaults={
                "validated_by": controleur,
                "method": self.rng.choice([BoardingMethod.SCAN] * 4 + [BoardingMethod.MANUAL]),
                "boarded_at": boarded_at,
            },
        )
        if not created:
            return
        self.stats["Embarquements"] += 1

        log = ScanLog.objects.create(
            agent=controleur,
            booking=booking,
            ticket_number=booking.ticket_number,
            result=ScanResult.VALID,
        )
        self._backdate(ScanLog, log.pk, boarded_at)
        self.stats["Scans"] += 1

    def _apply_final_status(self, trip, final_status, delay) -> None:
        """Applique le statut definitif du voyage une fois les sieges vendus."""
        fields = []
        if trip.status != final_status:
            trip.status = final_status
            fields.append("status")
        if delay and trip.delay_minutes != delay:
            trip.delay_minutes = delay
            fields.append("delay_minutes")
        if final_status == Trip.TripStatus.CANCELLED and not trip.cancellation_reason:
            trip.cancellation_reason = self.rng.choice(TRIP_CANCELLATION_REASONS)
            fields.append("cancellation_reason")
        # Repli sur l'invariant de production (registration_closes_at =
        # departure_time) : la valeur provisoire loin dans le futur n'etait
        # utile que le temps de remplir le voyage (cf. _create_trip).
        if trip.registration_closes_at != trip.departure_time:
            trip.registration_closes_at = trip.departure_time
            fields.append("registration_closes_at")
        if fields:
            trip.save(update_fields=[*fields, "updated_at"])

    def _seed_rich_voyageur_history(self, ctx: dict) -> None:
        """Garantit un historique complet au voyageur de demonstration.

        L'espace voyageur doit montrer d'emblee un voyage a venir, des voyages
        passes et une reservation annulee : on complete donc explicitement le
        dossier de ce compte plutot que de compter sur le tirage aleatoire.
        """
        rich = ctx["rich"]
        now = timezone.now()

        candidates = [
            trip
            for trip, status, _fill, _delay in ctx["trip_specs"]
            if status == Trip.TripStatus.SCHEDULED
            and trip.departure_time > now
            and trip.route.company_id == ctx["main"].pk
        ]
        # `trip.available_seats` en memoire date de la creation du voyage, avant
        # son remplissage par `_fill_trip` : on revalide aupres de la base pour
        # ne jamais tenter de reserver sur un voyage devenu complet entre-temps.
        available_ids = set(
            Trip.objects.filter(
                pk__in=[trip.pk for trip in candidates], available_seats__gt=0
            ).values_list("pk", flat=True)
        )
        upcoming = [trip for trip in candidates if trip.pk in available_ids]

        # Un voyage a venir paye.
        if upcoming and not rich.bookings.filter(
            trip__departure_time__gt=now, status=BookingStatus.PAID
        ).exists():
            booking = create_booking(
                {
                    "trip": upcoming[0],
                    "user": rich,
                    "first_name": rich.prenom,
                    "last_name": rich.nom,
                    "phone": rich.phone,
                    "amount": upcoming[0].price,
                    "status": BookingStatus.PAID,
                    "payment_method": PaymentMethod.ORANGE_MONEY,
                },
            )
            Payment.objects.create(
                booking=booking,
                amount=booking.amount,
                method=PaymentMethod.ORANGE_MONEY,
                status=PaymentStatus.PAID,
                transaction_ref=f"MM{self.rng.randint(100000000, 999999999)}",
                phone=rich.phone,
                commission=compute_commission(booking.amount, ctx["main"]),
                paid_at=now,
            )
            self.stats["Reservations"] += 1
            self.stats["Paiements"] += 1

        # Une reservation annulee.
        if len(upcoming) > 1 and not rich.bookings.filter(
            status=BookingStatus.CANCELLED
        ).exists():
            booking = create_booking(
                {
                    "trip": upcoming[1],
                    "user": rich,
                    "first_name": rich.prenom,
                    "last_name": rich.nom,
                    "phone": rich.phone,
                    "amount": upcoming[1].price,
                },
            )
            cancel_booking(
                booking,
                ctx["users"]["main_admin"],
                "Annulation demandee par le voyageur (empechement personnel).",
            )
            self.stats["Reservations"] += 1
            self.stats["Reservations annulees"] += 1

        # Des voyages passes payes, indispensables pour deposer des avis.
        past = [
            trip
            for trip, status, _fill, _delay in ctx["trip_specs"]
            if status == Trip.TripStatus.COMPLETED
            and trip.route.company_id == ctx["main"].pk
        ][:4]
        for trip in past:
            if rich.bookings.filter(trip=trip).exists():
                continue
            # Le voyage est termine : on insere directement la reservation, le
            # service refusant (a juste titre) de vendre sur un voyage passe.
            ticket = self._next_ticket_number()
            booking = Booking.objects.create(
                trip=trip,
                user=rich,
                first_name=rich.prenom,
                last_name=rich.nom,
                phone=rich.phone,
                gender=Gender.MALE,
                seat_number=self._free_seat(trip),
                amount=trip.price,
                payment_method=PaymentMethod.ORANGE_MONEY,
                ticket_number=ticket,
                qr_code=generate_qr(ticket),
                status=BookingStatus.PAID,
                origin_city=trip.route.origin_city,
                destination_city=trip.route.destination_city,
            )
            self._backdate(Booking, booking.pk, trip.departure_time - timedelta(days=3))
            Payment.objects.create(
                booking=booking,
                amount=booking.amount,
                method=PaymentMethod.ORANGE_MONEY,
                status=PaymentStatus.PAID,
                transaction_ref=f"MM{self.rng.randint(100000000, 999999999)}",
                phone=rich.phone,
                commission=compute_commission(booking.amount, ctx["main"]),
                paid_at=trip.departure_time - timedelta(days=3),
            )
            Trip.objects.filter(pk=trip.pk, available_seats__gt=0).update(
                available_seats=trip.available_seats - 1
            )
            self.stats["Reservations"] += 1
            self.stats["Paiements"] += 1

        ctx["rich_past_trips"] = past

    def _next_ticket_number(self) -> str:
        """Numero de billet suivant, au format officiel BF<annee><sequence>."""
        from apps.bookings.services import generate_ticket_number

        return generate_ticket_number()

    def _free_seat(self, trip) -> str:
        """Premier siege encore libre sur un voyage."""
        seats = get_available_seats(trip.vehicle, trip)
        return seats[0] if seats else str(self.rng.randint(900, 999))

    # ------------------------------------------------------------------ #
    # 7. Colis
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_parcels(self, ctx: dict) -> None:
        """Enregistre des colis dans chacun des statuts du modele.

        Plusieurs colis sont laisses en `arrived` sans notification a la gare
        de Ouagadougou : ce sont eux qui alimentent l'ecran « Notification
        d'arrivee de colis » de l'agent guichet.
        """
        company = ctx["main"]
        cities = ctx["cities"]
        stations = {station.city.name: station for station in ctx["main_stations"]}
        agent = ctx["users"]["main_agent_ouaga"]
        rich = ctx["rich"]

        # Garde d'idempotence : le numero de suivi etant sequentiel, on ne
        # rejoue pas la generation si les colis de demo sont deja la.
        if Parcel.objects.filter(company=company).count() >= 14:
            self.stdout.write("  Colis             : deja presents, ignores")
            return

        # (origine, destination, statut, nombre)
        plan = [
            ("Ouagadougou", "Bobo-Dioulasso", ParcelStatus.REGISTERED, 2),
            ("Ouagadougou", "Koudougou", ParcelStatus.REGISTERED, 1),
            ("Ouagadougou", "Bobo-Dioulasso", ParcelStatus.IN_TRANSIT, 2),
            ("Ouagadougou", "Ouahigouya", ParcelStatus.IN_TRANSIT, 1),
            # Arrives a Ouaga et non notifies : file de travail de l'agent.
            ("Bobo-Dioulasso", "Ouagadougou", ParcelStatus.ARRIVED, 4),
            ("Bobo-Dioulasso", "Ouagadougou", ParcelStatus.NOTIFIED, 2),
            ("Bobo-Dioulasso", "Ouagadougou", ParcelStatus.COLLECTED, 3),
        ]

        trips = ctx.get("today_trips") or []
        for origin, destination, status, count in plan:
            for index in range(count):
                self._create_parcel(
                    ctx, company, cities, stations, agent, rich,
                    origin, destination, status, trips, index,
                )
        self.stdout.write(f"  Colis             : {self.stats['Colis']}")

    def _create_parcel(
        self, ctx, company, cities, stations, agent, rich,
        origin, destination, status, trips, index,
    ) -> None:
        """Cree un colis avec tarif calcule et numero de suivi officiels."""
        nature = self.rng.choice(PARCEL_NATURES)
        weight = Decimal(self.rng.randint(2, 45))
        tariff = calculate_tariff(weight, cities[origin].id, cities[destination].id, company)
        tracking = generate_tracking_number()

        # Le voyageur de demo est expediteur d'une partie des colis, pour que
        # son espace « Mes colis » ne soit pas vide.
        is_rich_sender = index == 0 and self.rng.random() < 0.6
        if is_rich_sender:
            sender_name, sender_phone = f"{rich.prenom} {rich.nom}", rich.phone
        else:
            sender_prenom, sender_nom = self._person()
            sender_name, sender_phone = f"{sender_prenom} {sender_nom}", self._walkin_phone()
        recipient_prenom, recipient_nom = self._person()

        registered_at = timezone.now() - timedelta(days=self.rng.randint(1, 12))
        parcel = Parcel.objects.create(
            company=company,
            trip=self.rng.choice(trips) if trips else None,
            origin_city=cities[origin],
            destination_city=cities[destination],
            origin_station=stations.get(origin),
            destination_station=stations.get(destination),
            sender_name=sender_name,
            sender_phone=sender_phone,
            recipient_name=f"{recipient_prenom} {recipient_nom}",
            recipient_phone=self._walkin_phone(),
            nature=nature,
            description=f"{nature} expedie de {origin} vers {destination}.",
            weight_kg=weight,
            length_cm=Decimal(self.rng.randint(20, 90)),
            width_cm=Decimal(self.rng.randint(15, 60)),
            height_cm=Decimal(self.rng.randint(10, 50)),
            declared_value=Decimal(self.rng.randrange(5000, 250000, 5000)),
            is_fragile=nature in FRAGILE_NATURES,
            tariff=tariff,
            tracking_number=tracking,
            qr_code=generate_qr(tracking),
            status=status,
            registered_by=agent,
            collected_at=registered_at + timedelta(days=2)
            if status == ParcelStatus.COLLECTED
            else None,
        )
        self._backdate(Parcel, parcel.pk, registered_at)
        self.stats["Colis"] += 1

        # Le SMS d'arrivee n'est trace que pour les colis notifies ou remis :
        # l'absence de notification est ce qui fait remonter un colis dans
        # l'ecran « Notification d'arrivee » (regle anti-doublon).
        if status in (ParcelStatus.NOTIFIED, ParcelStatus.COLLECTED):
            notification = ParcelNotification.objects.create(
                parcel=parcel,
                message=(
                    f"Votre colis {tracking} est arrive a la gare de "
                    f"{destination}. Presentez-vous avec une piece d'identite."
                ),
                sent_by=agent,
            )
            self._backdate(
                ParcelNotification, notification.pk, registered_at + timedelta(days=1)
            )
            self.stats["Notifications colis"] += 1

    # ------------------------------------------------------------------ #
    # 8. Relation client et supervision
    # ------------------------------------------------------------------ #

    @transaction.atomic
    def seed_feedback(self, ctx: dict) -> None:
        """Cree avis, reclamations, signalements, notifications et journaux."""
        self._seed_reviews(ctx)
        self._seed_claims(ctx)
        self._seed_speed_reports(ctx)
        self._seed_notifications(ctx)
        self._seed_activity_logs(ctx)
        self._seed_messages(ctx)

    def _seed_reviews(self, ctx: dict) -> None:
        """Depose des avis notes de 1 a 5 sur les voyages termines.

        Un avis exige un voyage termine et une reservation payee du voyageur
        (cf. business_rules.md §4) : on ne parcourt donc que les reservations
        payees des voyages `completed`.
        """
        company = ctx["main"]
        # Notes ciblees : majorite de bonnes notes, mais toute l'echelle est
        # representee pour que la repartition du dashboard soit lisible. Les
        # cinq premieres notes balaient l'echelle, de sorte que le camembert
        # reste parlant meme si peu de voyages sont eligibles a un avis.
        tail = [5] * 7 + [4] * 5 + [3] * 3 + [2] * 2 + [1]
        self.rng.shuffle(tail)
        ratings = [5, 4, 3, 2, 1] + tail

        candidates = (
            Booking.objects.filter(
                trip__route__company=company,
                trip__status=Trip.TripStatus.COMPLETED,
                status=BookingStatus.PAID,
                user__isnull=False,
            )
            .select_related("trip")
            .order_by("trip__departure_time", "pk")
        )

        seen = set()
        for booking in candidates:
            if not ratings:
                break
            key = (booking.user_id, booking.trip_id)
            if key in seen:
                continue
            seen.add(key)

            rating = ratings.pop(0)
            responded = rating <= 3 or self.rng.random() < 0.3
            review, created = Review.objects.get_or_create(
                user_id=booking.user_id,
                trip=booking.trip,
                defaults={
                    "company": company,
                    "rating": rating,
                    "comment": self.rng.choice(REVIEW_COMMENTS[rating]),
                    # Les avis negatifs recoivent systematiquement une reponse.
                    "response": self.rng.choice(REVIEW_RESPONSES) if responded else "",
                    "responded_at": booking.trip.departure_time + timedelta(days=2)
                    if responded
                    else None,
                    "is_flagged": rating == 1 and self.rng.random() < 0.5,
                    "is_testimonial": rating == 5 and self.rng.random() < 0.4,
                },
            )
            if created:
                self.stats["Avis"] += 1
                self._backdate(
                    Review, review.pk, booking.trip.departure_time + timedelta(days=1)
                )

    def _seed_claims(self, ctx: dict) -> None:
        """Cree des reclamations de tous les types et statuts.

        Deux d'entre elles sont volontairement laissees sans reponse depuis
        plus de 48h : elles doivent ressortir en rouge (`is_overdue`, annote
        cote service) dans l'espace admin compagnie.
        """
        company = ctx["main"]
        now = timezone.now()
        voyageurs = ctx["voyageurs"]
        admin = ctx["users"]["main_admin"]

        # (type, statut, anciennete en heures, reponse ?)
        plan = [
            (ClaimType.RETARD, ClaimStatus.SUBMITTED, 72, False),          # en retard
            (ClaimType.PERTE_BAGAGE, ClaimStatus.SUBMITTED, 96, False),    # en retard
            (ClaimType.BAGAGE_ENDOMMAGE, ClaimStatus.SUBMITTED, 6, False),
            (ClaimType.COMPORTEMENT, ClaimStatus.IN_PROGRESS, 30, False),
            (ClaimType.SURCHARGE, ClaimStatus.IN_PROGRESS, 80, False),     # en retard
            (ClaimType.REMBOURSEMENT, ClaimStatus.RESOLVED, 120, True),
            (ClaimType.AUTRE, ClaimStatus.RESOLVED, 200, True),
            (ClaimType.RETARD, ClaimStatus.CLOSED, 300, True),
            (ClaimType.PERTE_BAGAGE, ClaimStatus.ESCALATED, 150, False),
        ]

        bookings = list(
            Booking.objects.filter(
                trip__route__company=company, status=BookingStatus.PAID, user__isnull=False
            ).order_by("pk")[:20]
        )

        for index, (claim_type, status, age_hours, has_response) in enumerate(plan):
            subject, description = CLAIM_TEMPLATES[claim_type]
            # Le voyageur de demo depose les deux premieres reclamations.
            user = ctx["rich"] if index < 2 else voyageurs[index % len(voyageurs)]
            booking = bookings[index] if index < len(bookings) else None
            created_at = now - timedelta(hours=age_hours)

            claim, created = Claim.objects.get_or_create(
                company=company,
                user=user,
                claim_type=claim_type,
                subject=subject,
                defaults={
                    "description": description,
                    "booking": booking,
                    "ticket_number": booking.ticket_number if booking else "",
                    "travel_date": (booking.trip.departure_time.date() if booking else None),
                    "status": status,
                    "response": self.rng.choice(CLAIM_RESPONSES) if has_response else "",
                    "responded_by": admin if has_response else None,
                    "responded_at": created_at + timedelta(hours=20) if has_response else None,
                },
            )
            if created:
                self.stats["Reclamations"] += 1
                self._backdate(Claim, claim.pk, created_at)

    def _seed_speed_reports(self, ctx: dict) -> None:
        """Cree des signalements d'exces de vitesse geolocalises et horodates."""
        company = ctx["main"]
        now = timezone.now()
        trips = [
            trip
            for trip, status, _fill, _delay in ctx["trip_specs"]
            if status == Trip.TripStatus.COMPLETED and trip.route.company_id == company.pk
        ]
        statuses = [
            SpeedReportStatus.PENDING,
            SpeedReportStatus.PENDING,
            SpeedReportStatus.REVIEWED,
            SpeedReportStatus.CLOSED,
        ]

        for index, (description, speed) in enumerate(SPEED_REPORT_TEMPLATES):
            user = ctx["rich"] if index == 0 else ctx["voyageurs"][index % len(ctx["voyageurs"])]
            trip = trips[index % len(trips)] if trips else None
            city = trip.route.origin_city.name if trip else "Ouagadougou"
            latitude, longitude = CITY_COORDS.get(city, CITY_COORDS["Ouagadougou"])
            reported_at = now - timedelta(days=index + 1, hours=self.rng.randint(0, 20))

            # Cle naturelle : le texte du signalement, stable d'une execution a
            # l'autre. `reported_at` derive de l'heure courante et ne peut donc
            # pas servir de cle sans recreer un signalement a chaque relance.
            report, created = SpeedReport.objects.get_or_create(
                company=company,
                user=user,
                description=description,
                defaults={
                    "trip": trip,
                    "reported_at": reported_at,
                    "estimated_speed": speed,
                    # Legere derive autour de la ville pour situer le point.
                    "latitude": latitude + Decimal("0.05") * index,
                    "longitude": longitude - Decimal("0.04") * index,
                    "status": statuses[index % len(statuses)],
                },
            )
            if created:
                self.stats["Signalements vitesse"] += 1
                self._backdate(SpeedReport, report.pk, reported_at)

    def _seed_notifications(self, ctx: dict) -> None:
        """Cree des notifications in-app via la facade `notifications.services.notify`."""
        super_admin = ctx["users"]["super_admin"]
        rich = ctx["rich"]

        if Notification.objects.filter(user=super_admin).exists():
            return

        pending = Company.objects.filter(status=CompanyStatus.PENDING).first()
        messages = [
            (
                super_admin,
                NotificationType.SYSTEM,
                "Nouvelle demande d'inscription",
                f"La compagnie {pending.name} a depose une demande d'agrement."
                if pending
                else "Une nouvelle compagnie a depose une demande d'agrement.",
                "company",
                pending.pk if pending else None,
            ),
            (
                super_admin,
                NotificationType.SYSTEM,
                "Abonnement arrivant a echeance",
                f"L'abonnement de {ctx['second'].name} expire dans 5 jours.",
                "company",
                ctx["second"].pk,
            ),
            (
                super_admin,
                NotificationType.CLAIM,
                "Reclamations non traitees",
                "Trois reclamations depassent le delai de reponse de 48 heures.",
                "claim",
                None,
            ),
            (
                ctx["users"]["main_admin"],
                NotificationType.REVIEW,
                "Nouvel avis client",
                "Un voyageur a laisse un avis 2/5 sur un voyage recent.",
                "review",
                None,
            ),
            (
                rich,
                NotificationType.BOOKING,
                "Reservation confirmee",
                "Votre billet est disponible dans l'espace « Mes reservations ».",
                "booking",
                None,
            ),
            (
                rich,
                NotificationType.PARCEL,
                "Colis arrive en gare",
                "Votre colis est arrive a la gare de Ouagadougou Patte d'Oie.",
                "parcel",
                None,
            ),
        ]

        for user, kind, title, body, reference_type, reference_id in messages:
            notification = notify(
                user_id=user.pk,
                type=kind,
                title=title,
                body=body,
                reference_id=reference_id,
                reference_type=reference_type,
            )
            self.stats["Notifications"] += 1
            self._backdate(
                Notification,
                notification.pk,
                timezone.now() - timedelta(hours=self.rng.randint(1, 60)),
            )

    def _seed_activity_logs(self, ctx: dict) -> None:
        """Alimente le journal d'audit consulte par le super admin."""
        super_admin = ctx["users"]["super_admin"]
        if ctx.get("_logs_done") or super_admin.activity_logs.exists():
            return

        demande_id = (
            Company.objects.filter(status=CompanyStatus.INFO_REQUESTED)
            .values_list("pk", flat=True)
            .first()
        )
        entries = [
            ("company.approve", "company", ctx["main"].pk,
             {"statut": "active", "motif": "Dossier complet et conforme."}),
            ("company.suspend", "company", ctx["suspended"].pk,
             {"statut": "suspended", "motif": "Abonnement expire depuis 40 jours."}),
            ("company.request_info", "company", demande_id,
             {"statut": "info_requested", "pieces": ["RCCM", "attestation d'assurance"]}),
            ("subscription.create", "subscription", None,
             {"compagnie": ctx["main"].name, "forfait": "Premium Annuel"}),
            ("settings.commission_update", "global_setting", None,
             {"avant": "5.00", "apres": "6.00"}),
            ("user.deactivate", "user", ctx["voyageurs"][-1].pk,
             {"motif": "Compte inactif depuis 12 mois."}),
        ]

        for index, (action, entity_type, entity_id, details) in enumerate(entries):
            log = log_activity(
                super_admin,
                action,
                entity_type=entity_type,
                entity_id=entity_id,
                details=details,
                ip_address="41.203.0.{}".format(10 + index),
            )
            self._backdate(
                type(log), log.pk, timezone.now() - timedelta(days=index + 1, hours=3)
            )
            self.stats["Journaux d'activite"] += 1
        ctx["_logs_done"] = True

    def _seed_messages(self, ctx: dict) -> None:
        """Cree quelques messages agent <-> voyageur."""
        agent = ctx["users"]["main_agent_ouaga"]
        rich = ctx["rich"]
        if Message.objects.filter(sender=agent, recipient=rich).exists():
            return

        exchanges = [
            (
                agent, rich, "Rappel de depart",
                "Bonjour, votre bus part demain a 07h00. Merci de vous presenter "
                "30 minutes avant le depart.",
            ),
            (
                rich, agent, "Re : Rappel de depart",
                "Bonjour, c'est note. Puis-je ajouter un bagage supplementaire ?",
            ),
        ]
        for sender, recipient, subject, body in exchanges:
            message = Message.objects.create(
                sender=sender, recipient=recipient, subject=subject, body=body
            )
            self._backdate(
                Message, message.pk, timezone.now() - timedelta(hours=self.rng.randint(2, 30))
            )
            self.stats["Messages"] += 1

    # ------------------------------------------------------------------ #
    # Recapitulatif
    # ------------------------------------------------------------------ #

    def print_recap(self) -> None:
        """Affiche les comptes de connexion et les volumes crees."""
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("COMPTES DE DEMONSTRATION"))
        self.stdout.write(
            self.style.SUCCESS(f"Mot de passe commun a tous les comptes : {self.password}")
        )
        self.stdout.write("")
        self.stdout.write(
            f"  {'Role':<15} {'Identifiant':<15} {'Nom':<24} Contexte"
        )
        self.stdout.write(f"  {'-' * 15} {'-' * 15} {'-' * 24} {'-' * 45}")
        for role, phone, name, label in self.accounts:
            self.stdout.write(f"  {role:<15} {phone:<15} {name:<24} {label}")

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("VOLUMES CREES"))
        if not self.stats:
            self.stdout.write("  Aucun nouvel objet : la base contenait deja le jeu de demo.")
        for key in sorted(self.stats):
            self.stdout.write(f"  {key:.<28} {self.stats[key]}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                "Jeu de donnees pret. Connexion : POST /api/v1/auth/login/ "
                "avec {\"phone\": \"+22670000001\", \"password\": \"%s\"}" % self.password
            )
        )
