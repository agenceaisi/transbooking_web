from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.response import Response

from utils.permissions import IsCompanyAdminBilling, IsSuperAdmin

from .models import Subscription, SubscriptionInvoice, SubscriptionPlan
from .serializers import (
    SubscriptionCreateSerializer,
    SubscriptionInvoiceSerializer,
    SubscriptionPlanSerializer,
    SubscriptionReadSerializer,
    SubscriptionUpdateSerializer,
)
from .services import (
    create_subscription,
    generate_invoice_pdf,
    get_current_subscription,
    invoice_reference,
    renew_subscription,
)


def _to_drf_validation(exc: DjangoValidationError):
    """Convertit une ValidationError Django (levee par services.py) en erreur DRF."""
    detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
    return ValidationError(detail)


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #
@extend_schema(tags=["super"])
class SuperSubscriptionPlanViewSet(viewsets.ModelViewSet):
    """CRUD des forfaits d'abonnement proposes aux compagnies (super admin)."""

    queryset = SubscriptionPlan.objects.all()
    serializer_class = SubscriptionPlanSerializer
    permission_classes = [IsSuperAdmin]
    filterset_fields = ["is_active", "duration_months"]

    def perform_destroy(self, instance: SubscriptionPlan) -> None:
        # Un forfait deja souscrit reste reference par l'historique : on le
        # desactive plutot que de casser les abonnements existants.
        if instance.subscriptions.exists():
            raise ValidationError(
                {
                    "detail": (
                        "Ce forfait est utilise par des abonnements existants : "
                        "desactivez-le (is_active=false) au lieu de le supprimer."
                    )
                }
            )
        instance.delete()


@extend_schema(tags=["super"])
class SuperSubscriptionViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Abonnements des compagnies : attribution, activation, renouvellement."""

    permission_classes = [IsSuperAdmin]
    filterset_fields = ["company", "plan", "status", "auto_renew"]

    def get_queryset(self):
        return Subscription.objects.select_related("company", "plan")

    def get_serializer_class(self):
        if self.action == "create":
            return SubscriptionCreateSerializer
        if self.action in {"update", "partial_update"}:
            return SubscriptionUpdateSerializer
        return SubscriptionReadSerializer

    @extend_schema(
        summary="Attribuer un forfait a une compagnie",
        request=SubscriptionCreateSerializer,
        responses={
            status.HTTP_201_CREATED: SubscriptionReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Compagnie deja abonnee, forfait inactif ou dates incoherentes.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"company": 3, "plan": 1, "auto_renew": True},
                request_only=True,
            ),
        ],
    )
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            subscription = create_subscription(
                serializer.validated_data, actor=request.user
            )
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(
            SubscriptionReadSerializer(subscription).data,
            status=status.HTTP_201_CREATED,
        )

    def update(self, request, *args, **kwargs):
        response = super().update(request, *args, **kwargs)
        instance = self.get_object()
        response.data = SubscriptionReadSerializer(instance).data
        return response

    @extend_schema(
        summary="Renouveler un abonnement (nouvelle periode + facture)",
        request=None,
        responses={status.HTTP_200_OK: SubscriptionReadSerializer},
    )
    @action(detail=True, methods=["post"])
    def renew(self, request, pk=None):
        subscription = self.get_object()
        renew_subscription(subscription, actor=request.user)
        return Response(SubscriptionReadSerializer(subscription).data)


# --------------------------------------------------------------------------- #
# Company admin — forfait courant et factures
# --------------------------------------------------------------------------- #
class _CompanyBillingMixin:
    """Perimetre facturation du company admin.

    Ces routes utilisent ``IsCompanyAdminBilling`` : une compagnie suspendue ou
    dont l'abonnement a expire doit pouvoir consulter son forfait et ses
    factures pour se remettre en regle (cf. PROMPT_SUP A3).
    """

    permission_classes = [IsCompanyAdminBilling]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company


@extend_schema(tags=["company"])
class CompanySubscriptionView(_CompanyBillingMixin, GenericAPIView):
    """GET /company/subscription/ — forfait courant, echeance et statut."""

    serializer_class = SubscriptionReadSerializer

    @extend_schema(
        summary="Consulter l'abonnement courant de sa compagnie",
        responses={
            status.HTTP_200_OK: SubscriptionReadSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="Aucune compagnie associee ou aucun abonnement en cours.",
            ),
        },
    )
    def get(self, request, *args, **kwargs):
        company = self.get_company()
        subscription = get_current_subscription(company)
        if subscription is None:
            # Pas d'abonnement valide : on renvoie le dernier connu pour que le
            # front affiche l'echeance depassee, sinon 404.
            subscription = (
                Subscription.objects.filter(company=company)
                .select_related("plan")
                .order_by("-end_date")
                .first()
            )
        if subscription is None:
            raise NotFound("Aucun abonnement pour cette compagnie.")
        return Response(self.get_serializer(subscription).data)


@extend_schema(tags=["company"])
class CompanySubscriptionInvoiceListView(_CompanyBillingMixin, ListAPIView):
    """GET /company/subscription/invoices/ — factures de la compagnie."""

    serializer_class = SubscriptionInvoiceSerializer

    def get_queryset(self):
        return SubscriptionInvoice.objects.filter(
            subscription__company=self.get_company()
        ).select_related("subscription__plan")


@extend_schema(tags=["company"])
class CompanySubscriptionInvoiceDownloadView(_CompanyBillingMixin, GenericAPIView):
    """GET /company/subscription/invoices/{id}/download/ — facture en PDF."""

    serializer_class = SubscriptionInvoiceSerializer

    @extend_schema(
        summary="Telecharger une facture d'abonnement (PDF)",
        responses={
            (status.HTTP_200_OK, "application/pdf"): OpenApiResponse(
                description="Fichier PDF de la facture.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="Facture inexistante ou appartenant a une autre compagnie.",
            ),
        },
    )
    def get(self, request, pk=None, *args, **kwargs):
        # Isolation multi-tenant : la facture doit appartenir a sa compagnie.
        try:
            invoice = SubscriptionInvoice.objects.select_related(
                "subscription__company", "subscription__plan"
            ).get(pk=pk, subscription__company=self.get_company())
        except SubscriptionInvoice.DoesNotExist:
            raise NotFound("Facture introuvable.")

        pdf = generate_invoice_pdf(invoice)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="{invoice_reference(invoice)}.pdf"'
        )
        return response
