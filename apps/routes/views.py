from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from utils.permissions import IsCompanyAdmin

from .models import Route, RouteStop
from .serializers import RouteSerializer, RouteStopSerializer
from .services import duplicate_reverse_route


class CompanyScopedMixin:
    """Restreint l'acces aux objets de la compagnie du company admin courant."""

    permission_classes = [IsCompanyAdmin]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company


class RouteViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """CRUD des trajets de la compagnie du company admin courant."""

    serializer_class = RouteSerializer
    filterset_fields = ["origin_city", "destination_city", "is_active"]

    def get_queryset(self):
        return (
            Route.objects.filter(company=self.get_company())
            .select_related("origin_city", "destination_city")
            .prefetch_related("stops")
        )

    def perform_create(self, serializer):
        serializer.save(company=self.get_company())

    @action(detail=True, methods=["post"])
    def duplicate(self, request, pk=None):
        route = self.get_object()
        reverse = duplicate_reverse_route(route)
        serializer = self.get_serializer(reverse)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class RouteStopViewSet(CompanyScopedMixin, viewsets.ModelViewSet):
    """CRUD des escales d'un trajet (URL imbriquee sous /routes/{route_pk}/)."""

    serializer_class = RouteStopSerializer

    def get_route(self) -> Route:
        try:
            return Route.objects.get(
                pk=self.kwargs["route_pk"], company=self.get_company()
            )
        except Route.DoesNotExist:
            raise NotFound("Trajet introuvable.")

    def get_queryset(self):
        return RouteStop.objects.filter(route=self.get_route()).select_related("city")

    def perform_create(self, serializer):
        serializer.save(route=self.get_route())
