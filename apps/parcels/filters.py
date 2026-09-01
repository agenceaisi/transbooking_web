from django_filters import rest_framework as filters

from .models import Parcel


class ParcelFilter(filters.FilterSet):
    """Filtres de la liste admin : statut, periode, ville de destination."""

    destination = filters.NumberFilter(field_name="destination_city_id")
    date_from = filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Parcel
        fields = ["status", "destination", "date_from", "date_to"]
