from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.trips.models import Trip
from utils.permissions import IsAgent

from .models import Message
from .serializers import (
    MessageCreateSerializer,
    MessageReadSerializer,
    PassengerSerializer,
)
from .services import inbox_for, passenger_list


class MessageViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Messagerie de l'utilisateur courant : messages envoyes et recus."""

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return inbox_for(self.request.user)

    def get_serializer_class(self):
        if self.action == "create":
            return MessageCreateSerializer
        return MessageReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        message = serializer.save(sender=request.user)
        return Response(
            MessageReadSerializer(message).data, status=status.HTTP_201_CREATED
        )

    def retrieve(self, request, *args, **kwargs):
        message = self.get_object()
        # La lecture par le destinataire marque le message comme lu.
        if message.recipient_id == request.user.id and not message.is_read:
            message.is_read = True
            message.save(update_fields=["is_read", "updated_at"])
        return Response(MessageReadSerializer(message).data)


class TripPassengerListView(GenericAPIView):
    """GET /agent/trips/{id}/passenger-list/ — passagers d'un voyage (agent)."""

    permission_classes = [IsAgent]
    serializer_class = PassengerSerializer

    def get(self, request, trip_id):
        try:
            trip = Trip.objects.get(pk=trip_id)
        except Trip.DoesNotExist:
            raise NotFound("Voyage introuvable.")
        # Isolation multi-tenant : un agent ne voit que les voyages de sa compagnie.
        profile = getattr(request.user, "agent_profile", None)
        if profile and profile.company_id and trip.route.company_id != profile.company_id:
            raise NotFound("Voyage introuvable.")
        return Response(passenger_list(trip))
