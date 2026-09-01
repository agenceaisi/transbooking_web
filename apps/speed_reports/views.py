from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from utils.permissions import IsCompanyAdmin, IsSuperAdmin, IsVoyageur

from .models import SpeedReport
from .serializers import (
    SpeedReportCreateSerializer,
    SpeedReportReadSerializer,
    SpeedReportStatusSerializer,
)
from .services import create_speed_report, update_status


def _admin_company(user):
    """Return the company administered by a company admin or raise 404.

    Args:
        user: The authenticated company admin user.

    Returns:
        The administered company.
    """
    company = getattr(user, "administered_company", None)
    if company is None:
        raise NotFound("Aucune compagnie associee a cet utilisateur.")
    return company


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #


class SpeedReportViewSet(
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    """Depot d'un signalement d'exces de vitesse par un voyageur."""

    permission_classes = [IsVoyageur]
    serializer_class = SpeedReportCreateSerializer

    @extend_schema(
        request=SpeedReportCreateSerializer,
        responses={status.HTTP_201_CREATED: SpeedReportReadSerializer},
    )
    def create(self, request, *args, **kwargs):
        # La creation renvoie le serialiseur de lecture (id + reference + statut)
        # pour que l'ecran de confirmation affiche le numero de signalement.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        report = create_speed_report(serializer.validated_data, user=request.user)
        return Response(
            SpeedReportReadSerializer(report).data, status=status.HTTP_201_CREATED
        )


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


class CompanySpeedReportViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Signalements recus par la compagnie de l'admin courant."""

    permission_classes = [IsCompanyAdmin]
    serializer_class = SpeedReportReadSerializer

    def get_queryset(self):
        return SpeedReport.objects.filter(
            company=_admin_company(self.request.user)
        ).select_related("company")


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #


class SuperSpeedReportViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Tous les signalements de la plateforme + changement de statut (super)."""

    permission_classes = [IsSuperAdmin]
    serializer_class = SpeedReportReadSerializer

    def get_queryset(self):
        return SpeedReport.objects.select_related("company")

    def update(self, request, *args, **kwargs):
        """PATCH /super/speed-reports/{id}/ — changer le statut."""
        report = self.get_object()
        serializer = SpeedReportStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_status(report, serializer.validated_data["status"])
        return Response(SpeedReportReadSerializer(report).data)
