from rest_framework import serializers

from apps.bookings.models import Booking

from .models import MOBILE_MONEY_METHODS, Payment, PaymentMethod, PaymentStatus
from .providers import mask_phone


def _mask(value: str) -> str:
    """Mask a sensitive value, keeping its last 4 characters.

    Args:
        value: The raw value.

    Returns:
        The masked value (e.g. ``****1234``), or an empty string.
    """
    if not value:
        return ""
    return f"****{value[-4:]}" if len(value) > 4 else "****"


def _validate_mobile_money(attrs: dict) -> dict:
    """Apply the Mobile Money constraints shared by the initiation serializers.

    Args:
        attrs: The validated field values.

    Returns:
        The unchanged ``attrs``.

    Raises:
        serializers.ValidationError: If the method is out of scope, or if a
            Mobile Money payment lacks the payer phone number.
    """
    method = attrs.get("method")
    if method == PaymentMethod.CARD:
        # Carte bancaire : hors perimetre tant qu'aucun PSP n'est contractualise.
        raise serializers.ValidationError(
            {"method": "Le paiement par carte n'est pas encore disponible."}
        )
    if method in MOBILE_MONEY_METHODS and not attrs.get("phone"):
        raise serializers.ValidationError(
            {"phone": "Numero du payeur requis pour un paiement Mobile Money."}
        )
    return attrs


class PaymentReadSerializer(serializers.ModelSerializer):
    """Lecture du statut d'un paiement (voyageur, agent, admin)."""

    method_display = serializers.CharField(source="get_method_display", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    ticket_number = serializers.CharField(
        source="booking.ticket_number", read_only=True, default=None
    )
    transaction_ref = serializers.SerializerMethodField()
    phone = serializers.SerializerMethodField()
    otp_expires_at = serializers.SerializerMethodField()
    otp_attempts_remaining = serializers.SerializerMethodField()

    class Meta:
        model = Payment
        fields = [
            "id",
            "ticket_number",
            "amount",
            "method",
            "method_display",
            "status",
            "status_display",
            "transaction_ref",
            "phone",
            "otp_expires_at",
            "otp_attempts_remaining",
            "receipt_url",
            "paid_at",
            "created_at",
        ]

    def get_transaction_ref(self, payment: Payment) -> str:
        # Donnee sensible : on ne renvoie que les 4 derniers caracteres.
        return _mask(payment.transaction_ref)

    def get_phone(self, payment: Payment) -> str:
        # Donnee personnelle : masquee comme la reference de transaction.
        return mask_phone(payment.phone)

    def _active_otp(self, payment: Payment):
        """Return the latest one-time code of a payment awaiting confirmation."""
        if payment.status != PaymentStatus.OTP_REQUIRED:
            return None
        return payment.otps.order_by("-created_at").first()

    def get_otp_expires_at(self, payment: Payment) -> str | None:
        otp = self._active_otp(payment)
        return otp.expires_at.isoformat() if otp else None

    def get_otp_attempts_remaining(self, payment: Payment) -> int | None:
        otp = self._active_otp(payment)
        return otp.attempts_remaining if otp else None


class PaymentInitiateSerializer(serializers.Serializer):
    """Initiation d'un paiement par un voyageur (reservation + moyen).

    Mobile Money : le paiement passe a `otp_required` et un code est envoye au
    payeur. Especes : le paiement reste `pending` jusqu'a encaissement guichet.
    """

    booking_id = serializers.PrimaryKeyRelatedField(
        queryset=Booking.objects.all(), source="booking", required=False
    )
    parcel_id = serializers.IntegerField(required=False)
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    phone = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        if attrs.get("parcel_id") is not None:
            # TODO: supporter le paiement de colis quand apps.parcels sera dispo.
            raise serializers.ValidationError(
                {"parcel_id": "Le paiement de colis n'est pas encore disponible."}
            )
        if attrs.get("booking") is None:
            raise serializers.ValidationError(
                {"booking_id": "Champ requis : booking_id."}
            )
        return _validate_mobile_money(attrs)


class PaymentVerifySerializer(serializers.Serializer):
    """Confirmation manuelle d'un paiement especes (saisie de la reference)."""

    transaction_ref = serializers.CharField(required=False, allow_blank=True, default="")


class PaymentOtpVerifySerializer(serializers.Serializer):
    """Saisie du code de confirmation Mobile Money."""

    otp = serializers.RegexField(
        r"^\d{4,8}$",
        error_messages={"invalid": "Le code de confirmation doit etre numerique."},
    )


class AgentPaymentSerializer(serializers.Serializer):
    """Encaissement au guichet : especes en une etape, Mobile Money par OTP."""

    booking_id = serializers.PrimaryKeyRelatedField(
        queryset=Booking.objects.all(), source="booking"
    )
    method = serializers.ChoiceField(choices=PaymentMethod.choices)
    transaction_ref = serializers.CharField(required=False, allow_blank=True, default="")
    phone = serializers.CharField(required=False, allow_blank=True, default="")

    def validate(self, attrs):
        return _validate_mobile_money(attrs)
