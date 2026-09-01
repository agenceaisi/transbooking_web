from django.core.exceptions import ValidationError as DjangoValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.reviews.services import company_rating_stats
from utils.validators import validate_phone_bf

from .models import (
    Company,
    CompanyNotificationSettings,
    CompanyPaymentMethod,
    CompanyStatus,
)
from .services import create_company_request


class CompanyPublicSerializer(serializers.ModelSerializer):
    """Fiche publique d'une compagnie (page d'accueil, recherche)."""

    logo = serializers.SerializerMethodField()
    rating = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = ["id", "name", "sigle", "logo", "description", "city", "rating"]

    def get_logo(self, obj: Company) -> str | None:
        if not obj.logo:
            return None
        request = self.context.get("request")
        url = obj.logo.url
        return request.build_absolute_uri(url) if request else url

    def get_rating(self, obj: Company) -> float | None:
        # `avg_rating` est annote par la vue quand l'app reviews est disponible.
        avg = getattr(obj, "avg_rating", None)
        return round(avg, 1) if avg is not None else None


class CompanyRouteSummarySerializer(serializers.Serializer):
    """Resume d'un trajet actif desservi par une compagnie (fiche publique)."""

    id = serializers.IntegerField()
    origin_city_name = serializers.CharField(source="origin_city.name")
    destination_city_name = serializers.CharField(source="destination_city.name")
    base_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = serializers.IntegerField(allow_null=True)


class CompanyPublicDetailSerializer(CompanyPublicSerializer):
    """Fiche publique detaillee : ajoute contact, trajets desservis et avis."""

    reviews = serializers.SerializerMethodField()
    routes = serializers.SerializerMethodField()
    reviews_count = serializers.SerializerMethodField()
    rating_breakdown = serializers.SerializerMethodField()

    class Meta(CompanyPublicSerializer.Meta):
        fields = CompanyPublicSerializer.Meta.fields + [
            "phone",
            "email",
            "routes",
            "reviews_count",
            "rating_breakdown",
            "reviews",
        ]

    def get_reviews(self, obj: Company) -> list:
        # Les avis sont charges separement via GET /reviews/?company_id= (pagine).
        return []

    @extend_schema_field(CompanyRouteSummarySerializer(many=True))
    def get_routes(self, obj: Company) -> list:
        routes = obj.routes.filter(is_active=True).select_related(
            "origin_city", "destination_city"
        )
        return CompanyRouteSummarySerializer(routes, many=True).data

    def _rating_stats(self, obj: Company) -> dict:
        # Memoisation : une seule agregation par compagnie pour count + breakdown.
        cache = getattr(self, "_stats_cache", None)
        if cache is None:
            cache = self._stats_cache = {}
        if obj.pk not in cache:
            cache[obj.pk] = company_rating_stats(obj)
        return cache[obj.pk]

    def get_reviews_count(self, obj: Company) -> int:
        return self._rating_stats(obj)["reviews_count"]

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_rating_breakdown(self, obj: Company) -> dict:
        return self._rating_stats(obj)["rating_breakdown"]


class CompanyPaymentMethodSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyPaymentMethod
        fields = ["method", "is_active"]


class CompanyNotificationSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyNotificationSettings
        fields = [
            "sms_booking_confirmation",
            "sms_departure_reminder",
            "sms_parcel_arrival",
        ]


class CompanyDetailSerializer(serializers.ModelSerializer):
    """Vue complete pour le super admin et le company admin."""

    active_payment_methods = serializers.SerializerMethodField()
    subscription_status = serializers.SerializerMethodField()

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "sigle",
            "description",
            "logo",
            "banner",
            "primary_color",
            "welcome_message",
            "city",
            "address",
            "phone",
            "email",
            "responsible_name",
            "responsible_phone",
            "rccm",
            "ifu",
            "commission_rate",
            "status",
            "rejection_reason",
            "suspension_reason",
            "info_request_message",
            "active_payment_methods",
            "subscription_status",
            "created_at",
            "updated_at",
        ]

    def get_active_payment_methods(self, obj: Company) -> list[str]:
        return [pm.method for pm in obj.payment_methods.all() if pm.is_active]

    def get_subscription_status(self, obj: Company) -> str | None:
        # Abonnement courant de la compagnie (OneToOne, peut etre absent).
        subscription = getattr(obj, "subscription", None)
        return getattr(subscription, "status", None) if subscription else None


class CompanyCreateSerializer(serializers.ModelSerializer):
    """Formulaire de creation d'une compagnie par le super admin."""

    class Meta:
        model = Company
        fields = [
            "id",
            "name",
            "sigle",
            "description",
            "city",
            "address",
            "phone",
            "email",
            "responsible_name",
            "responsible_phone",
            "rccm",
            "ifu",
            "commission_rate",
            "status",
        ]
        read_only_fields = ["id", "status"]

    def validate_name(self, value: str) -> str:
        name = value.strip()
        if Company.objects.filter(name__iexact=name).exists():
            raise serializers.ValidationError("Une compagnie porte deja ce nom.")
        return name

    def create(self, validated_data: dict) -> Company:
        # Une compagnie creee directement par le super admin est active d'emblee.
        validated_data["status"] = CompanyStatus.ACTIVE
        return super().create(validated_data)


class CompanyRegistrationRequestSerializer(serializers.Serializer):
    """Demande publique d'inscription d'une compagnie (aucun compte cree)."""

    company_name = serializers.CharField(max_length=150)
    manager_name = serializers.CharField(max_length=150)
    phone = serializers.CharField(max_length=30, validators=[validate_phone_bf])
    email = serializers.EmailField()
    city = serializers.CharField(max_length=100)
    documents = serializers.FileField(required=False, allow_null=True)

    def validate_company_name(self, value: str) -> str:
        name = value.strip()
        if Company.objects.filter(name__iexact=name).exists():
            raise serializers.ValidationError("Une compagnie porte deja ce nom.")
        return name

    def create(self, validated_data: dict) -> Company:
        try:
            return create_company_request(validated_data)
        except DjangoValidationError as exc:
            detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
            raise serializers.ValidationError(detail) from exc


class CompanyInfoRequestSerializer(serializers.Serializer):
    """Message du super admin demandant des informations complementaires."""

    message = serializers.CharField(allow_blank=False, trim_whitespace=True)

    def validate_message(self, value: str) -> str:
        message = value.strip()
        if not message:
            raise serializers.ValidationError("Le message est obligatoire.")
        return message


class CompanyRequestStatusSerializer(serializers.ModelSerializer):
    """Accuse de reception d'une demande d'inscription."""

    company_name = serializers.CharField(source="name", read_only=True)
    manager_name = serializers.CharField(source="responsible_name", read_only=True)
    phone = serializers.CharField(source="responsible_phone", read_only=True)

    class Meta:
        model = Company
        fields = [
            "id",
            "company_name",
            "manager_name",
            "phone",
            "email",
            "city",
            "status",
            "created_at",
        ]
        read_only_fields = fields


class CompanySettingsSerializer(serializers.ModelSerializer):
    """Parametres editables par le company admin (charte graphique, accueil)."""

    class Meta:
        model = Company
        fields = [
            "name",
            "sigle",
            "description",
            "logo",
            "banner",
            "primary_color",
            "welcome_message",
            "address",
            "phone",
            "email",
            "responsible_name",
            "responsible_phone",
        ]
