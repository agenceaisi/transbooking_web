from rest_framework import serializers

from apps.vehicles.services import get_available_seats

from .models import Trip


class TripWriteSerializer(serializers.ModelSerializer):
    """Creation/modification d'un voyage par le company admin.

    `available_seats` est initialise depuis `vehicle.total_seats` a la creation
    et n'est jamais fixe manuellement. `price` reprend `route.base_price` si non
    fourni.
    """

    class Meta:
        model = Trip
        fields = [
            "id",
            "route",
            "vehicle",
            "departure_time",
            "arrival_time",
            "price",
            "status",
            "cancellation_reason",
        ]
        read_only_fields = ["id", "cancellation_reason"]
        extra_kwargs = {"price": {"required": False}}

    def validate(self, attrs):
        vehicle = attrs.get("vehicle", getattr(self.instance, "vehicle", None))
        route = attrs.get("route", getattr(self.instance, "route", None))
        if route and vehicle and route.company_id != vehicle.company_id:
            raise serializers.ValidationError(
                "Le vehicule et le trajet doivent appartenir a la meme compagnie."
            )
        return attrs

    def create(self, validated_data):
        vehicle = validated_data["vehicle"]
        validated_data.setdefault("price", validated_data["route"].base_price)
        validated_data["available_seats"] = vehicle.total_seats
        return super().create(validated_data)


class TripReadSerializer(serializers.ModelSerializer):
    """Lecture detaillee d'un voyage (admin, agent, recherche publique)."""

    route_label = serializers.SerializerMethodField()
    origin_city = serializers.CharField(source="route.origin_city.name", read_only=True)
    destination_city = serializers.CharField(
        source="route.destination_city.name", read_only=True
    )
    vehicle_registration = serializers.CharField(
        source="vehicle.registration", read_only=True
    )
    vehicle_type = serializers.SerializerMethodField()
    total_seats = serializers.IntegerField(source="vehicle.total_seats", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    # Champs derives de trip.route, exposes pour les cartes de resultats (phase 4A/4B).
    company = serializers.IntegerField(source="route.company_id", read_only=True)
    company_name = serializers.CharField(source="route.company.name", read_only=True)
    company_sigle = serializers.CharField(source="route.company.sigle", read_only=True)
    company_rating = serializers.SerializerMethodField()
    is_direct = serializers.SerializerMethodField()
    stops_count = serializers.SerializerMethodField()
    duration_minutes = serializers.IntegerField(
        source="route.duration_minutes", read_only=True
    )

    class Meta:
        model = Trip
        fields = [
            "id",
            "route",
            "route_label",
            "origin_city",
            "destination_city",
            "vehicle",
            "vehicle_registration",
            "vehicle_type",
            "total_seats",
            "driver_name",
            "driver_phone",
            "departure_time",
            "arrival_time",
            "registration_closes_at",
            "price",
            "available_seats",
            "status",
            "status_display",
            "company",
            "company_name",
            "company_sigle",
            "company_rating",
            "is_direct",
            "stops_count",
            "duration_minutes",
            "created_at",
            "updated_at",
        ]

    def get_route_label(self, trip: Trip) -> str:
        return f"{trip.route.origin_city.name} - {trip.route.destination_city.name}"

    def _stops_count(self, trip: Trip) -> int:
        # `stops_count` est annote par la vue (cf. services.with_read_annotations) ;
        # repli sur une requete pour les objets non annotes (creation, annulation).
        count = getattr(trip, "stops_count", None)
        if count is None:
            count = trip.route.stops.count()
        return count

    def get_stops_count(self, trip: Trip) -> int:
        return self._stops_count(trip)

    def get_is_direct(self, trip: Trip) -> bool:
        return self._stops_count(trip) == 0

    def get_company_rating(self, trip: Trip) -> float | None:
        rating = getattr(trip, "company_rating", None)
        return round(float(rating), 1) if rating is not None else None

    def get_vehicle_type(self, trip: Trip) -> str | None:
        # Type de vehicule (standard/vip/vvip...) : chaine vide traitee comme absente.
        return trip.vehicle.vehicle_type or None


class TripDelaySerializer(serializers.Serializer):
    """Corps de `POST /api/v1/agent/trips/{id}/delay/` (cf. requetes agent §2)."""

    minutes = serializers.IntegerField(min_value=1)


class TripDetailSerializer(TripReadSerializer):
    """Detail public d'un voyage incluant la liste des sieges disponibles."""

    available_seat_numbers = serializers.SerializerMethodField()

    class Meta(TripReadSerializer.Meta):
        fields = TripReadSerializer.Meta.fields + ["available_seat_numbers"]

    def get_available_seat_numbers(self, trip: Trip) -> list[str]:
        return get_available_seats(trip.vehicle, trip)
