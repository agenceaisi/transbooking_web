from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from utils.permissions import IsCompanyAdmin, IsSuperAdmin, IsVoyageur

from .filters import ClaimFilter
from .models import UNRESOLVED_STATUSES, Claim
from .serializers import (
    ClaimAttachmentUploadSerializer,
    ClaimCreateSerializer,
    ClaimReadSerializer,
    ClaimRespondSerializer,
)
from .services import (
    add_claim_attachment,
    annotated_claims,
    claim_stats,
    close_claim,
    escalate_claim,
    respond_to_claim,
    unresolved_first,
)


def _admin_company(user):
    """Return the company administered by a company admin or raise 404.

    Args:
        user: The authenticated company admin user.

    Returns:
        The administered company.
    """
    company = getattr(user, "administered_company", None)
    if company is None:
        raise NotFound("Aucune compagnie associee a cet utilisateur.")
    return company


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #


class ClaimViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Reclamations du voyageur courant : depot et consultation."""

    permission_classes = [IsVoyageur]

    def get_queryset(self):
        return annotated_claims(
            Claim.objects.filter(user=self.request.user)
            .select_related("company", "booking")
            .prefetch_related("attachments")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return ClaimCreateSerializer
        return ClaimReadSerializer

    @extend_schema(
        request=ClaimCreateSerializer,
        responses={status.HTTP_201_CREATED: ClaimReadSerializer},
    )
    def create(self, request, *args, **kwargs):
        # La creation renvoie le serialiseur de lecture (id + reference + statut)
        # pour que l'ecran de confirmation affiche le numero de suivi.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # La piece jointe facultative est detachee : elle devient une
        # ClaimAttachment, elle n'est pas un champ du modele Claim.
        attachment = serializer.validated_data.pop("attachment", None)
        claim = serializer.save(user=request.user)
        if attachment is not None:
            add_claim_attachment(claim, attachment)
        return Response(
            ClaimReadSerializer(claim, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )

    @extend_schema(
        request=ClaimAttachmentUploadSerializer,
        responses={status.HTTP_201_CREATED: ClaimReadSerializer},
    )
    @action(detail=True, methods=["post"], url_path="attachment")
    def add_attachment(self, request, pk=None):
        """POST /claims/{id}/attachment/ — joindre un fichier (PDF/photo, 10 Mo)."""
        claim = self.get_object()
        serializer = ClaimAttachmentUploadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        add_claim_attachment(claim, serializer.validated_data["file"])
        # Recharge pour renvoyer la reclamation avec la nouvelle piece jointe.
        claim = self.get_queryset().get(pk=claim.pk)
        return Response(
            ClaimReadSerializer(claim, context=self.get_serializer_context()).data,
            status=status.HTTP_201_CREATED,
        )


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


class CompanyClaimViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Reclamations recues par la compagnie de l'admin courant."""

    permission_classes = [IsCompanyAdmin]
    filterset_class = ClaimFilter
    serializer_class = ClaimReadSerializer

    def get_queryset(self):
        queryset = annotated_claims(
            Claim.objects.filter(company=_admin_company(self.request.user))
            .select_related("company", "booking")
            .prefetch_related("attachments")
        )
        # Les reclamations non traitees apparaissent en premier.
        return unresolved_first(queryset)

    @action(detail=True, methods=["post"])
    def respond(self, request, pk=None):
        """POST /company/claims/{id}/respond/ — repondre et changer le statut."""
        claim = self.get_object()
        serializer = ClaimRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        respond_to_claim(
            claim,
            response=serializer.validated_data["response"],
            status=serializer.validated_data["status"],
            responder=request.user,
        )
        return Response(ClaimReadSerializer(claim).data)

    @action(detail=False, methods=["get"])
    def stats(self, request):
        """GET /company/claims/stats/ — taux de resolution et delai moyen."""
        company = _admin_company(request.user)
        return Response(claim_stats(Claim.objects.filter(company=company)))


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #


class SuperClaimViewSet(
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Supervision des reclamations toutes compagnies (super admin)."""

    permission_classes = [IsSuperAdmin]
    serializer_class = ClaimReadSerializer

    def get_queryset(self):
        return annotated_claims(
            Claim.objects.select_related("company", "booking").prefetch_related(
                "attachments"
            )
        )

    @action(detail=False, methods=["get"])
    def unresolved(self, request):
        """GET /super/claims/unresolved/ — reclamations non traitees."""
        queryset = unresolved_first(
            self.get_queryset().filter(status__in=UNRESOLVED_STATUSES)
        )
        page = self.paginate_queryset(queryset)
        serializer = ClaimReadSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def escalate(self, request, pk=None):
        """POST /super/claims/{id}/escalate/ — relancer la compagnie."""
        claim = self.get_object()
        escalate_claim(claim)
        return Response(ClaimReadSerializer(claim).data)

    @action(detail=True, methods=["post"])
    def close(self, request, pk=None):
        """POST /super/claims/{id}/close/ — cloturer directement."""
        claim = self.get_object()
        close_claim(claim)
        return Response(ClaimReadSerializer(claim).data)
