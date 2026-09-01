from drf_spectacular.utils import extend_schema
from rest_framework import mixins, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from utils.permissions import IsAgent

from .models import SyncConflict, SyncLog
from .serializers import (
    AgentOfflineDataSerializer,
    OfflineBookingReadSerializer,
    OfflineParcelReadSerializer,
    OfflineTripSerializer,
    SyncConflictSerializer,
    SyncLogSerializer,
    SyncPayloadSerializer,
    SyncResultSerializer,
)
from .services import get_offline_data, sync_agent_data


def _require_agent_profile(user):
    """Return the agent profile of an agent or raise 404 if none.

    Args:
        user: The authenticated agent user.

    Returns:
        The agent profile (carries company, station and vehicle).
    """
    profile = getattr(user, "agent_profile", None)
    if profile is None or profile.company_id is None:
        raise NotFound("Aucun profil agent associe a cet utilisateur.")
    return profile


class SyncView(GenericAPIView):
    """POST /api/v1/agent/sync/ — synchronise les donnees hors ligne de l'agent.

    Recoit un lot (`bookings`, `parcels`, `validations`) et l'integre dans une
    transaction atomique unique. Les conflits de siege sont resolus
    automatiquement (cf. business_rules.md §6).
    """

    permission_classes = [IsAgent]
    serializer_class = SyncPayloadSerializer

    @extend_schema(request=SyncPayloadSerializer, responses=SyncResultSerializer)
    def post(self, request, *args, **kwargs):
        _require_agent_profile(request.user)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        log = sync_agent_data(request.user, serializer.validated_data)
        return Response(SyncResultSerializer(log).data)


class SyncLogViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """GET /api/v1/agent/sync/logs/ — historique des synchronisations."""

    permission_classes = [IsAgent]
    serializer_class = SyncLogSerializer

    def get_queryset(self):
        _require_agent_profile(self.request.user)
        return (
            SyncLog.objects.filter(agent=self.request.user)
            .prefetch_related("conflicts")
        )


class SyncConflictListView(GenericAPIView):
    """GET /api/v1/agent/sync/conflicts/ — conflits resolus a la derniere sync."""

    permission_classes = [IsAgent]
    serializer_class = SyncConflictSerializer
    pagination_class = None

    def get(self, request, *args, **kwargs):
        _require_agent_profile(request.user)
        last_log = (
            SyncLog.objects.filter(agent=request.user).order_by("-created_at").first()
        )
        if last_log is None:
            return Response([])
        conflicts = SyncConflict.objects.filter(sync_log=last_log, resolved=True)
        return Response(SyncConflictSerializer(conflicts, many=True).data)


class OfflineDataView(GenericAPIView):
    """GET /api/v1/agent/offline-data/ — paquet de travail hors ligne du jour.

    Renvoie les voyages du jour de la gare/vehicule de l'agent, les reservations
    associees et les colis arrives en attente de remise.
    """

    permission_classes = [IsAgent]
    serializer_class = OfflineTripSerializer
    pagination_class = None

    @extend_schema(responses=AgentOfflineDataSerializer)
    def get(self, request, *args, **kwargs):
        _require_agent_profile(request.user)
        data = get_offline_data(request.user)
        return Response(
            {
                "trips": OfflineTripSerializer(data["trips"], many=True).data,
                "bookings": OfflineBookingReadSerializer(
                    data["bookings"], many=True
                ).data,
                "parcel_arrivals": OfflineParcelReadSerializer(
                    data["parcel_arrivals"], many=True
                ).data,
            }
        )
