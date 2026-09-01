from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from utils.permissions import IsAgent, IsAgentGuichet, IsCompanyAdmin, IsControleur

from .models import Trip
from .serializers import (
    TripDelaySerializer,
    TripDetailSerializer,
    TripReadSerializer,
    TripWriteSerializer,
)
from .services import (
    cancel_trip,
    delay_trip,
    generate_trips,
    search_trips,
    with_read_annotations,
)


def _requesting_company_id(user) -> int:
    """Return the company id of an agent or a company admin, or raise 404.

    Args:
        user: The authenticated agent (guichet/controleur) or company admin.

    Returns:
        The user's company primary key.
    """
    profile = getattr(user, "agent_profile", None)
    if profile is not None and profile.company_id is not None:
        return profile.company_id
    company = getattr(user, "administered_company", None)
    if company is not None:
        return company.id
    raise NotFound("Aucune compagnie associee a cet utilisateur.")


class CompanyTripViewSet(viewsets.ModelViewSet):
    """CRUD des voyages de la compagnie du company admin courant."""

    permission_classes = [IsCompanyAdmin]
    filterset_fields = ["route", "status"]

    def get_company(self):
        company = getattr(self.request.user, "administered_company", None)
        if company is None:
            raise NotFound("Aucune compagnie associee a cet utilisateur.")
        return company

    def get_queryset(self):
        return with_read_annotations(
            Trip.objects.filter(route__company=self.get_company()).select_related(
                "route__company",
                "route__origin_city",
                "route__destination_city",
                "vehicle",
            )
        )

    def get_serializer_class(self):
        if self.action in {"list", "retrieve"}:
            return TripReadSerializer
        return TripWriteSerializer

    def filter_queryset(self, queryset):
        queryset = super().filter_queryset(queryset)
        date = self.request.query_params.get("date")
        if date:
            queryset = queryset.filter(departure_time__date=date)
        return queryset

    def destroy(self, request, *args, **kwargs):
        # La suppression d'un voyage = annulation + notification des passagers.
        trip = self.get_object()
        reason = request.data.get("reason", "")
        cancel_trip(trip, reason)
        return Response(TripReadSerializer(trip).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"])
    def generate(self, request):
        try:
            route_id = int(request.data["route_id"])
            schedule_config = request.data["schedule_config"]
            days = int(request.data["days"])
        except (KeyError, TypeError, ValueError):
            raise ValidationError(
                "Champs requis : route_id (int), schedule_config (liste), days (int)."
            )

        # Isolation : le trajet doit appartenir a la compagnie de l'admin.
        if not self.get_company().routes.filter(pk=route_id).exists():
            raise NotFound("Trajet introuvable.")

        trips = generate_trips(route_id, schedule_config, days)
        serializer = TripReadSerializer(trips, many=True)
        return Response(
            {"created": len(trips), "trips": serializer.data},
            status=status.HTTP_201_CREATED,
        )


class PublicTripSearchView(generics.ListAPIView):
    """Recherche publique de voyages.

    Query params : origin_city, dest_city, date, passengers (int),
    max_price, direct (bool), company (id), min_rating (0-5). Retourne les
    voyages programmes ayant assez de places, ordonnes par heure de depart.
    """

    serializer_class = TripReadSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        """Validate the query params, then delegate the filtering.

        La recherche elle-meme vit dans ``apps.trips.services.search_trips`` :
        les pages publiques du site l'appellent directement, sans passer par
        HTTP. Cette vue ne fait donc plus que traduire des parametres de
        requete en criteres types et remonter les saisies invalides.

        Returns:
            The matching trips queryset.

        Raises:
            ValidationError: If a numeric parameter is not numeric.
        """
        params = self.request.query_params

        def entier(nom):
            valeur = params.get(nom)
            if not valeur:
                return None
            try:
                return int(valeur)
            except ValueError:
                raise ValidationError(f"Le parametre '{nom}' doit etre un entier.")

        def nombre(nom):
            valeur = params.get(nom)
            if not valeur:
                return None
            try:
                return float(valeur)
            except ValueError:
                raise ValidationError(f"Le parametre '{nom}' doit etre numerique.")

        return search_trips(
            origin_city_id=entier("origin_city"),
            destination_city_id=entier("dest_city"),
            date=params.get("date") or None,
            passengers=entier("passengers"),
            max_price=nombre("max_price"),
            company_id=entier("company"),
            min_rating=nombre("min_rating"),
            direct=params.get("direct", "").lower() in {"true", "1"},
        )


class PublicTripDetailView(generics.RetrieveAPIView):
    """Detail public d'un voyage + sieges disponibles."""

    serializer_class = TripDetailSerializer
    permission_classes = [AllowAny]
    queryset = with_read_annotations(
        Trip.objects.select_related(
            "route__company",
            "route__origin_city",
            "route__destination_city",
            "vehicle",
        )
    )


class AgentTodayTripsView(generics.ListAPIView):
    """Voyages de la gare/vehicule de l'agent connecte pour une date donnee.

    Le parametre optionnel ``date`` (``YYYY-MM-DD``) permet de consulter un
    autre jour que la journee en cours (defaut). Alimente le selecteur de
    jour de l'ecran « Programme de la semaine » (guichet et controleur).
    """

    serializer_class = TripReadSerializer
    permission_classes = [IsAgent]
    pagination_class = None

    def _target_date(self):
        raw = self.request.query_params.get("date")
        if not raw:
            return timezone.localdate()
        try:
            return datetime.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            raise ValidationError({"date": "Format attendu : YYYY-MM-DD."})

    def get_queryset(self):
        profile = getattr(self.request.user, "agent_profile", None)
        if profile is None or profile.company_id is None:
            raise NotFound("Aucun profil agent associe a cet utilisateur.")

        queryset = with_read_annotations(
            Trip.objects.filter(
                route__company_id=profile.company_id,
                departure_time__date=self._target_date(),
            ).select_related(
                "route__company",
                "route__origin_city",
                "route__destination_city",
                "vehicle",
            )
        )

        # On cible le perimetre de l'agent : son vehicule et/ou sa gare.
        scope = Q()
        if profile.vehicle_id:
            scope |= Q(vehicle_id=profile.vehicle_id)
        if profile.station_id:
            scope |= Q(route__origin_station_id=profile.station_id)
        if scope:
            queryset = queryset.filter(scope)

        return queryset.order_by("departure_time")


class TripDelayView(GenericAPIView):
    """POST /api/v1/agent/trips/{id}/delay/ — reporter un voyage de N minutes.

    Ouvert a l'agent guichet, au controleur et au company admin du perimetre
    du voyage (isolation par compagnie, cf. requetes agent module §2).
    """

    permission_classes = [IsAgentGuichet | IsControleur | IsCompanyAdmin]
    serializer_class = TripDelaySerializer

    def post(self, request, trip_id=None):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        company_id = _requesting_company_id(request.user)

        with transaction.atomic():
            try:
                trip = Trip.objects.select_for_update().get(
                    pk=trip_id, route__company_id=company_id
                )
            except Trip.DoesNotExist:
                raise NotFound("Voyage introuvable.")
            trip = delay_trip(trip, serializer.validated_data["minutes"])

        return Response(TripReadSerializer(trip).data)
