from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.reviews.services import company_rating_subquery
from utils.permissions import IsCompanyAdmin, IsSuperAdmin

from .filters import CompanyFilter
from .models import (
    OPEN_REQUEST_STATUSES,
    Company,
    CompanyNotificationSettings,
    CompanyStatus,
    PaymentMethodChoice,
)
from .serializers import (
    CompanyCreateSerializer,
    CompanyDetailSerializer,
    CompanyInfoRequestSerializer,
    CompanyNotificationSettingsSerializer,
    CompanyPaymentMethodSerializer,
    CompanyPublicDetailSerializer,
    CompanyPublicSerializer,
    CompanyRegistrationRequestSerializer,
    CompanyRequestStatusSerializer,
    CompanySettingsSerializer,
)
from .services import (
    activate_company,
    approve_company,
    reject_company,
    request_company_info,
    suspend_company,
)


def _to_drf_validation(exc: DjangoValidationError):
    """Convertit une ValidationError Django (levee par services.py) en erreur DRF."""
    from rest_framework.exceptions import ValidationError as DRFValidationError

    detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
    return DRFValidationError(detail)


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #
class SuperCompanyViewSet(viewsets.ModelViewSet):
    """CRUD complet des compagnies + activation/suspension (super admin)."""

    queryset = Company.objects.all()
    permission_classes = [IsSuperAdmin]
    filterset_class = CompanyFilter

    def get_serializer_class(self):
        if self.action == "create":
            return CompanyCreateSerializer
        return CompanyDetailSerializer

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        company = self.get_object()
        try:
            activate_company(company, actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyDetailSerializer(company).data)

    @action(detail=True, methods=["post"])
    def suspend(self, request, pk=None):
        company = self.get_object()
        try:
            suspend_company(company, request.data.get("reason", ""), actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyDetailSerializer(company).data)


class CompanyRequestViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Demandes de creation de compagnie en cours d'instruction (super admin)."""

    permission_classes = [IsSuperAdmin]

    def get_queryset(self):
        # Une demande reste dans la file tant qu'elle n'est ni approuvee ni rejetee :
        # `info_requested` est donc inclus (le super admin doit pouvoir y revenir).
        return Company.objects.filter(status__in=OPEN_REQUEST_STATUSES)

    def get_serializer_class(self):
        if self.action == "request_info":
            return CompanyInfoRequestSerializer
        return CompanyDetailSerializer

    @extend_schema(
        tags=["super"],
        summary="Demander des informations complementaires a une compagnie",
        request=CompanyInfoRequestSerializer,
        responses={
            status.HTTP_200_OK: CompanyDetailSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Message vide ou demande deja approuvee/rejetee.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"message": "Merci de fournir le RCCM et l'agrement de transport."},
                request_only=True,
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="request-info")
    def request_info(self, request, pk=None):
        company = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            request_company_info(
                company, serializer.validated_data["message"], actor=request.user
            )
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyDetailSerializer(company).data)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        company = self.get_object()
        try:
            approve_company(company, actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyDetailSerializer(company).data)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        company = self.get_object()
        try:
            reject_company(company, request.data.get("reason", ""), actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyDetailSerializer(company).data)


# --------------------------------------------------------------------------- #
# Public
# --------------------------------------------------------------------------- #
@method_decorator(
    # Endpoint public non authentifie : 10 demandes/heure par IP (cf. security.md §4).
    ratelimit(key="ip", rate="10/h", method="POST", block=True),
    name="post",
)
class CompanyRegistrationRequestView(GenericAPIView):
    """Demande publique d'inscription d'une compagnie (statut ``pending``)."""

    serializer_class = CompanyRegistrationRequestSerializer
    permission_classes = [AllowAny]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    @extend_schema(
        tags=["public"],
        summary="Deposer une demande de creation de compte compagnie",
        request=CompanyRegistrationRequestSerializer,
        responses={
            status.HTTP_201_CREATED: CompanyRequestStatusSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Champs manquants, telephone invalide ou nom deja utilise.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={
                    "company_name": "Transport Sahel",
                    "manager_name": "Awa Ouedraogo",
                    "phone": "+22670000000",
                    "email": "contact@sahel.bf",
                    "city": "Ouagadougou",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Demande enregistree",
                value={
                    "id": 12,
                    "company_name": "Transport Sahel",
                    "manager_name": "Awa Ouedraogo",
                    "phone": "+22670000000",
                    "email": "contact@sahel.bf",
                    "city": "Ouagadougou",
                    "status": "pending",
                    "created_at": "2026-07-21T10:00:00Z",
                },
                response_only=True,
                status_codes=["201"],
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company = serializer.save()
        return Response(
            CompanyRequestStatusSerializer(company).data,
            status=status.HTTP_201_CREATED,
        )


class PublicCompanyViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Compagnies actives, visibles sans authentification."""

    permission_classes = [AllowAny]

    def get_queryset(self):
        # Note moyenne (avis publics non signales) annotee pour la liste et le detail.
        return Company.objects.filter(status=CompanyStatus.ACTIVE).annotate(
            avg_rating=company_rating_subquery("pk")
        )

    def get_serializer_class(self):
        if self.action == "retrieve":
            return CompanyPublicDetailSerializer
        return CompanyPublicSerializer

    @method_decorator(cache_page(60 * 60))
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)


# --------------------------------------------------------------------------- #
# Company admin — isolation stricte par compagnie de l'utilisateur courant
# --------------------------------------------------------------------------- #
class _CompanyAdminMixin:
    permission_classes = [IsCompanyAdmin]

    def get_company(self) -> Company:
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company


class CompanySettingsView(_CompanyAdminMixin, GenericAPIView):
    """GET/PATCH des parametres de la compagnie du company admin courant."""

    serializer_class = CompanySettingsSerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_company())
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        company = self.get_company()
        serializer = self.get_serializer(company, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


class CompanyPaymentMethodsView(_CompanyAdminMixin, GenericAPIView):
    """GET/PATCH des moyens de paiement de la compagnie."""

    serializer_class = CompanyPaymentMethodSerializer

    def get(self, request, *args, **kwargs):
        company = self.get_company()
        serializer = self.get_serializer(company.payment_methods.all(), many=True)
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        company = self.get_company()
        payload = request.data.get("payment_methods", request.data)
        serializer = self.get_serializer(data=payload, many=True)
        serializer.is_valid(raise_exception=True)

        valid_methods = set(PaymentMethodChoice.values)
        for item in serializer.validated_data:
            if item["method"] not in valid_methods:
                continue
            company.payment_methods.update_or_create(
                method=item["method"],
                defaults={"is_active": item.get("is_active", True)},
            )

        result = self.get_serializer(company.payment_methods.all(), many=True)
        return Response(result.data, status=status.HTTP_200_OK)


class CompanyNotificationsView(_CompanyAdminMixin, GenericAPIView):
    """GET/PATCH des parametres de notifications SMS de la compagnie."""

    serializer_class = CompanyNotificationSettingsSerializer

    def get_settings(self, company: Company) -> CompanyNotificationSettings:
        settings_obj, _ = CompanyNotificationSettings.objects.get_or_create(company=company)
        return settings_obj

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_settings(self.get_company()))
        return Response(serializer.data)

    def patch(self, request, *args, **kwargs):
        settings_obj = self.get_settings(self.get_company())
        serializer = self.get_serializer(settings_obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)
