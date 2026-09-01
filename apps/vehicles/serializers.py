from rest_framework import serializers

from .models import Vehicle


class VehicleSerializer(serializers.ModelSerializer):
    """Vehicule d'une compagnie. `company` est deduite de l'utilisateur courant."""

    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Vehicle
        fields = [
            "id",
            "registration",
            "brand",
            "model",
            "vehicle_type",
            "total_seats",
            "status",
            "status_display",
            "seat_plan",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "status", "seat_plan", "created_at", "updated_at"]

    def validate_total_seats(self, value: int) -> int:
        if value <= 0:
            raise serializers.ValidationError("Le nombre de sieges doit etre positif.")
        return value


class SeatPlanSerializer(serializers.Serializer):
    """Lecture/ecriture du plan des sieges (JSON) d'un vehicule."""

    layout = serializers.ListField(
        child=serializers.ListField(),
        help_text="Rangees de numeros de siege, ex: [[1, 2], [3, 4]].",
    )
    reserved = serializers.ListField(
        required=False,
        default=list,
        help_text="Numeros de siege non commercialisables (chauffeur, hotesse...).",
    )

    def validate_layout(self, value):
        if not value:
            raise serializers.ValidationError("Le plan doit contenir au moins une rangee.")
        return value
