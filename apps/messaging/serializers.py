from rest_framework import serializers

from .models import Message


def _full_name(user) -> str:
    return f"{user.prenom} {user.nom}".strip()


class MessageReadSerializer(serializers.ModelSerializer):
    """Lecture d'un message (expediteur et destinataire resolus)."""

    sender_name = serializers.SerializerMethodField()
    recipient_name = serializers.SerializerMethodField()

    class Meta:
        model = Message
        fields = [
            "id",
            "sender",
            "sender_name",
            "recipient",
            "recipient_name",
            "subject",
            "body",
            "is_read",
            "created_at",
        ]

    def get_sender_name(self, obj) -> str:
        return _full_name(obj.sender)

    def get_recipient_name(self, obj) -> str:
        return _full_name(obj.recipient)


class MessageCreateSerializer(serializers.ModelSerializer):
    """Envoi d'un message. L'objet est obligatoire pour les agents."""

    class Meta:
        model = Message
        fields = ["recipient", "subject", "body"]

    def validate_recipient(self, recipient):
        request = self.context.get("request")
        if request is not None and recipient == request.user:
            raise serializers.ValidationError(
                "Vous ne pouvez pas vous envoyer un message a vous-meme."
            )
        return recipient

    def validate(self, attrs):
        request = self.context.get("request")
        role = getattr(getattr(request, "user", None), "role", None)
        role_name = getattr(role, "name", None)
        # L'objet est obligatoire lorsque l'expediteur est un agent.
        if role_name in {"agent_guichet", "controleur"} and not attrs.get("subject"):
            raise serializers.ValidationError(
                {"subject": "L'objet est obligatoire pour un agent."}
            )
        return attrs


class PassengerSerializer(serializers.Serializer):
    """Passager d'un voyage, pour le choix d'un destinataire de message."""

    id = serializers.IntegerField()
    full_name = serializers.CharField()
    phone = serializers.CharField()
