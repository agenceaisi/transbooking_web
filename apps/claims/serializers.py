from rest_framework import serializers

from .models import Claim, ClaimAttachment, ClaimStatus

# Contraintes de stockage des pieces jointes (cf. maquette « Nouvelle reclamation »).
MAX_ATTACHMENT_SIZE = 10 * 1024 * 1024  # 10 Mo
ALLOWED_ATTACHMENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/pdf",
}


def validate_claim_attachment(uploaded_file):
    """Reject attachments over 10 MB or outside the allowed PDF/photo types.

    Args:
        uploaded_file: The uploaded file to validate.

    Returns:
        The unchanged ``uploaded_file``.

    Raises:
        serializers.ValidationError: If the file is too large or of a type
            other than JPEG, PNG, WebP or PDF.
    """
    if uploaded_file.size > MAX_ATTACHMENT_SIZE:
        raise serializers.ValidationError(
            "La piece jointe ne doit pas depasser 10 Mo."
        )
    content_type = getattr(uploaded_file, "content_type", "") or ""
    if content_type not in ALLOWED_ATTACHMENT_TYPES:
        raise serializers.ValidationError(
            "Format non supporte : joignez un PDF ou une image (JPEG, PNG, WebP)."
        )
    return uploaded_file


class ClaimAttachmentSerializer(serializers.ModelSerializer):
    """Lecture d'une piece jointe (URL du fichier + metadonnees)."""

    class Meta:
        model = ClaimAttachment
        fields = ["id", "file", "original_name", "content_type", "size", "created_at"]


class ClaimAttachmentUploadSerializer(serializers.Serializer):
    """Ajout d'une piece jointe a une reclamation existante (multipart)."""

    file = serializers.FileField(validators=[validate_claim_attachment])


class ClaimReadSerializer(serializers.ModelSerializer):
    """Lecture detaillee d'une reclamation (voyageur, admin, super admin)."""

    claim_type_display = serializers.CharField(
        source="get_claim_type_display", read_only=True
    )
    status_display = serializers.CharField(
        source="get_status_display", read_only=True
    )
    company_name = serializers.CharField(source="company.name", read_only=True)
    ticket_number = serializers.CharField(
        source="booking.ticket_number", read_only=True, default=None
    )
    # Annote par services.annotated_claims() — absent => False.
    is_overdue = serializers.BooleanField(read_only=True, default=False)
    attachments = ClaimAttachmentSerializer(many=True, read_only=True)

    class Meta:
        model = Claim
        fields = [
            "id",
            "company",
            "company_name",
            "booking",
            "ticket_number",
            "claim_type",
            "claim_type_display",
            "subject",
            "description",
            "status",
            "status_display",
            "response",
            "responded_at",
            "is_overdue",
            "attachments",
            "created_at",
            "updated_at",
        ]


class ClaimCreateSerializer(serializers.ModelSerializer):
    """Depot d'une reclamation par un voyageur.

    La compagnie peut etre fournie directement ou deduite de la reservation
    referencee. La reservation doit appartenir au voyageur courant. Une piece
    jointe facultative (`attachment`, multipart) peut accompagner le depot.
    """

    # Champ d'ecriture seule : la vue le detache pour creer la ClaimAttachment.
    attachment = serializers.FileField(
        required=False, write_only=True, validators=[validate_claim_attachment]
    )

    class Meta:
        model = Claim
        fields = [
            "company",
            "booking",
            "claim_type",
            "subject",
            "description",
            "attachment",
        ]
        extra_kwargs = {"company": {"required": False}}

    def validate_booking(self, booking):
        request = self.context.get("request")
        if booking is not None and request is not None:
            if booking.user_id != request.user.id:
                raise serializers.ValidationError(
                    "Cette reservation ne vous appartient pas."
                )
        return booking

    def validate(self, attrs):
        booking = attrs.get("booking")
        company = attrs.get("company")
        if booking is not None:
            # La compagnie est celle qui exploite le trajet de la reservation.
            attrs["company"] = booking.trip.route.company
        elif company is None:
            raise serializers.ValidationError(
                {"company": "La compagnie ou une reservation est obligatoire."}
            )
        return attrs


class ClaimRespondSerializer(serializers.Serializer):
    """Reponse d'un admin de compagnie a une reclamation."""

    response = serializers.CharField()
    status = serializers.ChoiceField(
        choices=[
            ClaimStatus.IN_PROGRESS,
            ClaimStatus.RESOLVED,
            ClaimStatus.CLOSED,
        ],
        default=ClaimStatus.RESOLVED,
    )
