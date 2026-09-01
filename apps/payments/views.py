from django.http import HttpResponse
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from utils.permissions import IsAgentGuichet

from .models import MOBILE_MONEY_METHODS, Payment
from .serializers import (
    AgentPaymentSerializer,
    PaymentInitiateSerializer,
    PaymentOtpVerifySerializer,
    PaymentReadSerializer,
    PaymentVerifySerializer,
)
from .services import (
    confirm_payment,
    generate_receipt_pdf,
    initiate_payment,
    resend_payment_otp,
    verify_payment_otp,
)


def _scope_payments(user):
    """Return the payments visible to ``user`` (multi-tenant isolation).

    Args:
        user: The authenticated user.

    Returns:
        A filtered ``Payment`` queryset.
    """
    queryset = Payment.objects.select_related(
        "booking__trip__route__origin_city",
        "booking__trip__route__destination_city",
        "booking__trip__route__company",
    )
    role = getattr(getattr(user, "role", None), "name", None)

    if role == "super_admin":
        return queryset
    if role == "company_admin":
        company = getattr(user, "administered_company", None)
        company_id = getattr(company, "id", None)
        return queryset.filter(booking__trip__route__company_id=company_id)
    if role in {"agent_guichet", "controleur"}:
        profile = getattr(user, "agent_profile", None)
        company_id = getattr(profile, "company_id", None)
        return queryset.filter(booking__trip__route__company_id=company_id)
    # Voyageur : uniquement les paiements de ses propres reservations.
    return queryset.filter(booking__user=user)


@extend_schema(tags=["payments"])
class PaymentViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Paiements accessibles a l'utilisateur courant (filtres par perimetre)."""

    permission_classes = [IsAuthenticated]
    serializer_class = PaymentReadSerializer

    def get_queryset(self):
        return _scope_payments(self.request.user)

    @extend_schema(
        summary="Lister mes paiements",
        description=(
            "Liste paginee des paiements visibles par l'utilisateur courant. "
            "Un voyageur ne voit que les paiements de ses propres reservations "
            "(reference de transaction et telephone masques). Tri par date "
            "decroissante."
        ),
        responses={status.HTTP_200_OK: PaymentReadSerializer(many=True)},
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    def get_serializer_class(self):
        if self.action == "create":
            return PaymentInitiateSerializer
        if self.action == "verify":
            return PaymentVerifySerializer
        if self.action in {"verify_otp", "resend_otp"}:
            return PaymentOtpVerifySerializer
        return PaymentReadSerializer

    @extend_schema(
        summary="Initier un paiement",
        description=(
            "Mobile Money : ouvre la transaction chez l'operateur, envoie un code "
            "de confirmation au payeur et renvoie le paiement au statut "
            "`otp_required`. Especes : le paiement reste `pending` jusqu'a "
            "l'encaissement au guichet. Carte : hors perimetre (400)."
        ),
        request=PaymentInitiateSerializer,
        responses={
            status.HTTP_201_CREATED: PaymentReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Champ manquant, moyen desactive ou hors perimetre.",
            ),
            status.HTTP_409_CONFLICT: OpenApiResponse(
                description="Reservation deja reglee.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete Mobile Money",
                value={
                    "booking_id": 42,
                    "method": "orange_money",
                    "phone": "+22670000001",
                },
                request_only=True,
            ),
            OpenApiExample(
                "Reponse",
                value={
                    "id": 7,
                    "ticket_number": "BF2026001234",
                    "amount": "5000.00",
                    "method": "orange_money",
                    "method_display": "Orange Money",
                    "status": "otp_required",
                    "status_display": "Code de confirmation attendu",
                    "transaction_ref": "",
                    "phone": "****0001",
                    "otp_expires_at": "2026-07-21T09:17:00Z",
                    "otp_attempts_remaining": 3,
                    "receipt_url": "",
                    "paid_at": None,
                    "created_at": "2026-07-21T09:12:00Z",
                },
                response_only=True,
            ),
        ],
    )
    def create(self, request, *args, **kwargs):
        serializer = PaymentInitiateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        payment = initiate_payment(
            booking=data["booking"],
            method=data["method"],
            phone=data.get("phone", ""),
        )
        return Response(
            PaymentReadSerializer(payment).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Confirmer un paiement especes (saisie manuelle)",
        description=(
            "Reserve aux paiements hors Mobile Money. Un paiement Mobile Money "
            "se confirme via `/verify-otp/`."
        ),
        request=PaymentVerifySerializer,
        responses={
            status.HTTP_200_OK: PaymentReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Reference manquante, ou paiement relevant du flux OTP.",
            ),
            status.HTTP_409_CONFLICT: OpenApiResponse(description="Deja confirme."),
        },
    )
    @action(detail=True, methods=["post"])
    def verify(self, request, pk=None):
        payment = self.get_object()
        if payment.method in MOBILE_MONEY_METHODS:
            raise ValidationError(
                {
                    "detail": (
                        "Un paiement Mobile Money se confirme avec le code recu : "
                        f"POST /api/v1/payments/{payment.pk}/verify-otp/."
                    )
                }
            )
        serializer = PaymentVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = confirm_payment(
            payment, transaction_ref=serializer.validated_data.get("transaction_ref", "")
        )
        return Response(PaymentReadSerializer(payment).data)

    @extend_schema(
        summary="Confirmer un paiement Mobile Money avec le code recu",
        description=(
            "Verifie le code a usage unique. En cas d'echec, le nombre de "
            "tentatives restantes est renvoye ; au-dela de `max_attempts` ou "
            "apres expiration, le paiement passe a `failed`."
        ),
        request=PaymentOtpVerifySerializer,
        responses={
            status.HTTP_200_OK: PaymentReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description=(
                    "Code incorrect (avec `attempts_remaining`), expire, "
                    "tentatives epuisees, ou refus de l'operateur."
                ),
            ),
            status.HTTP_409_CONFLICT: OpenApiResponse(description="Deja confirme."),
        },
        examples=[
            OpenApiExample("Requete", value={"otp": "123456"}, request_only=True),
            OpenApiExample(
                "Code incorrect",
                value={
                    "otp": ["Code incorrect. Il vous reste 2 tentative(s)."],
                    "attempts_remaining": 2,
                },
                response_only=True,
                status_codes=["400"],
            ),
        ],
    )
    @action(detail=True, methods=["post"], url_path="verify-otp")
    def verify_otp(self, request, pk=None):
        payment = self.get_object()
        serializer = PaymentOtpVerifySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        payment = verify_payment_otp(payment, serializer.validated_data["otp"])
        return Response(PaymentReadSerializer(payment).data)

    @extend_schema(
        summary="Renvoyer un code de confirmation",
        description=(
            "Emet un nouveau code. Limite a un envoi toutes les "
            "`OTP_RESEND_INTERVAL_SECONDS` secondes (30 s par defaut)."
        ),
        request=None,
        responses={
            status.HTTP_200_OK: PaymentReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Le paiement n'attend pas de code.",
            ),
            status.HTTP_429_TOO_MANY_REQUESTS: OpenApiResponse(
                description="Nouveau code demande trop tot.",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="resend-otp")
    def resend_otp(self, request, pk=None):
        payment = self.get_object()
        resend_payment_otp(payment)
        payment.refresh_from_db()
        return Response(PaymentReadSerializer(payment).data)

    @extend_schema(
        summary="Telecharger le recu d'un paiement (PDF)",
        responses={
            (status.HTTP_200_OK, "application/pdf"): OpenApiResponse(
                description="Fichier PDF du recu.",
            ),
        },
    )
    @action(detail=True, methods=["get"])
    def receipt(self, request, pk=None):
        payment = self.get_object()
        pdf = generate_receipt_pdf(payment)
        response = HttpResponse(pdf, content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="recu_PAY{payment.pk:06d}.pdf"'
        )
        return response


@extend_schema(tags=["agent"])
class AgentPaymentView(GenericAPIView):
    """POST /agent/payments/ — encaissement guichet (especes ou Mobile Money).

    Especes : l'agent initie et confirme en une etape. Mobile Money : le meme
    flux OTP que le voyageur (le paiement revient `otp_required`, le client
    confirme avec le code recu via `/payments/{id}/verify-otp/`).
    """

    permission_classes = [IsAgentGuichet]
    serializer_class = AgentPaymentSerializer

    @extend_schema(
        summary="Encaisser une reservation au guichet",
        request=AgentPaymentSerializer,
        responses={
            status.HTTP_201_CREATED: PaymentReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Moyen hors perimetre ou numero du payeur manquant.",
            ),
            status.HTTP_404_NOT_FOUND: OpenApiResponse(
                description="Reservation hors de la compagnie de l'agent.",
            ),
        },
        examples=[
            OpenApiExample(
                "Especes",
                value={"booking_id": 42, "method": "cash"},
                request_only=True,
            ),
            OpenApiExample(
                "Mobile Money (flux OTP)",
                value={
                    "booking_id": 42,
                    "method": "orange_money",
                    "phone": "+22670000001",
                },
                request_only=True,
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        profile = getattr(request.user, "agent_profile", None)
        if profile is None or profile.company_id is None:
            raise NotFound("Aucun profil agent associe a cet utilisateur.")

        serializer = AgentPaymentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        booking = data["booking"]
        # Isolation multi-tenant : l'agent n'encaisse que pour sa compagnie.
        if booking.trip.route.company_id != profile.company_id:
            raise NotFound("Reservation introuvable.")

        payment = initiate_payment(
            booking=booking,
            method=data["method"],
            phone=data.get("phone", ""),
            agent=request.user,
        )
        # Mobile Money : `initiate_payment` a deja envoye l'OTP, la confirmation
        # attend la saisie du client.
        if payment.method not in MOBILE_MONEY_METHODS:
            payment = confirm_payment(
                payment, transaction_ref=data.get("transaction_ref", "")
            )
        return Response(
            PaymentReadSerializer(payment).data, status=status.HTTP_201_CREATED
        )
