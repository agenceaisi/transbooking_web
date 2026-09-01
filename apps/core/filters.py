import django_filters

from .models import ActivityLog


class ActivityLogFilter(django_filters.FilterSet):
    """Filtres du journal d'audit : auteur, type d'action, entite, dates."""

    user = django_filters.NumberFilter(field_name="user_id")
    action = django_filters.CharFilter(field_name="action", lookup_expr="icontains")
    entity_type = django_filters.CharFilter(field_name="entity_type", lookup_expr="iexact")
    date_from = django_filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    date_to = django_filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = ActivityLog
        fields = ["user", "action", "entity_type", "entity_id", "date_from", "date_to"]
