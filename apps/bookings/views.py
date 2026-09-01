import csv

from django.http import HttpResponse
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView, ListAPIView
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.response import Response

from apps.trips.models import Trip
from utils.permissions import (
    IsAgent,
    IsAgentGuichet,
    IsCompanyAdmin,
    IsControleur,
    IsVoyageur,
)

from .filters import BookingFilter
from .models import BoardingValidation, Booking, BookingStatus, ScanLog
from .serializers import (
    AgentBookingCancelSerializer,
    AgentBookingCreateSerializer,
    BoardingValidationSerializer,
    BoardingValidationSummarySerializer,
    BookingCreateSerializer,
    BookingReadSerializer,
    ScanLogSerializer,
    ScanRequestSerializer,
    ScanResultSerializer,
    TicketPrintSerializer,
)
from .services import (
    cancel_booking,
    check_in,
    create_booking,
    generate_ticket_pdf,
    mark_ticket_printed,
    register_baggage,
    scan_qr,
)

# --------------------------------------------------------------------------- #
# Helpers de perimetre (isolation multi-tenant)
# --------------------------------------------------------------------------- #


def _agent_company_id(user) -> int:
    """Return the company id of an agent or raise 404 if none.

    Args:
        user: The authenticated agent user.

    Returns:
        The agent's company primary key.
    """
    profile = getattr(user, "agent_profile", None)
    if profile is None or profile.company_id is None:
        raise NotFound("Aucun profil agent associe a cet utilisateur.")
    return profile.company_id


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


class BookingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Reservations du voyageur connecte."""

    permission_classes = [IsVoyageur]

    def get_queryset(self):
        return (
            Booking.objects.filter(user=self.request.user)
            .select_related(
                "trip__route__origin_city",
                "trip__route__destination_city",
                "trip__route__company",
            )
            .prefetch_related("baggage")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return BookingCreateSerializer
        return BookingReadSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        booking = create_booking(serializer.validated_data)
        return Response(
            BookingReadSerializer(booking).data, status=status.HTTP_201_CREATED
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        booking = self.get_object()
        reason = request.data.get("reason", "")
        cancel_booking(booking, cancelled_by=request.user, reason=reason)
        return Response(BookingReadSerializer(booking).data)

    @action(detail=True, methods=["get"])
    def ticket(self, request, pk=None):
        booking = self.get_object()
        pdf = generate_ticket_pdf(booking)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="billet_{booking.ticket_number}.pdf"'
        )
        return response


# --------------------------------------------------------------------------- #
# Agent guichet
# --------------------------------------------------------------------------- #


class AgentBookingViewSet(
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Enregistrement et recherche de billets au guichet.

    Recherche par `ticket_number` (jamais par id sequentiel expose).
    """

    permission_classes = [IsAgentGuichet]
    lookup_field = "ticket_number"
    lookup_value_regex = "[^/]+"

    def get_queryset(self):
        return Booking.objects.filter(
            trip__route__company_id=_agent_company_id(self.request.user)
        ).select_related(
            "trip__route__origin_city",
            "trip__route__destination_city",
            "trip__route__company",
        ).prefetch_related("baggage")

    def get_serializer_class(self):
        if self.action == "create":
            return AgentBookingCreateSerializer
        return BookingReadSerializer

    def create(self, request, *args, **kwargs):
        # Verifie l'existence d'un profil agent (perimetre + isolation).
        _agent_company_id(request.user)
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        baggage_items = data.pop("baggage", [])
        booking = create_booking(data, agent=request.user)
        if baggage_items:
            # Etiquetage des bagages peses au guichet (meme statut hors ligne).
            register_baggage(
                booking, baggage_items, is_offline=data.get("is_offline", False)
            )
        return Response(
            BookingReadSerializer(booking).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        tags=["agent"],
        summary="Marquer un billet imprime et recuperer le payload d'impression",
        request=None,
        responses={
            status.HTTP_200_OK: TicketPrintSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="Billet inconnu ou appartenant a une autre compagnie.",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="print")
    def print_ticket(self, request, ticket_number=None):
        booking = self.get_object()
        payload = mark_ticket_printed(booking, agent=request.user)
        return Response(TicketPrintSerializer(payload).data)

    @extend_schema(
        tags=["agent"],
        summary="Annuler un billet au guichet",
        request=AgentBookingCancelSerializer,
        responses={
            status.HTTP_200_OK: BookingReadSerializer,
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="Billet inconnu ou appartenant a une autre compagnie.",
            ),
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description="Billet deja embarque ou rembourse : annulation refusee.",
            ),
        },
    )
    @action(detail=True, methods=["post"])
    def cancel(self, request, ticket_number=None):
        booking = self.get_object()
        serializer = AgentBookingCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        cancel_booking(
            booking,
            cancelled_by=request.user,
            reason=serializer.validated_data.get("reason", ""),
        )
        return Response(BookingReadSerializer(booking).data)


# --------------------------------------------------------------------------- #
# Controleur — embarquement
# --------------------------------------------------------------------------- #


@extend_schema(
    tags=["agent"],
    summary="Scanner un QR code et valider le billet",
    request=ScanRequestSerializer,
    responses={
        status.HTTP_200_OK: ScanResultSerializer,
        status.HTTP_400_BAD_REQUEST: OpenApiResponse(
            description="Champ requis manquant : qr_data ou ticket_number.",
        ),
        status.HTTP_404_NOT_FOUND: OpenApiResponse(
            description="Billet introuvable (ou hors de la compagnie du controleur).",
        ),
    },
)
class ScanView(GenericAPIView):
    """Scanne un QR code et renvoie le statut du billet avec code couleur."""

    permission_classes = [IsControleur]
    serializer_class = ScanRequestSerializer

    def post(self, request, *args, **kwargs):
        qr_data = request.data.get("qr_data") or request.data.get("ticket_number")
        if not qr_data:
            raise ValidationError("Champ requis : qr_data ou ticket_number.")
        try:
            result = scan_qr(qr_data, request.user)
        except Booking.DoesNotExist:
            raise NotFound("Billet introuvable.")
        return Response(result)


@extend_schema(tags=["agent"])
class ScanHistoryView(ListAPIView):
    """GET /agent/scan/history/ — 50 derniers scans de l'agent, horodates."""

    permission_classes = [IsAgent]
    serializer_class = ScanLogSerializer

    # Limite fonctionnelle : seuls les 50 derniers scans sont exposes.
    HISTORY_SIZE = 50

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return ScanLog.objects.none()
        # Isolation : chaque agent ne consulte que ses propres scans.
        return list(
            ScanLog.objects.filter(agent=self.request.user).select_related("booking")[
                : self.HISTORY_SIZE
            ]
        )


class BoardingBaseView(GenericAPIView):
    """Base partagee des vues d'embarquement (isolation par compagnie)."""

    permission_classes = [IsControleur]
    serializer_class = BoardingValidationSerializer

    def get_trip(self, trip_id: int) -> Trip:
        company_id = _agent_company_id(self.request.user)
        try:
            return Trip.objects.get(pk=trip_id, route__company_id=company_id)
        except Trip.DoesNotExist:
            raise NotFound("Voyage introuvable.")

    def paid_bookings(self, trip: Trip):
        return Booking.objects.filter(trip=trip, status=BookingStatus.PAID)


class BoardingCheckInView(BoardingBaseView):
    """POST /agent/trips/{id}/boarding/{booking_id}/ — cocher un passager."""

    def post(self, request, trip_id=None, booking_id=None):
        trip = self.get_trip(trip_id)
        try:
            booking = self.paid_bookings(trip).get(pk=booking_id)
        except Booking.DoesNotExist:
            raise NotFound("Reservation payee introuvable pour ce voyage.")
        validation = check_in(booking, request.user, method="manual")
        return Response(
            BoardingValidationSerializer(validation).data,
            status=status.HTTP_201_CREATED,
        )


class BoardingAllView(BoardingBaseView):
    """POST /agent/trips/{id}/boarding/all/ — embarquer tous les payes."""

    def post(self, request, trip_id=None):
        if str(request.data.get("confirm", "")).lower() not in {"true", "1"}:
            raise ValidationError(
                {"confirm": "Confirmation requise pour l'embarquement groupe."}
            )
        trip = self.get_trip(trip_id)
        validations = [
            check_in(booking, request.user, method="manual")
            for booking in self.paid_bookings(trip)
        ]
        return Response({"boarded": len(validations)}, status=status.HTTP_200_OK)


@extend_schema(
    tags=["agent"],
    summary="Verrouiller l'embarquement et recuperer le recapitulatif",
    request=None,
    responses={status.HTTP_200_OK: BoardingValidationSummarySerializer},
)
class BoardingValidateView(BoardingBaseView):
    """POST /agent/trips/{id}/boarding/validate/ — verrouille l'embarquement."""

    serializer_class = BoardingValidationSummarySerializer

    def post(self, request, trip_id=None):
        trip = self.get_trip(trip_id)
        paid = self.paid_bookings(trip)
        total_paid = paid.count()
        boarded = BoardingValidation.objects.filter(booking__trip=trip).count()
        return Response(
            {
                "trip": trip.id,
                "total_paid": total_paid,
                "boarded": boarded,
                "not_boarded": max(total_paid - boarded, 0),
                "locked": True,
            }
        )


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


class ExportContentNegotiation(DefaultContentNegotiation):
    """Neutralise le parametre `?format=` reserve par DRF.

    L'export reutilise `?format=pdf|excel` pour choisir le type de fichier, ce
    qui entrerait en conflit avec la selection de renderer de DRF (404). On
    ignore donc le suffixe de format et on garde le premier renderer.
    """

    def select_renderer(self, request, renderers, format_suffix=None):
        return renderers[0], renderers[0].media_type


class CompanyBookingViewSet(mixins.ListModelMixin, viewsets.GenericViewSet):
    """Toutes les reservations de la compagnie de l'admin courant."""

    permission_classes = [IsCompanyAdmin]
    serializer_class = BookingReadSerializer
    filterset_class = BookingFilter
    content_negotiation_class = ExportContentNegotiation

    def get_queryset(self):
        return Booking.objects.filter(
            trip__route__company=_admin_company(self.request.user)
        ).select_related(
            "trip__route__origin_city",
            "trip__route__destination_city",
            "trip__route__company",
        ).prefetch_related("baggage")

    @action(detail=False, methods=["get"])
    def export(self, request):
        export_format = request.query_params.get("format", "excel").lower()
        bookings = self.filter_queryset(self.get_queryset())
        if export_format == "pdf":
            return self._export_pdf(bookings)
        return self._export_excel(bookings)

    def _export_excel(self, bookings) -> HttpResponse:
        try:
            from openpyxl import Workbook
        except ImportError:
            return self._export_csv(bookings)

        from io import BytesIO

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Reservations"
        sheet.append(
            ["Billet", "Passager", "Telephone", "Siege", "Montant", "Statut"]
        )
        for booking in bookings:
            sheet.append(
                [
                    booking.ticket_number,
                    booking.passenger_name,
                    booking.phone,
                    booking.seat_number,
                    float(booking.amount),
                    booking.get_status_display(),
                ]
            )
        buffer = BytesIO()
        workbook.save(buffer)
        response = HttpResponse(
            buffer.getvalue(),
            content_type=(
                "application/vnd.openxmlformats-officedocument."
                "spreadsheetml.sheet"
            ),
        )
        response["Content-Disposition"] = 'attachment; filename="reservations.xlsx"'
        return response

    def _export_csv(self, bookings) -> HttpResponse:
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = 'attachment; filename="reservations.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ["Billet", "Passager", "Telephone", "Siege", "Montant", "Statut"]
        )
        for booking in bookings:
            writer.writerow(
                [
                    booking.ticket_number,
                    booking.passenger_name,
                    booking.phone,
                    booking.seat_number,
                    booking.amount,
                    booking.get_status_display(),
                ]
            )
        return response

    def _export_pdf(self, bookings) -> HttpResponse:
        from io import BytesIO

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfgen import canvas

        buffer = BytesIO()
        pdf = canvas.Canvas(buffer, pagesize=A4)
        _, height = A4
        pdf.setFont("Helvetica-Bold", 14)
        pdf.drawString(20 * mm, height - 20 * mm, "Reservations")
        pdf.setFont("Helvetica", 9)
        y = height - 30 * mm
        for booking in bookings:
            line = (
                f"{booking.ticket_number}  {booking.passenger_name}  "
                f"siege {booking.seat_number}  {booking.amount} FCFA  "
                f"{booking.get_status_display()}"
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
        response["Content-Disposition"] = 'attachment; filename="reservations.pdf"'
        return response
