from decimal import Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.geography.models import City, Station
from apps.trips.models import Trip

from .models import NotificationMethod, Parcel, ParcelNotification, ParcelStatus
from .services import build_tracking_history


def _mask_phone(phone: str) -> str:
    """Mask all but the last two digits of a phone number for public display."""
    if not phone:
        return ""
    visible = phone[-2:]
    return f"{'*' * max(len(phone) - 2, 0)}{visible}"


class ParcelNotificationSerializer(serializers.ModelSerializer):
    """Lecture d'une notification colis."""

    method_display = serializers.CharField(source="get_method_display", read_only=True)

    class Meta:
        model = ParcelNotification
        fields = ["id", "method", "method_display", "message", "created_at"]


class ParcelHistoryMixin:
    """Construit l'historique d'un colis a partir de ses evenements connus."""

    def get_history(self, parcel: Parcel) -> list:
        events = [
            {
                "event": "registered",
                "label": "Colis enregistre",
                "timestamp": parcel.created_at,
            }
        ]
        for notification in parcel.notifications.all():
            events.append(
                {
                    "event": f"notified_{notification.method}",
                    "label": notification.get_method_display(),
                    "timestamp": notification.created_at,
                }
            )
        if parcel.collected_at:
            events.append(
                {
                    "event": "collected",
                    "label": "Colis remis",
                    "timestamp": parcel.collected_at,
                }
            )
        return sorted(events, key=lambda event: event["timestamp"])


class ParcelHistoryEntrySerializer(serializers.Serializer):
    """Une etape horodatee de la chronologie de suivi d'un colis."""

    status = serializers.ChoiceField(choices=ParcelStatus.choices)
    status_display = serializers.CharField()
    location = serializers.CharField(allow_null=True)
    timestamp = serializers.DateTimeField()
    note = serializers.CharField(allow_null=True)


class ParcelTrackSerializer(serializers.ModelSerializer):
    """Suivi public d'un colis : statut + historique, sans donnees sensibles."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    origin_city = serializers.CharField(source="origin_city.name", read_only=True)
    destination_city = serializers.CharField(
        source="destination_city.name", read_only=True
    )
    recipient_phone = serializers.SerializerMethodField()
    current_location = serializers.SerializerMethodField()
    estimated_delivery = serializers.SerializerMethodField()
    history = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        fields = [
            "tracking_number",
            "status",
            "status_display",
            "origin_city",
            "destination_city",
            "recipient_name",
            "recipient_phone",
            "current_location",
            "estimated_delivery",
            "history",
        ]

    def get_recipient_phone(self, parcel: Parcel) -> str:
        return _mask_phone(parcel.recipient_phone)

    def get_current_location(self, parcel: Parcel) -> str | None:
        # Derivation honnete : on ne connait pas la position intermediaire reelle
        # d'un colis en transit, on renvoie donc null dans ce cas.
        if parcel.status == ParcelStatus.REGISTERED:
            return parcel.origin_city.name if parcel.origin_city_id else None
        if parcel.status in {
            ParcelStatus.ARRIVED,
            ParcelStatus.NOTIFIED,
            ParcelStatus.COLLECTED,
        }:
            return parcel.destination_city.name if parcel.destination_city_id else None
        return None

    @extend_schema_field(serializers.DateTimeField(allow_null=True))
    def get_estimated_delivery(self, parcel: Parcel):
        # Estimation = heure d'arrivee prevue du bus transporteur, tant que le
        # colis n'a pas ete remis. Aucune valeur inventee si le trajet est absent.
        if parcel.status == ParcelStatus.COLLECTED:
            return None
        trip = parcel.trip
        return trip.arrival_time if trip and trip.arrival_time else None

    @extend_schema_field(ParcelHistoryEntrySerializer(many=True))
    def get_history(self, parcel: Parcel) -> list:
        return build_tracking_history(parcel)


class ParcelReadSerializer(ParcelHistoryMixin, serializers.ModelSerializer):
    """Lecture detaillee d'un colis (agent, admin) avec historique complet."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)
    origin_city = serializers.CharField(source="origin_city.name", read_only=True)
    destination_city = serializers.CharField(
        source="destination_city.name", read_only=True
    )
    notifications = ParcelNotificationSerializer(many=True, read_only=True)
    history = serializers.SerializerMethodField()

    class Meta:
        model = Parcel
        fields = [
            "id",
            "tracking_number",
            "company",
            "trip",
            "origin_city",
            "destination_city",
            "origin_station",
            "destination_station",
            "sender_name",
            "sender_phone",
            "recipient_name",
            "recipient_phone",
            "description",
            "weight_kg",
            "tariff",
            "qr_code",
            "status",
            "status_display",
            "collected_at",
            "is_offline",
            "notifications",
            "history",
            "created_at",
            "updated_at",
        ]


class AgentParcelCreateSerializer(serializers.Serializer):
    """Enregistrement d'un colis au guichet (mode hors ligne supporte).

    La compagnie et la gare de depart sont deduites du profil agent dans la vue.
    Le tarif et le `tracking_number` sont calcules par le service, jamais fournis
    par le client (sauf `tracking_number` en mode hors ligne).
    """

    origin_city = serializers.PrimaryKeyRelatedField(queryset=City.objects.all())
    destination_city = serializers.PrimaryKeyRelatedField(queryset=City.objects.all())
    destination_station = serializers.PrimaryKeyRelatedField(
        queryset=Station.objects.all(), required=False, allow_null=True
    )
    trip = serializers.PrimaryKeyRelatedField(
        queryset=Trip.objects.all(), required=False, allow_null=True
    )
    sender_name = serializers.CharField()
    sender_phone = serializers.CharField()
    recipient_name = serializers.CharField()
    recipient_phone = serializers.CharField()
    description = serializers.CharField(required=False, allow_blank=True)
    weight_kg = serializers.DecimalField(
        max_digits=7, decimal_places=2, min_value=Decimal("0.1")
    )
    tracking_number = serializers.CharField(required=False, allow_blank=True)
    is_offline = serializers.BooleanField(required=False, default=False)
    offline_created_at = serializers.DateTimeField(required=False, allow_null=True)

    # Champs facultatifs non nullables en base : le client mobile (Flutter) serialise
    # ses DTO avec `null` explicite pour un champ non renseigne plutot que de l'omettre.
    _NULLABLE_OPTIONAL_FIELDS = ("description", "tracking_number", "is_offline")

    def to_internal_value(self, data):
        if hasattr(data, "items"):
            data = {
                key: value
                for key, value in data.items()
                if value is not None or key not in self._NULLABLE_OPTIONAL_FIELDS
            }
        return super().to_internal_value(data)

    def validate(self, attrs):
        if attrs["origin_city"] == attrs["destination_city"]:
            raise serializers.ValidationError(
                "La ville de depart et la ville d'arrivee doivent differer."
            )
        if attrs.get("is_offline") and not attrs.get("offline_created_at"):
            raise serializers.ValidationError(
                {"offline_created_at": "Date de saisie hors ligne requise."}
            )
        return attrs


class ParcelStatusSerializer(serializers.Serializer):
    """Changement manuel du statut d'un colis (admin compagnie)."""

    status = serializers.ChoiceField(choices=ParcelStatus.choices)


class ParcelUpdateSerializer(serializers.ModelSerializer):
    """Mise a jour partielle des infos d'un colis (admin compagnie)."""

    class Meta:
        model = Parcel
        fields = [
            "recipient_name",
            "recipient_phone",
            "sender_name",
            "sender_phone",
            "description",
            "destination_station",
            "trip",
        ]


class NotifySerializer(serializers.Serializer):
    """Parametre de la notification destinataire (SMS ou appel manuel)."""

    method = serializers.ChoiceField(
        choices=NotificationMethod.choices,
        required=False,
        default=NotificationMethod.SMS,
    )
