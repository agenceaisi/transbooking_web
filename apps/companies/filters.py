from django_filters import rest_framework as filters

from .models import Company


class CompanyFilter(filters.FilterSet):
    """Filtres pour la liste super admin : statut et date de creation."""

    created_after = filters.DateFilter(field_name="created_at", lookup_expr="date__gte")
    created_before = filters.DateFilter(field_name="created_at", lookup_expr="date__lte")

    class Meta:
        model = Company
        fields = ["status", "city", "created_after", "created_before"]
