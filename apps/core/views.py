from drf_spectacular.utils import (
    OpenApiExample,
    OpenApiParameter,
    OpenApiResponse,
    extend_schema,
)
from rest_framework import status
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response

from apps.companies.models import Company
from utils.permissions import IsSuperAdmin

from .filters import ActivityLogFilter
from .models import ActivityLog
from .serializers import (
    ActivityLogSerializer,
    CommissionSettingsSerializer,
    GeneralSettingsSerializer,
    PlatformPaymentMethodSerializer,
    PlatformPaymentMethodsSerializer,
    SuperNotificationSerializer,
)
from .services import (
    build_super_notifications,
    get_general_settings,
    get_global_commission_rate,
    get_payment_methods_config,
    log_activity,
    set_global_commission_rate,
    set_payment_methods_config,
    update_general_settings,
)


@extend_schema(tags=["super"])
class SuperSettingsView(GenericAPIView):
    """GET/PATCH /super/settings/ — parametres generaux de la plateforme."""

    permission_classes = [IsSuperAdmin]
    serializer_class = GeneralSettingsSerializer

    @extend_schema(
        summary="Consulter les parametres generaux de la plateforme",
        responses={status.HTTP_200_OK: GeneralSettingsSerializer},
    )
    def get(self, request, *args, **kwargs):
        return Response(GeneralSettingsSerializer(get_general_settings()).data)

    @extend_schema(
        summary="Mettre a jour les parametres generaux",
        request=GeneralSettingsSerializer,
        responses={
            status.HTTP_200_OK: GeneralSettingsSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(description="Champ invalide."),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"platform_name": "TransBooking BF", "maintenance_mode": False},
                request_only=True,
            ),
        ],
    )
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        result = update_general_settings(serializer.validated_data)
        log_activity(
            request.user,
            action="settings.update",
            entity_type="global_setting",
            details={key: str(value) for key, value in serializer.validated_data.items()},
        )
        return Response(GeneralSettingsSerializer(result).data)


@extend_schema(tags=["super"])
class SuperCommissionSettingsView(GenericAPIView):
    """GET/PATCH /super/settings/commissions/ — taux global et surcharges."""

    permission_classes = [IsSuperAdmin]
    serializer_class = CommissionSettingsSerializer

    def _payload(self) -> dict:
        overrides = [
            {
                "company_id": company.id,
                "company_name": company.name,
                "commission_rate": company.commission_rate,
            }
            # Seules les compagnies avec un taux propre constituent une surcharge.
            for company in Company.objects.exclude(commission_rate=None).only(
                "id", "name", "commission_rate"
            )
        ]
        return {
            "global_rate": get_global_commission_rate(),
            "company_overrides": overrides,
        }

    @extend_schema(
        summary="Consulter le taux de commission global et les surcharges",
        responses={status.HTTP_200_OK: CommissionSettingsSerializer},
    )
    def get(self, request, *args, **kwargs):
        return Response(CommissionSettingsSerializer(self._payload()).data)

    @extend_schema(
        summary="Mettre a jour le taux global et/ou les surcharges par compagnie",
        request=CommissionSettingsSerializer,
        responses={
            status.HTTP_200_OK: CommissionSettingsSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Taux hors bornes 0-100 ou compagnie inconnue.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={
                    "global_rate": "12.50",
                    "company_overrides": [{"company_id": 3, "commission_rate": "8.00"}],
                },
                request_only=True,
            ),
        ],
    )
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        if "global_rate" in data:
            set_global_commission_rate(data["global_rate"])
            log_activity(
                request.user,
                action="settings.commission_rate",
                entity_type="global_setting",
                details={"global_rate": str(data["global_rate"])},
            )

        for override in data.get("company_overrides", []):
            # commission_rate=None => la compagnie repasse au taux global.
            Company.objects.filter(pk=override["company_id"]).update(
                commission_rate=override["commission_rate"]
            )
            log_activity(
                request.user,
                action="settings.company_commission",
                entity_type="company",
                entity_id=override["company_id"],
                details={"commission_rate": str(override["commission_rate"])},
            )

        return Response(CommissionSettingsSerializer(self._payload()).data)


@extend_schema(tags=["super"])
class SuperPaymentMethodsView(GenericAPIView):
    """GET/PATCH /super/settings/payment-methods/ — moyens de paiement plateforme."""

    permission_classes = [IsSuperAdmin]
    serializer_class = PlatformPaymentMethodsSerializer

    @extend_schema(
        summary="Consulter les moyens de paiement actives au niveau plateforme",
        responses={status.HTTP_200_OK: PlatformPaymentMethodSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return Response(
            PlatformPaymentMethodSerializer(get_payment_methods_config(), many=True).data
        )

    @extend_schema(
        summary="Activer / desactiver un moyen de paiement",
        request=PlatformPaymentMethodsSerializer,
        responses={
            status.HTTP_200_OK: PlatformPaymentMethodSerializer(many=True),
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Moyen de paiement inconnu.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"payment_methods": [{"method": "card", "is_active": False}]},
                request_only=True,
            ),
        ],
    )
    def patch(self, request, *args, **kwargs):
        # Accepte l'enveloppe {"payment_methods": [...]} ou la liste brute,
        # comme /company/settings/payment-methods/.
        payload = request.data.get("payment_methods", request.data)
        serializer = PlatformPaymentMethodSerializer(data=payload, many=True)
        serializer.is_valid(raise_exception=True)
        result = set_payment_methods_config(serializer.validated_data)
        log_activity(
            request.user,
            action="settings.payment_methods",
            entity_type="global_setting",
            details={entry["method"]: entry["is_active"] for entry in result},
        )
        return Response(PlatformPaymentMethodSerializer(result, many=True).data)


# --------------------------------------------------------------------------- #
# Audit & supervision (cf. PROMPT_SUP A6)
# --------------------------------------------------------------------------- #
@extend_schema(tags=["super"])
class SuperActivityLogListView(ListAPIView):
    """GET /super/activity-logs/ — journal des actions sensibles, pagine."""

    permission_classes = [IsSuperAdmin]
    serializer_class = ActivityLogSerializer
    filterset_class = ActivityLogFilter
    queryset = ActivityLog.objects.select_related("user__role")

    @extend_schema(
        summary="Consulter le journal d'audit de la plateforme",
        parameters=[
            OpenApiParameter("user", int, description="ID de l'auteur de l'action."),
            OpenApiParameter(
                "action",
                str,
                description="Filtre partiel sur le code d'action (ex: `company.`).",
            ),
            OpenApiParameter(
                "entity_type",
                str,
                description="Type d'objet impacte (`company`, `subscription`, `user`...).",
            ),
            OpenApiParameter("entity_id", int, description="ID de l'objet impacte."),
            OpenApiParameter("date_from", str, description="Date de debut (YYYY-MM-DD)."),
            OpenApiParameter("date_to", str, description="Date de fin (YYYY-MM-DD)."),
        ],
        responses={status.HTTP_200_OK: ActivityLogSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        return super().get(request, *args, **kwargs)


@extend_schema(tags=["super"])
class SuperNotificationListView(GenericAPIView):
    """GET /super/notifications/ — fil de supervision de la plateforme.

    Alertes calculees a la volee (aucun stockage) : nouvelles inscriptions,
    abonnements expires, signalements urgents et incidents techniques.
    """

    permission_classes = [IsSuperAdmin]
    serializer_class = SuperNotificationSerializer

    @extend_schema(
        summary="Consulter les alertes de supervision du super admin",
        parameters=[
            OpenApiParameter(
                "type",
                str,
                enum=[
                    "new_registration",
                    "subscription_expired",
                    "urgent_report",
                    "technical_incident",
                ],
                description="Filtre optionnel sur la categorie d'alerte.",
            ),
            OpenApiParameter(
                "severity",
                str,
                enum=["info", "warning", "critical"],
                description="Filtre optionnel sur la criticite.",
            ),
        ],
        responses={status.HTTP_200_OK: SuperNotificationSerializer(many=True)},
    )
    def get(self, request, *args, **kwargs):
        items = build_super_notifications()

        notification_type = request.query_params.get("type")
        if notification_type:
            items = [item for item in items if item["type"] == notification_type]
        severity = request.query_params.get("severity")
        if severity:
            items = [item for item in items if item["severity"] == severity]

        page = self.paginate_queryset(items)
        serializer = self.get_serializer(page, many=True)
        return self.get_paginated_response(serializer.data)
