from django.conf import settings
from django.db import models

from utils.models import TimeStampedModel


class ParcelStatus(models.TextChoices):
    REGISTERED = "registered", "Enregistre"
    IN_TRANSIT = "in_transit", "En transit"
    ARRIVED = "arrived", "Arrive"
    NOTIFIED = "notified", "Destinataire prevenu"
    COLLECTED = "collected", "Remis"


class NotificationMethod(models.TextChoices):
    SMS = "sms", "SMS"
    CALL = "call", "Appel manuel"


class Parcel(TimeStampedModel):
    """Colis transporte d'une gare a une autre par une compagnie.

    Le tarif est calcule automatiquement a l'enregistrement via
    `services.calculate_tariff()` (tranches de distance, cf. business_rules.md
    §3). Peut etre enregistre hors ligne par un agent guichet.
    """

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.PROTECT,
        related_name="parcels",
    )
    # Voyage (bus) transportant le colis : facultatif a l'enregistrement.
    trip = models.ForeignKey(
        "trips.Trip",
        on_delete=models.SET_NULL,
        related_name="parcels",
        null=True,
        blank=True,
    )

    origin_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="parcels_sent",
    )
    destination_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="parcels_received",
    )
    origin_station = models.ForeignKey(
        "geography.Station",
        on_delete=models.SET_NULL,
        related_name="parcels_origin",
        null=True,
        blank=True,
    )
    destination_station = models.ForeignKey(
        "geography.Station",
        on_delete=models.SET_NULL,
        related_name="parcels_destination",
        null=True,
        blank=True,
    )

    # Expediteur et destinataire (le destinataire recoit le SMS d'arrivee).
    sender_name = models.CharField(max_length=150)
    sender_phone = models.CharField(max_length=30)
    recipient_name = models.CharField(max_length=150)
    recipient_phone = models.CharField(max_length=30)

    # Nature du contenu (ex: vetements, documents) — figure sur le bordereau.
    nature = models.CharField(max_length=100, blank=True)
    description = models.TextField(blank=True)
    weight_kg = models.DecimalField(max_digits=7, decimal_places=2)

    # Dimensions facultatives (cm) pour le calcul volumetrique / l'etiquette.
    length_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    width_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    height_cm = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)

    # Valeur declaree (FCFA) : base de couverture en cas de perte/dommage.
    declared_value = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Mention FRAGILE sur l'etiquette si True.
    is_fragile = models.BooleanField(default=False)
    photo = models.ImageField(upload_to="parcels/photos/", null=True, blank=True)

    # Calcule a l'enregistrement (poids x prix_par_kg + frais_fixes selon tranche).
    tariff = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Genere automatiquement : "COL" + annee + sequence a 6 chiffres (COL2026000456).
    tracking_number = models.CharField(max_length=20, unique=True)
    # PNG base64 encodant le tracking_number (jamais l'id DB).
    qr_code = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=ParcelStatus.choices,
        default=ParcelStatus.REGISTERED,
    )
    collected_at = models.DateTimeField(null=True, blank=True)

    # Agent guichet ayant enregistre le colis (null pour une saisie en ligne).
    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="registered_parcels",
        null=True,
        blank=True,
    )

    # Mode hors ligne (cf. CLAUDE.md « Mode hors ligne »).
    is_offline = models.BooleanField(default=False)
    offline_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Colis"
        verbose_name_plural = "Colis"

    def __str__(self) -> str:
        return self.tracking_number


class ParcelNotification(TimeStampedModel):
    """Notification envoyee au destinataire d'un colis (SMS ou appel manuel).

    La regle anti-doublon (cf. business_rules.md §3) interdit un second SMS pour
    un meme colis, ce qui rend la presence d'un enregistrement `method='sms'`
    significative.
    """

    parcel = models.ForeignKey(
        Parcel,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    method = models.CharField(
        max_length=10,
        choices=NotificationMethod.choices,
        default=NotificationMethod.SMS,
    )
    message = models.TextField(blank=True)
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="parcel_notifications",
        null=True,
        blank=True,
    )

    # Mode hors ligne (l'agent peut notifier sans connexion puis synchroniser).
    is_offline = models.BooleanField(default=False)
    offline_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Notification colis"
        verbose_name_plural = "Notifications colis"

    def __str__(self) -> str:
        return f"{self.get_method_display()} - {self.parcel.tracking_number}"
