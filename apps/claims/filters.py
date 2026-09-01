from django_filters import rest_framework as filters

from .models import Claim


class ClaimFilter(filters.FilterSet):
    """Filtres de la liste admin : statut et type de reclamation."""

    class Meta:
        model = Claim
        fields = ["status", "claim_type"]
