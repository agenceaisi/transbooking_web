from django.utils import timezone
from rest_framework import serializers

from .models import (
    Subscription,
    SubscriptionInvoice,
    SubscriptionPlan,
    SubscriptionStatus,
)
from .services import invoice_reference


class SubscriptionPlanSerializer(serializers.ModelSerializer):
    """Forfait d'abonnement (lecture et ecriture super admin)."""

    class Meta:
        model = SubscriptionPlan
        fields = [
            "id",
            "name",
            "description",
            "price",
            "duration_months",
            "features",
            "is_active",
            "created_at",
        ]
        read_only_fields = ["id", "created_at"]

    def validate_duration_months(self, value: int) -> int:
        if value < 1:
            raise serializers.ValidationError("La duree doit valoir au moins 1 mois.")
        return value

    def validate_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Le prix ne peut pas etre negatif.")
        return value


class SubscriptionReadSerializer(serializers.ModelSerializer):
    """Abonnement d'une compagnie (lecture)."""

    plan = SubscriptionPlanSerializer(read_only=True)
    company_name = serializers.CharField(source="company.name", read_only=True)
    status_display = serializers.CharField(source="get_status_display", read_only=True)

    class Meta:
        model = Subscription
        fields = [
            "id",
            "company",
            "company_name",
            "plan",
            "start_date",
            "end_date",
            "status",
            "status_display",
            "auto_renew",
            "created_at",
        ]

    def to_representation(self, instance: Subscription) -> dict:
        data = super().to_representation(instance)
        today = timezone.localdate()
        # Champs calcules attendus par le front (forfait courant + echeance).
        data["days_remaining"] = max((instance.end_date - today).days, 0)
        data["is_current"] = (
            instance.status == SubscriptionStatus.ACTIVE and instance.end_date >= today
        )
        data["renewal_date"] = data["end_date"]
        return data


class SubscriptionCreateSerializer(serializers.ModelSerializer):
    """Attribution d'un forfait a une compagnie (super admin)."""

    class Meta:
        model = Subscription
        fields = ["company", "plan", "start_date", "end_date", "auto_renew"]
        extra_kwargs = {
            "start_date": {"required": False},
            "end_date": {"required": False},
        }

    def validate_plan(self, plan: SubscriptionPlan) -> SubscriptionPlan:
        if not plan.is_active:
            raise serializers.ValidationError("Ce forfait n'est plus proposable.")
        return plan


class SubscriptionUpdateSerializer(serializers.ModelSerializer):
    """Activation / desactivation / prolongation d'un abonnement (super admin)."""

    class Meta:
        model = Subscription
        fields = ["plan", "start_date", "end_date", "status", "auto_renew"]

    def validate(self, attrs: dict) -> dict:
        start_date = attrs.get("start_date", self.instance.start_date)
        end_date = attrs.get("end_date", self.instance.end_date)
        if end_date < start_date:
            raise serializers.ValidationError(
                {"end_date": "La date de fin doit suivre la date de debut."}
            )
        return attrs


class SubscriptionInvoiceSerializer(serializers.ModelSerializer):
    """Facture d'un cycle d'abonnement."""

    reference = serializers.SerializerMethodField()
    plan_name = serializers.CharField(source="subscription.plan.name", read_only=True)

    class Meta:
        model = SubscriptionInvoice
        fields = [
            "id",
            "reference",
            "subscription",
            "plan_name",
            "amount",
            "paid_at",
            "created_at",
        ]

    def get_reference(self, obj: SubscriptionInvoice) -> str:
        return invoice_reference(obj)

    def to_representation(self, instance: SubscriptionInvoice) -> dict:
        data = super().to_representation(instance)
        data["is_paid"] = instance.paid_at is not None
        data["download_url"] = (
            f"/api/v1/company/subscription/invoices/{instance.pk}/download/"
        )
        return data
