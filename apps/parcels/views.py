import csv

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.generics import GenericAPIView
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from utils.permissions import IsAgentGuichet, IsCompanyAdmin

from .filters import ParcelFilter
from .models import Parcel, ParcelStatus
from .serializers import (
    AgentParcelCreateSerializer,
    NotifySerializer,
    ParcelReadSerializer,
    ParcelStatusSerializer,
    ParcelTrackSerializer,
    ParcelUpdateSerializer,
)
from .services import notify_recipient, register_parcel, update_status

# --------------------------------------------------------------------------- #
# Helpers de perimetre (isolation multi-tenant)
# --------------------------------------------------------------------------- #


def _agent_profile(user):
    """Return the agent profile of an agent or raise 404 if none.

    Args:
        user: The authenticated agent user.

    Returns:
        The agent profile (carries company and station).
    """
    profile = getattr(user, "agent_profile", None)
    if profile is None or profile.company_id is None:
        raise NotFound("Aucun profil agent associe a cet utilisateur.")
    return profile


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
# Public — suivi
# --------------------------------------------------------------------------- #


class ParcelTrackView(GenericAPIView):
    """GET /api/v1/parcels/track/{tracking_number}/ — suivi public d'un colis.

    Aucune authentification. Renvoie le statut courant et l'historique, sans
    exposer les donnees sensibles (telephone destinataire masque).
    """

    permission_classes = [AllowAny]
    serializer_class = ParcelTrackSerializer
    lookup_field = "tracking_number"

    def get(self, request, tracking_number=None):
        try:
            parcel = (
                Parcel.objects.select_related("origin_city", "destination_city", "trip")
                .prefetch_related("notifications")
                .get(tracking_number=tracking_number)
            )
        except Parcel.DoesNotExist:
            raise NotFound("Colis introuvable.")
        return Response(ParcelTrackSerializer(parcel).data)


# --------------------------------------------------------------------------- #
# Agent guichet
# --------------------------------------------------------------------------- #


class AgentParcelViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Enregistrement et notification de colis au guichet."""

    permission_classes = [IsAgentGuichet]

    def get_queryset(self):
        profile = _agent_profile(self.request.user)
        return Parcel.objects.filter(company_id=profile.company_id).prefetch_related(
            "notifications"
        )

    def get_serializer_class(self):
        if self.action == "create":
            return AgentParcelCreateSerializer
        return ParcelReadSerializer

    @extend_schema(
        request=AgentParcelCreateSerializer,
        responses={status.HTTP_201_CREATED: ParcelReadSerializer},
    )
    def create(self, request, *args, **kwargs):
        # La creation renvoie le serialiseur de lecture (id, tarif, tracking_number,
        # qr_code, statut) : il n'existe pas de recherche par tracking_number pour
        # rattraper la reponse apres coup.
        profile = _agent_profile(request.user)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        # La compagnie et la gare de depart proviennent du profil agent.
        data["company"] = profile.company
        data["origin_station"] = profile.station
        parcel = register_parcel(data, agent=request.user)
        return Response(
            ParcelReadSerializer(parcel).data, status=status.HTTP_201_CREATED
        )

    @action(detail=False, methods=["get"])
    def arrivals(self, request):
        """Colis arrives a la gare de l'agent, en attente de notification."""
        profile = _agent_profile(request.user)
        queryset = self.get_queryset().filter(status=ParcelStatus.ARRIVED)
        if profile.station_id is not None:
            queryset = queryset.filter(destination_station_id=profile.station_id)
        page = self.paginate_queryset(queryset)
        serializer = ParcelReadSerializer(page or queryset, many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def notify(self, request, pk=None):
        """Envoie un SMS au destinataire ou enregistre un appel manuel."""
        parcel = self.get_object()
        params = NotifySerializer(data=request.data)
        params.is_valid(raise_exception=True)
        notify_recipient(
            parcel, agent=request.user, method=params.validated_data["method"]
        )
        parcel.refresh_from_db()
        return Response(ParcelReadSerializer(parcel).data)


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


class ExportContentNegotiation(DefaultContentNegotiation):
    """Neutralise le parametre `?format=` reserve par DRF pour l'export.

    L'export reutilise `?format=pdf|excel` pour choisir le type de fichier, ce
    qui entrerait en conflit avec la selection de renderer de DRF (404).
    """

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class CompanyParcelViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """Tous les colis de la compagnie de l'admin courant."""

    permission_classes = [IsCompanyAdmin]
    filterset_class = ParcelFilter
    content_negotiation_class = ExportContentNegotiation

    def get_queryset(self):
        return Parcel.objects.filter(
            company=_admin_company(self.request.user)
        ).prefetch_related("notifications")

    def get_serializer_class(self):
        if self.action in {"update", "partial_update"}:
            return ParcelUpdateSerializer
        return ParcelReadSerializer

    @action(detail=True, methods=["post"])
    def status(self, request, pk=None):
        """POST /company/parcels/{id}/status/ — changer le statut manuellement."""
        parcel = self.get_object()
        serializer = ParcelStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        update_status(parcel, serializer.validated_data["status"])
        return Response(ParcelReadSerializer(parcel).data)

    @action(detail=True, methods=["post"], url_path="notify-again")
    def notify_again(self, request, pk=None):
        """POST /company/parcels/{id}/notify-again/ — renvoyer le SMS d'arrivee."""
        parcel = self.get_object()
        notify_recipient(parcel, agent=request.user, method="sms", force=True)
        parcel.refresh_from_db()
        return Response(ParcelReadSerializer(parcel).data)

    @action(detail=False, methods=["get"])
    def export(self, request):
        """GET /company/parcels/export/?format=pdf|excel — export de la liste."""
        export_format = request.query_params.get("format", "excel").lower()
        parcels = self.filter_queryset(self.get_queryset())
        if export_format == "pdf":
            return self._export_pdf(parcels)
        return self._export_excel(parcels)

    _COLUMNS = ["Suivi", "Expediteur", "Destinataire", "Telephone", "Poids", "Tarif", "Statut"]

    def _row(self, parcel: Parcel) -> list:
        return [
            parcel.tracking_number,
            parcel.sender_name,
            parcel.recipient_name,
            parcel.recipient_phone,
            float(parcel.weight_kg),
            float(parcel.tariff),
            parcel.get_status_display(),
        ]

    def _export_excel(self, parcels) -> HttpResponse:
        try:
            from openpyxl import Workbook
        except ImportError:
            return self._export_csv(parcels)

        from io import BytesIO

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Colis"
        sheet.append(self._COLUMNS)
        for parcel in parcels:
            sheet.append(self._row(parcel))
        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = 'attachment; filename="colis.xlsx"'
        return response

    def _export_csv(self, parcels) -> HttpResponse:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="colis.csv"'
        writer = csv.writer(response)
        writer.writerow(self._COLUMNS)
        for parcel in parcels:
            writer.writerow(self._row(parcel))
        return response

    def _export_pdf(self, parcels) -> HttpResponse:
        from io import BytesIO

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        _, height = A4
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(20 * mm, height - 20 * mm, "Colis")
        pdf.setFont("Helvetica", 9)
        y = height - 30 * mm
        for parcel in parcels:
            line = (
                f"{parcel.tracking_number}  {parcel.sender_name} -> "
                f"{parcel.recipient_name}  {parcel.weight_kg} kg  "
                f"{parcel.tariff} FCFA  {parcel.get_status_display()}"
            )
            pdf.drawString(20 * mm, y, line)
            y -= 7 * mm
            if y < 20 * mm:
                pdf.showPage()
                pdf.setFont("Helvetica", 9)
                y = height - 20 * mm
        pdf.showPage()
        pdf.save()
        response = HttpResponse(buffer.getvalue(), content_type="application/pdf")
        response["Content-Disposition"] = 'attachment; filename="colis.pdf"'
        return response
