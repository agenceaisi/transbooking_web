from decimal import Decimal

from rest_framework import serializers

from apps.companies.models import Company, PaymentMethodChoice

from .models import ActivityLog


class ActivityLogSerializer(serializers.ModelSerializer):
    """Entree du journal d'audit (lecture super admin)."""

    user_name = serializers.SerializerMethodField()
    user_role = serializers.SerializerMethodField()

    class Meta:
        model = ActivityLog
        fields = [
            "id",
            "user",
            "user_name",
            "user_role",
            "action",
            "entity_type",
            "entity_id",
            "details",
            "ip_address",
            "created_at",
        ]

    def get_user_name(self, obj: ActivityLog) -> str:
        # user=None => action systeme (tache Celery, cron).
        if obj.user_id is None:
            return "Systeme"
        return f"{obj.user.prenom} {obj.user.nom}".strip() or obj.user.phone

    def get_user_role(self, obj: ActivityLog) -> str | None:
        if obj.user_id is None or obj.user.role_id is None:
            return None
        return obj.user.role.name


class SuperNotificationSerializer(serializers.Serializer):
    """Alerte du fil de supervision super admin (donnee calculee, non stockee)."""

    type = serializers.CharField()
    severity = serializers.CharField()
    title = serializers.CharField()
    body = serializers.CharField()
    reference_type = serializers.CharField()
    reference_id = serializers.IntegerField(allow_null=True)
    created_at = serializers.DateTimeField()


class GeneralSettingsSerializer(serializers.Serializer):
    """Parametres generaux de la plateforme (super admin).

    ``sms_provider`` est en lecture seule : les identifiants du fournisseur SMS
    restent dans les variables d'environnement et ne transitent jamais par l'API.
    """

    platform_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    support_phone = serializers.CharField(max_length=30, required=False, allow_blank=True)
    support_email = serializers.EmailField(required=False, allow_blank=True)
    maintenance_mode = serializers.BooleanField(required=False)
    sms_provider = serializers.CharField(read_only=True)


class CompanyCommissionSerializer(serializers.Serializer):
    """Surcharge de commission d'une compagnie."""

    company_id = serializers.IntegerField()
    company_name = serializers.CharField(read_only=True)
    commission_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        allow_null=True,
        help_text="null = la compagnie applique le taux global.",
    )

    def validate_company_id(self, value: int) -> int:
        if not Company.objects.filter(pk=value).exists():
            raise serializers.ValidationError("Compagnie inconnue.")
        return value

    def validate_commission_rate(self, value):
        if value is not None and not (Decimal("0") <= value <= Decimal("100")):
            raise serializers.ValidationError("Le taux doit etre compris entre 0 et 100.")
        return value


class CommissionSettingsSerializer(serializers.Serializer):
    """Taux de commission global + surcharges par compagnie."""

    global_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        required=False,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
    )
    company_overrides = CompanyCommissionSerializer(many=True, required=False)


class PlatformPaymentMethodSerializer(serializers.Serializer):
    """Activation d'un moyen de paiement au niveau plateforme."""

    method = serializers.ChoiceField(choices=PaymentMethodChoice.choices)
    method_display = serializers.CharField(read_only=True)
    is_active = serializers.BooleanField(default=True)


class PlatformPaymentMethodsSerializer(serializers.Serializer):
    """Enveloppe attendue en PATCH sur /super/settings/payment-methods/."""

    payment_methods = PlatformPaymentMethodSerializer(many=True)
