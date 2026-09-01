from rest_framework import serializers

from .models import Route, RouteStop


class RouteStopSerializer(serializers.ModelSerializer):
    """Escale d'un trajet. `route` est deduit de l'URL imbriquee."""

    city_name = serializers.CharField(source="city.name", read_only=True)

    class Meta:
        model = RouteStop
        fields = [
            "id",
            "city",
            "city_name",
            "stop_order",
            "stop_price",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class RouteSerializer(serializers.ModelSerializer):
    """Trajet d'une compagnie. `company` est deduite de l'utilisateur courant."""

    origin_city_name = serializers.CharField(source="origin_city.name", read_only=True)
    destination_city_name = serializers.CharField(
        source="destination_city.name", read_only=True
    )
    stops = RouteStopSerializer(many=True, read_only=True)

    class Meta:
        model = Route
        fields = [
            "id",
            "origin_city",
            "origin_city_name",
            "destination_city",
            "destination_city_name",
            "origin_station",
            "destination_station",
            "distance_km",
            "base_price",
            "duration_minutes",
            "is_active",
            "stops",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "stops", "created_at", "updated_at"]

    def validate(self, attrs):
        origin = attrs.get("origin_city", getattr(self.instance, "origin_city", None))
        destination = attrs.get(
            "destination_city", getattr(self.instance, "destination_city", None)
        )
        if origin and destination and origin == destination:
            raise serializers.ValidationError(
                "La ville de depart et la ville d'arrivee doivent etre differentes."
            )
        return attrs
