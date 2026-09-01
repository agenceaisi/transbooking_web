from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.bookings.models import Booking
from apps.bookings.serializers import BaggageWriteSerializer
from apps.parcels.models import Parcel
from apps.trips.models import Trip

from .models import SyncConflict, SyncConflictType, SyncEntity, SyncLog


# --------------------------------------------------------------------------- #
# Payload de synchronisation (entree)
# --------------------------------------------------------------------------- #


class OfflineBookingSerializer(serializers.Serializer):
    """Reservation saisie hors ligne par un agent guichet.

    Le `ticket_number` est genere localement par l'agent ; il sert de cle
    d'idempotence cote serveur (cf. business_rules.md §6).
    """

    ticket_number = serializers.CharField(max_length=20)
    trip_id = serializers.IntegerField()
    first_name = serializers.CharField(max_length=100)
    last_name = serializers.CharField(max_length=100)
    phone = serializers.CharField(max_length=30)
    seat_number = serializers.CharField(
        max_length=10, required=False, allow_blank=True
    )
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    payment_method = serializers.CharField(
        max_length=20, required=False, allow_blank=True
    )
    # Reference de transaction Mobile Money saisie par l'agent (comme en ligne) :
    # requise hors especes, y compris pour une vente saisie hors connexion.
    transaction_ref = serializers.CharField(
        max_length=100, required=False, allow_blank=True, allow_null=True
    )
    # Bagages peses au guichet hors ligne (meme forme qu'en ligne, cf.
    # AgentBookingCreateSerializer.baggage).
    baggage = BaggageWriteSerializer(many=True, required=False, default=list)
    offline_created_at = serializers.DateTimeField()

    def validate(self, attrs):
        # Meme regle que la creation directe (AgentBookingCreateSerializer) :
        # une vente non-especes exige une reference de transaction.
        method = (attrs.get("payment_method") or "").strip()
        if method and method != "cash" and not attrs.get("transaction_ref"):
            raise serializers.ValidationError(
                {"transaction_ref": "Reference de transaction requise hors especes."}
            )
        return attrs


class OfflineParcelSerializer(serializers.Serializer):
    """Colis enregistre hors ligne par un agent guichet."""

    tracking_number = serializers.CharField(max_length=20)
    origin_city = serializers.IntegerField()
    destination_city = serializers.IntegerField()
    destination_station = serializers.IntegerField(required=False, allow_null=True)
    trip = serializers.IntegerField(required=False, allow_null=True)
    sender_name = serializers.CharField(max_length=150)
    sender_phone = serializers.CharField(max_length=30)
    recipient_name = serializers.CharField(max_length=150)
    recipient_phone = serializers.CharField(max_length=30)
    description = serializers.CharField(required=False, allow_blank=True)
    weight_kg = serializers.DecimalField(max_digits=7, decimal_places=2)
    offline_created_at = serializers.DateTimeField()


class OfflineValidationSerializer(serializers.Serializer):
    """Embarquement valide hors ligne par un controleur."""

    ticket_number = serializers.CharField(max_length=20)
    offline_created_at = serializers.DateTimeField()


class OfflineCancellationSerializer(serializers.Serializer):
    """Annulation d'un billet au guichet, enregistree hors ligne (cf. requetes agent §1).

    Ne concerne qu'un billet **deja synchronise** avant la coupure (un billet cree
    hors ligne et jamais synchronise est simplement retire de l'outbox cote
    client, sans appel serveur).
    """

    ticket_number = serializers.CharField(max_length=20)
    reason = serializers.CharField(required=False, allow_blank=True, default="")
    offline_created_at = serializers.DateTimeField()


class OfflineParcelNotificationSerializer(serializers.Serializer):
    """« Marquer prevenu » d'un colis, enregistre hors ligne par un agent.

    Seul l'appel manuel (`call`) est synchronisable : un SMS ne peut pas partir
    hors ligne, l'app ne doit jamais laisser croire qu'un SMS a ete envoye.
    Le couple (`tracking_number`, `offline_created_at`) sert de cle d'idempotence.
    """

    tracking_number = serializers.CharField(max_length=20)
    method = serializers.ChoiceField(
        choices=[("call", "Appel manuel")],
        required=False,
        default="call",
    )
    offline_created_at = serializers.DateTimeField()


class SyncPayloadSerializer(serializers.Serializer):
    """Corps de `POST /api/v1/agent/sync/` : lots a synchroniser."""

    bookings = OfflineBookingSerializer(many=True, required=False, default=list)
    parcels = OfflineParcelSerializer(many=True, required=False, default=list)
    validations = OfflineValidationSerializer(many=True, required=False, default=list)
    parcel_notifications = OfflineParcelNotificationSerializer(
        many=True, required=False, default=list
    )
    cancellations = OfflineCancellationSerializer(many=True, required=False, default=list)


# --------------------------------------------------------------------------- #
# Lecture (sortie)
# --------------------------------------------------------------------------- #


class SyncConflictSerializer(serializers.ModelSerializer):
    """Lecture d'un conflit de synchronisation."""

    conflict_type_display = serializers.CharField(
        source="get_conflict_type_display", read_only=True
    )

    class Meta:
        model = SyncConflict
        fields = [
            "id",
            "entity",
            "conflict_type",
            "conflict_type_display",
            "reference",
            "original_seat",
            "assigned_seat",
            "resolution",
            "resolved",
            "created_at",
        ]


class SyncLogSerializer(serializers.ModelSerializer):
    """Lecture d'un journal de synchronisation avec ses conflits."""

    conflicts = SyncConflictSerializer(many=True, read_only=True)

    class Meta:
        model = SyncLog
        fields = [
            "id",
            "bookings_synced",
            "parcels_synced",
            "validations_synced",
            "parcel_notifications_synced",
            "cancellations_synced",
            "conflicts_count",
            "errors_count",
            "conflicts",
            "created_at",
        ]


class SyncSyncedCountsSerializer(serializers.Serializer):
    """Compteurs d'enregistrements integres a la synchronisation."""

    bookings = serializers.IntegerField()
    parcels = serializers.IntegerField()
    validations = serializers.IntegerField()
    parcel_notifications = serializers.IntegerField()
    cancellations = serializers.IntegerField()


class SyncResultConflictSerializer(serializers.Serializer):
    """Conflit de siege resolu automatiquement, renvoye par `POST /agent/sync/`.

    Seuls les conflits de siege reattribues apparaissent dans ``conflicts`` : ils
    sont toujours resolus (le prochain siege libre a ete attribue). Les rejets
    (voyage complet, voyage indisponible, donnee invalide) partent dans
    ``errors`` (cf. business_rules.md §6).
    """

    type = serializers.ChoiceField(
        choices=SyncConflictType.choices,
        help_text="Code du conflit ; toujours `seat_conflict` dans `conflicts`.",
    )
    ticket_number = serializers.CharField(
        help_text="Reference fonctionnelle de la reservation corrigee."
    )
    original_seat = serializers.CharField(help_text="Siege demande hors ligne.")
    assigned_seat = serializers.CharField(
        help_text="Siege reattribue automatiquement (a appliquer localement)."
    )
    message = serializers.CharField(help_text="Explication en francais clair.")


class SyncResultErrorSerializer(serializers.Serializer):
    """Enregistrement rejete lors d'une synchronisation (`POST /agent/sync/`).

    Un enregistrement est rejete lorsqu'il ne peut pas etre integre : voyage
    complet/indisponible ou donnee invalide. L'ecriture locale correspondante
    doit etre marquee en echec cote agent.
    """

    type = serializers.ChoiceField(
        choices=SyncConflictType.choices,
        help_text="Motif du rejet (`trip_full`, `trip_unavailable`, `invalid`...).",
    )
    entity = serializers.ChoiceField(
        choices=SyncEntity.choices,
        help_text="Type d'enregistrement rejete (`booking`/`parcel`/`validation`).",
    )
    reference = serializers.CharField(
        help_text="Reference fonctionnelle (`ticket_number`/`tracking_number`)."
    )
    message = serializers.CharField(help_text="Explication en francais clair.")


class SyncResultSerializer(serializers.Serializer):
    """Reponse de `POST /api/v1/agent/sync/` (cf. business_rules.md §6).

    Attention : ``conflicts`` et ``errors`` decrivent les descripteurs
    transitoires renvoyes par la synchronisation, PAS le schema du modele
    ``SyncConflict`` (celui-ci est expose par `GET /agent/sync/conflicts/`).
    """

    synced = serializers.SerializerMethodField()
    conflicts = serializers.SerializerMethodField()
    errors = serializers.SerializerMethodField()

    @extend_schema_field(SyncSyncedCountsSerializer)
    def get_synced(self, log: SyncLog) -> dict:
        return {
            "bookings": log.bookings_synced,
            "parcels": log.parcels_synced,
            "validations": log.validations_synced,
            "parcel_notifications": log.parcel_notifications_synced,
            "cancellations": log.cancellations_synced,
        }

    @extend_schema_field(SyncResultConflictSerializer(many=True))
    def get_conflicts(self, log: SyncLog) -> list:
        return getattr(log, "synced_conflicts", [])

    @extend_schema_field(SyncResultErrorSerializer(many=True))
    def get_errors(self, log: SyncLog) -> list:
        return getattr(log, "synced_errors", [])


# --------------------------------------------------------------------------- #
# Donnees du mode hors ligne
# --------------------------------------------------------------------------- #


class OfflineTripSerializer(serializers.ModelSerializer):
    """Voyage du jour expose pour le travail hors ligne."""

    origin_city = serializers.CharField(source="route.origin_city.name", read_only=True)
    destination_city = serializers.CharField(
        source="route.destination_city.name", read_only=True
    )
    vehicle = serializers.CharField(source="vehicle.registration", read_only=True)
    vehicle_type = serializers.SerializerMethodField()
    total_seats = serializers.IntegerField(source="vehicle.total_seats", read_only=True)
    seat_plan = serializers.JSONField(source="vehicle.seat_plan", read_only=True)

    class Meta:
        model = Trip
        fields = [
            "id",
            "origin_city",
            "destination_city",
            "departure_time",
            "registration_closes_at",
            "available_seats",
            "vehicle",
            "vehicle_type",
            "total_seats",
            "seat_plan",
            "status",
            "driver_name",
            "driver_phone",
        ]

    def get_vehicle_type(self, trip: Trip) -> str | None:
        return trip.vehicle.vehicle_type or None


class OfflineBookingReadSerializer(serializers.ModelSerializer):
    """Reservation embarquee dans le paquet hors ligne (donnees minimales)."""

    passenger_name = serializers.CharField(read_only=True)

    class Meta:
        model = Booking
        fields = [
            "id",
            "ticket_number",
            "trip_id",
            "passenger_name",
            "phone",
            "seat_number",
            "qr_code",
            "status",
        ]


class OfflineParcelReadSerializer(serializers.ModelSerializer):
    """Colis en attente de remise expose pour le travail hors ligne."""

    destination_city = serializers.CharField(
        source="destination_city.name", read_only=True
    )

    class Meta:
        model = Parcel
        fields = [
            "tracking_number",
            "recipient_name",
            "recipient_phone",
            "destination_city",
            "status",
        ]


class AgentOfflineDataSerializer(serializers.Serializer):
    """Reponse de `GET /api/v1/agent/offline-data/` : paquet de travail du jour.

    Enveloppe les trois listes du paquet hors ligne (voyages du jour,
    reservations associees, colis en attente de remise) dans un objet unique.
    """

    trips = OfflineTripSerializer(many=True)
    bookings = OfflineBookingReadSerializer(many=True)
    parcel_arrivals = OfflineParcelReadSerializer(many=True)
