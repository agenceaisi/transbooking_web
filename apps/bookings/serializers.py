from decimal import Decimal

from rest_framework import serializers

from apps.trips.models import Trip

from .models import (
    Baggage,
    BaggageLocation,
    BoardingValidation,
    Booking,
    BookingStatus,
    Gender,
    IdType,
    ScanLog,
)


class BaggageSerializer(serializers.ModelSerializer):
    """Lecture d'un bagage enregistre (ecran « Bagages » du voyageur)."""

    location_display = serializers.CharField(
        source="get_location_display", read_only=True
    )

    class Meta:
        model = Baggage
        fields = ["id", "label", "tag", "weight_kg", "location", "location_display"]


class BaggageWriteSerializer(serializers.Serializer):
    """Enregistrement d'un bagage pese au guichet (imbrique dans la reservation)."""

    label = serializers.CharField(max_length=100)
    weight_kg = serializers.DecimalField(
        max_digits=5, decimal_places=1, min_value=Decimal("0")
    )
    location = serializers.ChoiceField(
        choices=BaggageLocation.choices,
        required=False,
        default=BaggageLocation.HOLD,
    )


class TripSummarySerializer(serializers.ModelSerializer):
    """Resume d'un voyage embarque dans le detail d'une reservation."""

    origin_city = serializers.CharField(source="route.origin_city.name", read_only=True)
    destination_city = serializers.CharField(
        source="route.destination_city.name", read_only=True
    )
    # En-tete compagnie du billet (monogramme + nom sur la carte "Mon billet").
    company_name = serializers.CharField(source="route.company.name", read_only=True)
    company_sigle = serializers.CharField(
        source="route.company.sigle", read_only=True, allow_blank=True
    )

    class Meta:
        model = Trip
        fields = [
            "id",
            "origin_city",
            "destination_city",
            "company_name",
            "company_sigle",
            "departure_time",
            "arrival_time",
            "status",
        ]


class BookingReadSerializer(serializers.ModelSerializer):
    """Lecture detaillee d'une reservation (voyageur, agent, admin)."""

    trip = TripSummarySerializer(read_only=True)
    passenger_name = serializers.CharField(read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    is_boarded = serializers.SerializerMethodField()
    baggage = BaggageSerializer(many=True, read_only=True)
    baggage_total_weight_kg = serializers.SerializerMethodField()

    class Meta:
        model = Booking
        fields = [
            "id",
            "ticket_number",
            "trip",
            "first_name",
            "last_name",
            "passenger_name",
            "phone",
            "seat_number",
            "amount",
            "payment_method",
            "qr_code",
            "status",
            "status_display",
            "is_offline",
            "is_boarded",
            "baggage",
            "baggage_total_weight_kg",
            "created_at",
            "updated_at",
        ]

    def get_is_boarded(self, booking: Booking) -> bool:
        return hasattr(booking, "boarding_validation")

    def get_baggage_total_weight_kg(self, booking: Booking) -> str:
        # Poids total affiche sur l'ecran « Bagages » (somme des bagages peses).
        total = sum((bag.weight_kg for bag in booking.baggage.all()), Decimal("0"))
        return f"{total:.1f}"


class BookingCreateSerializer(serializers.Serializer):
    """Creation d'une reservation par un voyageur authentifie.

    L'identite du passager reprend par defaut le compte voyageur. Le siege est
    auto-attribue si non fourni. La reservation est creee au statut `pending`
    (paiement a confirmer).
    """

    trip = serializers.PrimaryKeyRelatedField(queryset=Trip.objects.all())
    seat_number = serializers.CharField(required=False, allow_blank=True)
    first_name = serializers.CharField(required=False)
    last_name = serializers.CharField(required=False)
    phone = serializers.CharField(required=False)

    def validate_trip(self, trip: Trip) -> Trip:
        if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
            raise serializers.ValidationError(
                "Ce voyage n'est plus ouvert a la reservation."
            )
        return trip

    def to_internal_value(self, data):
        attrs = super().to_internal_value(data)
        user = self.context["request"].user
        attrs.setdefault("first_name", user.prenom)
        attrs.setdefault("last_name", user.nom)
        if not attrs.get("phone"):
            attrs["phone"] = user.phone
        attrs["user"] = user
        attrs["amount"] = attrs["trip"].price
        attrs["status"] = BookingStatus.PENDING
        return attrs


class AgentBookingCreateSerializer(serializers.Serializer):
    """Enregistrement d'un passager au guichet (mode hors ligne supporte).

    L'agent encaisse au guichet : la reservation est creee au statut `paid`.
    `transaction_ref` est requis pour les paiements non-especes.
    """

    trip = serializers.PrimaryKeyRelatedField(queryset=Trip.objects.all())
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    phone = serializers.CharField()
    gender = serializers.ChoiceField(
        choices=Gender.choices, required=False, allow_blank=True
    )
    id_type = serializers.ChoiceField(
        choices=IdType.choices, required=False, default=IdType.NONE
    )
    id_number = serializers.CharField(required=False, allow_blank=True)
    seat_number = serializers.CharField(required=False, allow_blank=True)
    amount = serializers.DecimalField(
        max_digits=10, decimal_places=2, required=False
    )
    payment_method = serializers.CharField()
    transaction_ref = serializers.CharField(required=False, allow_blank=True)
    discount_code = serializers.CharField(required=False, allow_blank=True)
    ticket_number = serializers.CharField(required=False, allow_blank=True)
    is_offline = serializers.BooleanField(required=False, default=False)
    offline_created_at = serializers.DateTimeField(required=False, allow_null=True)
    # Bagages peses enregistres au guichet (facultatif).
    baggage = BaggageWriteSerializer(many=True, required=False)

    def validate_trip(self, trip: Trip) -> Trip:
        if trip.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
            raise serializers.ValidationError(
                "Ce voyage n'est plus ouvert a la reservation."
            )
        return trip

    def validate(self, attrs):
        method = attrs.get("payment_method")
        if method and method != "cash" and not attrs.get("transaction_ref"):
            raise serializers.ValidationError(
                {"transaction_ref": "Reference de transaction requise hors especes."}
            )
        if attrs.get("is_offline") and not attrs.get("offline_created_at"):
            raise serializers.ValidationError(
                {"offline_created_at": "Date de saisie hors ligne requise."}
            )
        id_type = attrs.get("id_type") or IdType.NONE
        if id_type != IdType.NONE and not attrs.get("id_number"):
            raise serializers.ValidationError(
                {"id_number": "Numero de piece requis si id_type est renseigne."}
            )
        return attrs

    # Champs facultatifs non nullables en base : le client mobile (Flutter) serialise
    # ses DTO avec `null` explicite pour un champ non renseigne plutot que de l'omettre.
    _NULLABLE_OPTIONAL_FIELDS = (
        "gender",
        "id_type",
        "id_number",
        "seat_number",
        "amount",
        "transaction_ref",
        "discount_code",
        "ticket_number",
        "is_offline",
        "baggage",
    )

    def to_internal_value(self, data):
        if hasattr(data, "items"):
            data = {
                key: value
                for key, value in data.items()
                if value is not None or key not in self._NULLABLE_OPTIONAL_FIELDS
            }
        attrs = super().to_internal_value(data)
        attrs.setdefault("amount", attrs["trip"].price)
        attrs["status"] = BookingStatus.PAID
        attrs.pop("transaction_ref", None)
        return attrs


class AgentBookingCancelSerializer(serializers.Serializer):
    """Annulation d'un billet au guichet (motif libre, cf. requetes agent §1)."""

    reason = serializers.CharField(required=False, allow_blank=True, default="")


class BoardingValidationSerializer(serializers.ModelSerializer):
    """Lecture d'un embarquement."""

    ticket_number = serializers.CharField(
        source="booking.ticket_number", read_only=True
    )
    passenger_name = serializers.CharField(
        source="booking.passenger_name", read_only=True
    )
    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = BoardingValidation
        fields = [
            "id",
            "ticket_number",
            "passenger_name",
            "method",
            "method_display",
            "boarded_at",
            "is_offline",
        ]


class BoardingValidationSummarySerializer(serializers.Serializer):
    """Reponse reelle de `POST /agent/trips/{id}/boarding/validate/`.

    A ne pas confondre avec `BoardingValidationSerializer` (lecture d'un
    embarquement individuel) : ce recapitulatif verrouille l'embarquement du
    voyage entier (cf. requetes agent §3).
    """

    trip = serializers.IntegerField()
    total_paid = serializers.IntegerField()
    boarded = serializers.IntegerField()
    not_boarded = serializers.IntegerField()
    locked = serializers.BooleanField()


class ScanRequestSerializer(serializers.Serializer):
    """Corps de `POST /api/v1/agent/scan/` : l'un des deux champs suffit."""

    qr_data = serializers.CharField(required=False, allow_blank=True)
    ticket_number = serializers.CharField(required=False, allow_blank=True)


class ScanResultTripSerializer(serializers.Serializer):
    """Voyage embarque dans le resultat d'un scan."""

    id = serializers.IntegerField()
    origin_city = serializers.CharField()
    destination_city = serializers.CharField()
    departure_time = serializers.DateTimeField()


class ScanResultBookingSerializer(serializers.Serializer):
    """Reservation embarquee dans le resultat d'un scan."""

    ticket_number = serializers.CharField()
    passenger_name = serializers.CharField()
    seat_number = serializers.CharField()
    status = serializers.CharField()
    trip = ScanResultTripSerializer()


class ScanResultSerializer(serializers.Serializer):
    """Reponse reelle de `POST /api/v1/agent/scan/` (cf. requetes agent §2).

    Un billet introuvable renvoie `404` (jamais ce corps avec `result: not_found`).
    """

    status = serializers.CharField()
    color = serializers.CharField()
    message = serializers.CharField()
    booking = ScanResultBookingSerializer()


class TicketPrintSerializer(serializers.Serializer):
    """Payload d'impression d'un billet au guichet (cf. PROMPT_SUP A7)."""

    ticket_number = serializers.CharField()
    passenger_name = serializers.CharField()
    phone = serializers.CharField()
    seat_number = serializers.CharField()
    amount = serializers.DecimalField(max_digits=10, decimal_places=2)
    status = serializers.CharField()
    company_name = serializers.CharField()
    origin_city = serializers.CharField()
    destination_city = serializers.CharField()
    departure_time = serializers.DateTimeField()
    qr_code = serializers.CharField()
    printed_at = serializers.DateTimeField()
    print_count = serializers.IntegerField()


class ScanLogSerializer(serializers.ModelSerializer):
    """Historique des scans d'un controleur."""

    scanned_at = serializers.DateTimeField(source="created_at", read_only=True)
    result_display = serializers.CharField(source="get_result_display", read_only=True)
    passenger_name = serializers.SerializerMethodField()
    seat_number = serializers.SerializerMethodField()

    class Meta:
        model = ScanLog
        fields = [
            "id",
            "ticket_number",
            "result",
            "result_display",
            "passenger_name",
            "seat_number",
            "scanned_at",
        ]

    def get_passenger_name(self, obj: ScanLog) -> str | None:
        # booking=None pour un scan infructueux (billet introuvable).
        return obj.booking.passenger_name if obj.booking_id else None

    def get_seat_number(self, obj: ScanLog) -> str | None:
        return obj.booking.seat_number if obj.booking_id else None
