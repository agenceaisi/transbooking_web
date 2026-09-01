from drf_spectacular.utils import OpenApiExample, OpenApiResponse, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.exceptions import ValidationError as DRFValidationError
from rest_framework.generics import ListAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.core.services import log_activity
from utils.permissions import IsCompanyAdmin, IsSuperAdmin, IsVoyageur

from .models import Review
from .serializers import (
    ReviewCreateSerializer,
    ReviewReadSerializer,
    ReviewRespondSerializer,
    TestimonialSerializer,
    TestimonialToggleSerializer,
)
from .services import create_review, flag_review, respond_to_review, word_cloud


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
# Public + voyageur
# --------------------------------------------------------------------------- #


class ReviewViewSet(
    mixins.CreateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Avis publics d'une compagnie (lecture) et depot d'un avis (voyageur)."""

    def get_permissions(self):
        if self.action == "create":
            return [IsVoyageur()]
        return [AllowAny()]

    def get_serializer_class(self):
        if self.action == "create":
            return ReviewCreateSerializer
        return ReviewReadSerializer

    def get_queryset(self):
        # Liste publique : avis non signales, filtrables par ?company_id=.
        queryset = Review.objects.filter(is_flagged=False).select_related(
            "company", "user"
        )
        company_id = self.request.query_params.get("company_id")
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return queryset

    @extend_schema(
        request=ReviewCreateSerializer,
        responses={status.HTTP_201_CREATED: ReviewReadSerializer},
    )
    def create(self, request, *args, **kwargs):
        # La creation renvoie le serialiseur de lecture (id + statut) pour que le
        # front bascule sur le detail de l'avis sans reinvalider la liste.
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        review = create_review(serializer.validated_data, user=request.user)
        return Response(
            ReviewReadSerializer(review).data, status=status.HTTP_201_CREATED
        )


# --------------------------------------------------------------------------- #
# Admin compagnie
# --------------------------------------------------------------------------- #


class CompanyReviewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Tous les avis de la compagnie de l'admin courant (signales inclus)."""

    permission_classes = [IsCompanyAdmin]
    serializer_class = ReviewReadSerializer

    def get_queryset(self):
        return Review.objects.filter(
            company=_admin_company(self.request.user)
        ).select_related("company", "user")

    @action(detail=True, methods=["post", "patch"])
    def respond(self, request, pk=None):
        """POST/PATCH /company/reviews/{id}/respond/ — repondre a un avis."""
        review = self.get_object()
        serializer = ReviewRespondSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        respond_to_review(review, serializer.validated_data["response"])
        return Response(ReviewReadSerializer(review).data)

    @action(detail=True, methods=["post"])
    def flag(self, request, pk=None):
        """POST /company/reviews/{id}/flag/ — signaler un avis au super admin."""
        review = self.get_object()
        flag_review(review)
        return Response(ReviewReadSerializer(review).data)

    # NB : pas de DestroyModelMixin — l'admin ne peut pas supprimer un avis
    # (cf. business_rules.md §4) ; DELETE renvoie donc 405. Seul le super admin
    # le peut, via l'administration.

    @action(detail=False, methods=["get"], url_path="word-cloud")
    def word_cloud(self, request):
        """GET /company/reviews/word-cloud/ — frequence des mots des avis."""
        return Response(word_cloud(self.get_queryset()))


# --------------------------------------------------------------------------- #
# Public — temoignages de la page d'accueil
# --------------------------------------------------------------------------- #
@extend_schema(tags=["public"])
class PublicTestimonialListView(ListAPIView):
    """GET /public/testimonials/ — temoignages valides par le super admin."""

    permission_classes = [AllowAny]
    serializer_class = TestimonialSerializer

    def get_queryset(self):
        # Seuls les avis explicitement mis en avant et non signales sortent.
        queryset = Review.objects.filter(
            is_testimonial=True, is_flagged=False
        ).select_related("company", "user")
        company_id = self.request.query_params.get("company_id")
        if company_id:
            queryset = queryset.filter(company_id=company_id)
        return queryset


# --------------------------------------------------------------------------- #
# Super admin — curation des temoignages
# --------------------------------------------------------------------------- #
@extend_schema(tags=["super"])
class SuperReviewViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    viewsets.GenericViewSet,
):
    """Tous les avis de la plateforme + selection des temoignages."""

    permission_classes = [IsSuperAdmin]
    queryset = Review.objects.select_related("company", "user")
    filterset_fields = ["company", "rating", "is_flagged", "is_testimonial"]

    def get_serializer_class(self):
        if self.action == "testimonial":
            return TestimonialToggleSerializer
        return ReviewReadSerializer

    @extend_schema(
        summary="Mettre un avis en avant comme temoignage (ou le retirer)",
        request=TestimonialToggleSerializer,
        responses={
            status.HTTP_200_OK: ReviewReadSerializer,
            status.HTTP_400_BAD_REQUEST: OpenApiResponse(
                description="Un avis signale ne peut pas devenir temoignage.",
            ),
        },
        examples=[
            OpenApiExample("Requete", value={"is_testimonial": True}, request_only=True),
        ],
    )
    @action(detail=True, methods=["post"])
    def testimonial(self, request, pk=None):
        review = self.get_object()
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        is_testimonial = serializer.validated_data["is_testimonial"]

        # Un avis signale par la compagnie ne peut pas etre mis en vitrine.
        if is_testimonial and review.is_flagged:
            raise DRFValidationError(
                {"detail": "Un avis signale ne peut pas etre mis en avant."}
            )

        review.is_testimonial = is_testimonial
        review.save(update_fields=["is_testimonial", "updated_at"])
        log_activity(
            request.user,
            action="review.testimonial",
            entity_type="review",
            entity_id=review.id,
            details={"is_testimonial": is_testimonial},
        )
        return Response(ReviewReadSerializer(review).data)
