from rest_framework import serializers

from .models import City, Station


class CitySerializer(serializers.ModelSerializer):
    """Ville desservie par le reseau (lecture publique, creation super admin)."""

    class Meta:
        model = City
        fields = ["id", "name", "region"]

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if City.objects.filter(name__iexact=name).exists():
            raise serializers.ValidationError("Cette ville existe deja.")
        return name


class StationSerializer(serializers.ModelSerializer):
    """Gare d'une compagnie. `company` est deduite de l'utilisateur courant."""

    city_name = serializers.CharField(source="city.name", read_only=True)

    class Meta:
        model = Station
        fields = [
            "id",
            "city",
            "city_name",
            "name",
            "address",
            "localisation",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]
