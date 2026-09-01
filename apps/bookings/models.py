from django.conf import settings
from django.db import models
from django.db.models import Q

from utils.models import TimeStampedModel


class BookingStatus(models.TextChoices):
    PENDING = "pending", "En attente"
    PAID = "paid", "Paye"
    CANCELLED = "cancelled", "Annule"
    REFUNDED = "refunded", "Rembourse"


class BoardingMethod(models.TextChoices):
    SCAN = "scan", "Scan QR"
    MANUAL = "manual", "Manuel"


class Gender(models.TextChoices):
    MALE = "M", "Masculin"
    FEMALE = "F", "Feminin"


class IdType(models.TextChoices):
    NONE = "none", "Aucune"
    CNIB = "cnib", "CNIB"
    PASSPORT = "passport", "Passeport"


class Booking(TimeStampedModel):
    """Reservation d'un siege sur un voyage.

    Coeur du systeme : peut etre creee par un voyageur (en ligne) ou par un
    agent guichet (eventuellement hors ligne). Le siege est decremente sur le
    voyage via `select_for_update()` (cf. business_rules.md §1).
    """

    trip = models.ForeignKey(
        "trips.Trip",
        on_delete=models.PROTECT,
        related_name="bookings",
    )
    # Voyageur authentifie a l'origine de la reservation (null pour un walk-in
    # enregistre au guichet sans compte client).
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="bookings",
        null=True,
        blank=True,
    )
    # Agent guichet ayant saisi la reservation (null pour une reservation en ligne).
    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="agent_bookings",
        null=True,
        blank=True,
    )

    # Identite du passager (peut differer du compte voyageur).
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)

    # Piece d'identite : donnee sensible, a exclure des listes (cf. mcd.md §7).
    id_type = models.CharField(
        max_length=20, choices=IdType.choices, default=IdType.NONE, blank=True
    )
    id_number = models.CharField(max_length=50, blank=True)

    # Ville de montee / descente : peuvent differer des extremites du trajet
    # (le passager peut monter a une escale). Facultatives.
    origin_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="bookings_boarding",
        null=True,
        blank=True,
    )
    destination_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="bookings_dropoff",
        null=True,
        blank=True,
    )

    # Bagages enregistres.
    has_luggage = models.BooleanField(default=False)
    luggage_qty = models.PositiveIntegerField(null=True, blank=True)

    seat_number = models.CharField(max_length=10)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    discount_code = models.CharField(max_length=30, blank=True)
    payment_method = models.CharField(max_length=20, blank=True)

    # Genere automatiquement : "BF" + annee + sequence a 6 chiffres (BF2026001234).
    ticket_number = models.CharField(max_length=20, unique=True)
    # PNG base64 encodant le ticket_number (jamais l'id DB).
    qr_code = models.TextField(blank=True)

    status = models.CharField(
        max_length=20,
        choices=BookingStatus.choices,
        default=BookingStatus.PENDING,
    )
    cancellation_reason = models.TextField(blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="cancelled_bookings",
        null=True,
        blank=True,
    )

    # Impression du billet au guichet (cf. POST /agent/bookings/{ticket}/print/).
    printed_at = models.DateTimeField(null=True, blank=True)
    print_count = models.PositiveIntegerField(default=0)

    # Mode hors ligne (cf. CLAUDE.md « Mode hors ligne »).
    is_offline = models.BooleanField(default=False)
    offline_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Reservation"
        verbose_name_plural = "Reservations"
        constraints = [
            # Un siege ne peut etre occupe que par une reservation active a la fois.
            models.UniqueConstraint(
                fields=["trip", "seat_number"],
                condition=~Q(status="cancelled"),
                name="unique_active_seat_per_trip",
            ),
        ]

    def __str__(self) -> str:
        return self.ticket_number

    @property
    def passenger_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class BaggageLocation(models.TextChoices):
    HOLD = "hold", "En soute"
    CABIN = "cabin", "En cabine"


class Baggage(TimeStampedModel):
    """Bagage enregistre au guichet et rattache a une reservation.

    Distinct de `Booking.has_luggage`/`luggage_qty` (declaration en ligne) : ici
    chaque bagage pese est trace avec une etiquette (`tag`) unique, imprimee au
    guichet, que le voyageur retrouve sur son ecran « Bagages ». La generation du
    `tag` est deleguee a `services.register_baggage` (pas de logique en modele).
    """

    booking = models.ForeignKey(
        Booking,
        on_delete=models.CASCADE,
        related_name="baggage",
    )
    label = models.CharField(max_length=100)  # ex: "Valise rigide"
    # Etiquette imprimee (ex: "TB-B-1042") — jamais l'id DB (cf. CLAUDE.md).
    tag = models.CharField(max_length=30, unique=True)
    weight_kg = models.DecimalField(max_digits=5, decimal_places=1)
    location = models.CharField(
        max_length=10,
        choices=BaggageLocation.choices,
        default=BaggageLocation.HOLD,
    )

    # Mode hors ligne (bagage enregistre au guichet sans connexion).
    is_offline = models.BooleanField(default=False)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Bagage"
        verbose_name_plural = "Bagages"

    def __str__(self) -> str:
        return f"{self.tag} - {self.label}"


class BoardingValidation(TimeStampedModel):
    """Embarquement d'un passager controle a la montee dans le vehicule."""

    booking = models.OneToOneField(
        Booking,
        on_delete=models.CASCADE,
        related_name="boarding_validation",
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="boarding_validations",
        null=True,
        blank=True,
    )
    method = models.CharField(
        max_length=10,
        choices=BoardingMethod.choices,
        default=BoardingMethod.SCAN,
    )
    boarded_at = models.DateTimeField()

    # Mode hors ligne (validation faite sans connexion puis synchronisee).
    is_offline = models.BooleanField(default=False)
    offline_created_at = models.DateTimeField(null=True, blank=True)
    synced_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-boarded_at"]
        verbose_name = "Embarquement"
        verbose_name_plural = "Embarquements"

    def __str__(self) -> str:
        return f"Embarquement {self.booking.ticket_number}"


class ScanResult(models.TextChoices):
    VALID = "valid", "Billet valide"
    UNPAID = "unpaid", "Paiement non confirme"
    CANCELLED = "cancelled", "Reservation annulee"
    REFUNDED = "refunded", "Reservation remboursee"
    ALREADY_BOARDED = "already_boarded", "Passager deja embarque"
    INVALID = "invalid", "Billet invalide"
    NOT_FOUND = "not_found", "Billet introuvable"


class ScanLog(TimeStampedModel):
    """Trace d'un scan de QR code par un controleur.

    Alimente `GET /api/v1/agent/scan/history/` (50 derniers scans de l'agent).
    Un scan sans correspondance est egalement trace (`result = not_found`) pour
    diagnostiquer les billets illisibles ou falsifies.
    """

    agent = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="scan_logs",
    )
    booking = models.ForeignKey(
        Booking,
        on_delete=models.SET_NULL,
        related_name="scans",
        null=True,
        blank=True,
    )
    # Conserve meme sans reservation associee (scan infructueux).
    ticket_number = models.CharField(max_length=20)
    result = models.CharField(max_length=20, choices=ScanResult.choices)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Scan de billet"
        verbose_name_plural = "Scans de billet"
        indexes = [
            models.Index(fields=["agent", "-created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.ticket_number} - {self.result}"
