from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel
from utils.validators import validate_phone_bf


class CompanyStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    INFO_REQUESTED = "info_requested", "Informations complementaires demandees"
    ACTIVE = "active", "Active"
    SUSPENDED = "suspended", "Suspendue"
    REJECTED = "rejected", "Rejetee"


# Statuts d'une demande d'inscription encore en cours d'instruction : le super
# admin peut encore approuver, rejeter ou demander des informations.
OPEN_REQUEST_STATUSES = (CompanyStatus.PENDING, CompanyStatus.INFO_REQUESTED)


class PaymentMethodChoice(models.TextChoices):
    CASH = "cash", "Especes"
    ORANGE_MONEY = "orange_money", "Orange Money"
    MOOV_MONEY = "moov_money", "Moov Money"
    CORIS_MONEY = "coris_money", "Coris Money"
    TELECEL_MONEY = "telecel_money", "Telecel Money"
    CARD = "card", "Carte bancaire"


def default_baggage_policy() -> dict:
    """Return the default passenger baggage policy for a new company.

    Displayed on the traveler "Bagages" screen (cf. maquette écran 7). A company
    can override any of these values from its admin settings.

    Returns:
        The default ``baggage_policy`` payload.
    """
    return {
        "franchise_kg": 20,
        "price_per_extra_kg": 250,
        "cabin_bag": "1 sac, 5 kg",
        "declared_value_max": 100000,
    }


def default_parcel_pricing_config() -> dict:
    """Return the default parcel pricing grid for a new company.

    Three distance tiers (cf. business_rules.md §3). Each tier carries a
    per-kilogram price and a fixed handling fee, both expressed in FCFA.

    Returns:
        The default ``parcel_pricing_config`` payload.
    """
    return {
        "tier_short": {"price_per_kg": 250, "fixed_fee": 500},
        "tier_medium": {"price_per_kg": 200, "fixed_fee": 750},
        "tier_long": {"price_per_kg": 150, "fixed_fee": 1000},
    }


class Company(TimeStampedModel):
    # Identite
    name = models.CharField(max_length=150, unique=True)
    sigle = models.CharField(max_length=30, blank=True)
    description = models.TextField(blank=True)
    logo = models.ImageField(upload_to="companies/logos/", null=True, blank=True)
    banner = models.ImageField(upload_to="companies/banners/", null=True, blank=True)
    primary_color = models.CharField(max_length=7, blank=True)  # ex: #1A73E8
    welcome_message = models.TextField(blank=True)

    # Localisation et contact
    city = models.CharField(max_length=100, blank=True)
    address = models.TextField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    # Responsable legal
    responsible_name = models.CharField(max_length=150, blank=True)
    responsible_phone = models.CharField(
        max_length=30,
        blank=True,
        validators=[validate_phone_bf],
    )

    # Informations administratives
    rccm = models.CharField(max_length=50, blank=True)  # Registre du commerce
    ifu = models.CharField(max_length=50, blank=True)  # Identifiant financier unique
    # Documents administratifs soumis a l'inscription (RCCM, agrement...).
    documents = models.FileField(upload_to="companies/documents/", null=True, blank=True)

    # Commission : NULL => on applique le taux global (cf. business_rules.md §2).
    commission_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Grille tarifaire colis stockee en JSON (tranches courte/moyenne/longue).
    # Utilisee par parcels.services.calculate_tariff (cf. business_rules.md §3).
    parcel_pricing_config = models.JSONField(default=default_parcel_pricing_config)

    # Regles de bagages voyageur (franchise, prix du kilo supplementaire...),
    # affichees sur l'ecran « Bagages » du voyageur.
    baggage_policy = models.JSONField(default=default_baggage_policy)

    status = models.CharField(
        max_length=20,
        choices=CompanyStatus.choices,
        default=CompanyStatus.PENDING,
    )
    rejection_reason = models.TextField(blank=True)
    suspension_reason = models.TextField(blank=True)
    # Message du super admin demandant des pieces/informations complementaires
    # a la compagnie demandeuse (statut info_requested).
    info_request_message = models.TextField(blank=True)

    # Compte company_admin proprietaire. Ajoute dans la migration 0002 car
    # users.AgentProfile depend deja de companies (evite la dependance circulaire).
    admin_user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="administered_company",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Compagnie"
        verbose_name_plural = "Compagnies"

    def __str__(self) -> str:
        return self.name


class CompanyPaymentMethod(TimeStampedModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="payment_methods",
    )
    method = models.CharField(max_length=20, choices=PaymentMethodChoice.choices)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = ("company", "method")
        ordering = ["method"]

    def __str__(self) -> str:
        return f"{self.company.name} - {self.method}"


class CompanyNotificationSettings(TimeStampedModel):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="notification_settings",
    )
    sms_booking_confirmation = models.BooleanField(default=True)
    sms_departure_reminder = models.BooleanField(default=True)
    sms_parcel_arrival = models.BooleanField(default=True)
    sms_claim_response = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Parametres de notification"
        verbose_name_plural = "Parametres de notification"

    def __str__(self) -> str:
        return f"Notifications - {self.company.name}"
