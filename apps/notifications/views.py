from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Notification
from .serializers import NotificationSerializer
from .services import mark_all_read


class NotificationViewSet(
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Notifications in-app de l'utilisateur courant : liste et marquage lu."""

    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer

    def get_queryset(self):
        # Les non lues d'abord, puis les plus recentes.
        return Notification.objects.filter(user=self.request.user).order_by(
            "is_read", "-created_at"
        )

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        """POST /notifications/{id}/read/ — marquer une notification comme lue."""
        notification = self.get_object()
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read", "updated_at"])
        return Response(NotificationSerializer(notification).data)

    @action(detail=False, methods=["post"], url_path="read-all")
    def read_all(self, request):
        """POST /notifications/read-all/ — tout marquer comme lu."""
        updated = mark_all_read(request.user)
        return Response({"updated": updated})
