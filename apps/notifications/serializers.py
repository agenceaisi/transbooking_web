from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Lecture d'une notification in-app de l'utilisateur courant."""

    type_display = serializers.CharField(source="get_type_display", read_only=True)

    class Meta:
        model = Notification
        fields = [
            "id",
            "type",
            "type_display",
            "title",
            "body",
            "is_read",
            "reference_id",
            "reference_type",
            "created_at",
        ]
        read_only_fields = fields
