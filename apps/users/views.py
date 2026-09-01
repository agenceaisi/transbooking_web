from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils.decorators import method_decorator
from django_ratelimit.decorators import ratelimit
from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.core.services import log_activity
from utils.permissions import IsCompanyAdmin

from .models import User
from .serializers import (
    CompanyAgentCreateSerializer,
    CompanyAgentInvitationResponseSerializer,
    CompanyAgentInviteSerializer,
    CompanyAgentSerializer,
    CompanyAgentUpdateSerializer,
    DetailResponseSerializer,
    LogoutSerializer,
    PasswordChangeSerializer,
    TransBookingTokenObtainPairSerializer,
    UserProfileSerializer,
    UserProfileUpdateSerializer,
    UserRegistrationSerializer,
)
from .services import (
    build_agent_invitation,
    change_password,
    create_agent,
    delete_agent,
    send_temp_password_sms,
    update_agent,
)


def _to_drf_validation(exc: DjangoValidationError):
    """Convertit une ValidationError Django (levee par services.py) en erreur DRF."""
    detail = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
    return DRFValidationError(detail)


# Auth endpoints — 10 tentatives/minute par IP (cf. docs/specs/security.md §4).
auth_ratelimit = method_decorator(
    ratelimit(key="ip", rate="10/m", method="POST", block=True),
    name="post",
)


@auth_ratelimit
class UserRegistrationView(GenericAPIView):
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    @extend_schema(responses={status.HTTP_201_CREATED: UserProfileSerializer})
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserProfileSerializer(user).data, status=status.HTTP_201_CREATED)


@auth_ratelimit
class TransBookingTokenObtainPairView(TokenObtainPairView):
    serializer_class = TransBookingTokenObtainPairSerializer


@auth_ratelimit
class TransBookingTokenRefreshView(TokenRefreshView):
    pass


@auth_ratelimit
class LogoutView(GenericAPIView):
    serializer_class = LogoutSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(responses={status.HTTP_204_NO_CONTENT: None})
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            RefreshToken(serializer.validated_data["refresh"]).blacklist()
        except TokenError:
            return Response(
                {"refresh": "Token invalide ou expire."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


@auth_ratelimit
class PasswordChangeView(GenericAPIView):
    """Changement du mot de passe de l'utilisateur authentifie."""

    serializer_class = PasswordChangeSerializer
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=["auth"],
        summary="Changer son mot de passe",
        request=PasswordChangeSerializer,
        responses={
            status.HTTP_200_OK: DetailResponseSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Ancien mot de passe incorrect ou nouveau mot de passe non conforme.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"old_password": "ancienMotDePasse1", "new_password": "nouveauMotDePasse1"},
                request_only=True,
            ),
            OpenApiExample(
                "Succes",
                value={"detail": "Mot de passe modifie avec succes."},
                response_only=True,
                status_codes=["200"],
            ),
        ],
    )
    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        change_password(request.user, serializer.validated_data["new_password"])
        return Response(
            {"detail": "Mot de passe modifie avec succes."},
            status=status.HTTP_200_OK,
        )


class UserMeView(GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.request.method == "PATCH":
            return UserProfileUpdateSerializer
        return UserProfileSerializer

    @extend_schema(responses=UserProfileSerializer)
    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user)
        return Response(serializer.data)

    @extend_schema(
        request=UserProfileUpdateSerializer,
        responses=UserProfileSerializer,
    )
    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(request.user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return Response(UserProfileSerializer(user).data)


# --------------------------------------------------------------------------- #
# Company admin — gestion des agents de sa compagnie (cf. PROMPT_SUP A4)
# --------------------------------------------------------------------------- #
@extend_schema(tags=["company"])
class CompanyAgentViewSet(
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Agents (guichet / controleur) de la compagnie de l'admin courant."""

    permission_classes = [IsCompanyAdmin]
    filterset_fields = ["is_active", "agent_profile__agent_type"]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company

    def get_queryset(self):
        # Isolation multi-tenant stricte : uniquement les agents de sa compagnie.
        return (
            User.objects.filter(agent_profile__company=self.get_company())
            .select_related("role", "agent_profile__station")
            .order_by("nom", "prenom")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return CompanyAgentCreateSerializer
        if self.action in {"update", "partial_update"}:
            return CompanyAgentUpdateSerializer
        if self.action == "invite":
            return CompanyAgentInviteSerializer
        return CompanyAgentSerializer

    def get_serializer_context(self) -> dict:
        context = super().get_serializer_context()
        if getattr(self, "swagger_fake_view", False):
            return context
        context["company"] = getattr(self.request.user, "administered_company", None)
        return context

    @extend_schema(
        summary="Creer un agent (mot de passe temporaire envoye par SMS)",
        request=CompanyAgentCreateSerializer,
        responses={
            status.HTTP_201_CREATED: CompanyAgentSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Telephone deja utilise, role invalide ou gare hors compagnie.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={
                    "prenom": "Issa",
                    "nom": "Kabore",
                    "phone": "+22670000100",
                    "role": "agent_guichet",
                },
                request_only=True,
            ),
        ],
    )
    def create(self, request, *args, **kwargs):
        company = self.get_company()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            agent = create_agent(serializer.validated_data, company, actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(
            CompanyAgentSerializer(agent).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Modifier / activer / desactiver un agent",
        request=CompanyAgentUpdateSerializer,
        responses={status.HTTP_200_OK: CompanyAgentSerializer},
    )
    def update(self, request, *args, **kwargs):
        agent = self.get_object()
        serializer = self.get_serializer(
            data=request.data, partial=kwargs.get("partial", False)
        )
        serializer.is_valid(raise_exception=True)
        try:
            agent = update_agent(agent, serializer.validated_data, actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(CompanyAgentSerializer(agent).data)

    @extend_schema(
        summary="Supprimer un agent (interdit s'il a de l'activite)",
        responses={
            status.HTTP_204_NO_CONTENT: None,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="L'agent a de l'activite : seule la desactivation est possible.",
            ),
        },
    )
    def destroy(self, request, *args, **kwargs):
        agent = self.get_object()
        try:
            delete_agent(agent, actor=request.user)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Reinitialiser le mot de passe d'un agent (nouveau code par SMS)",
        request=None,
        responses={
            status.HTTP_200_OK: DetailResponseSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="L'agent n'a pas de numero de telephone.",
            ),
        },
    )
    @action(detail=True, methods=["post"], url_path="reset-password")
    def reset_password(self, request, pk=None):
        agent = self.get_object()
        try:
            # Le mot de passe genere part par SMS : jamais renvoye dans la reponse.
            send_temp_password_sms(agent)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        log_activity(
            request.user,
            action="agent.reset_password",
            entity_type="user",
            entity_id=agent.id,
        )
        return Response(
            {"detail": "Un mot de passe temporaire a ete envoye par SMS a l'agent."}
        )

    @extend_schema(
        summary="Inviter un agent par SMS (lien de creation de compte)",
        request=CompanyAgentInviteSerializer,
        responses={
            status.HTTP_201_CREATED: CompanyAgentInvitationResponseSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Telephone deja utilise ou role invalide.",
            ),
        },
        examples=[
            OpenApiExample(
                "Requete",
                value={"phone": "+22670000101", "role": "controleur", "prenom": "Awa"},
                request_only=True,
            ),
        ],
    )
    @action(detail=False, methods=["post"])
    def invite(self, request):
        company = self.get_company()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            invitation = build_agent_invitation(serializer.validated_data, company)
        except DjangoValidationError as exc:
            raise _to_drf_validation(exc) from exc
        return Response(
            {
                "detail": "Invitation envoyee par SMS.",
                "phone": invitation["phone"],
                "role": invitation["role"],
                "invite_url": invitation["invite_url"],
                "expires_in_hours": invitation["expires_in_hours"],
            },
            status=status.HTTP_201_CREATED,
        )
