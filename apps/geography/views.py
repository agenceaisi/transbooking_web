from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from rest_framework import mixins, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny

from utils.permissions import IsCompanyAdmin, IsSuperAdmin

from .models import City, Station
from .serializers import CitySerializer, StationSerializer


# --------------------------------------------------------------------------- #
# Villes
# --------------------------------------------------------------------------- #
class PublicCityViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Liste publique des villes desservies (cache 1h)."""

    queryset = City.objects.all()
    serializer_class = CitySerializer
    permission_classes = [AllowAny]
    pagination_class = None

    @method_decorator(cache_page(60 * 60))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


class SuperCityViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Gestion des villes par le super admin."""

    queryset = City.objects.all()
    serializer_class = CitySerializer
    permission_classes = [IsSuperAdmin]


# --------------------------------------------------------------------------- #
# Gares — isolation stricte par compagnie de l'utilisateur courant
# --------------------------------------------------------------------------- #
class StationViewSet(viewsets.ModelViewSet):
    """CRUD des gares de la compagnie du company admin courant."""

    serializer_class = StationSerializer
    permission_classes = [IsCompanyAdmin]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company

    def get_queryset(self):
        return Station.objects.filter(company=self.get_company()).select_related("city")

    def perform_create(self, serializer):
        serializer.save(company=self.get_company())
