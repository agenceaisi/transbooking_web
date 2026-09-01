from django_filters import rest_framework as filters

from .models import Booking


class BookingFilter(filters.FilterSet):
    """Filtres de la liste admin : statut, voyage, route, periode."""

    route = filters.NumberFilter(field_name="trip__route_id")
    date_from = filters.DateFilter(
        field_name="trip__departure_time", lookup_expr="date__gte"
    )
    date_to = filters.DateFilter(
        field_name="trip__departure_time", lookup_expr="date__lte"
    )

    class Meta:
        model = Booking
        fields = ["status", "trip", "route", "payment_method", "date_from", "date_to"]
