"""Output serializers for the dashboard responses.

These serializers document the response shapes for the OpenAPI schema. The
dashboards are read-only aggregations built in ``services.py``; the views feed
the already-computed dicts/lists straight into these serializers.
"""
from rest_framework import serializers

from apps.notifications.models import NotificationType


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #
class TravelerNextTripSerializer(serializers.Serializer):
    ticket_number = serializers.CharField()
    origin = serializers.CharField()
    destination = serializers.CharField()
    departure_time = serializers.DateTimeField()
    seat_number = serializers.CharField()
    status = serializers.CharField()
    # Compagnie du trajet (affichage « HH:MM · Compagnie » cote mobile).
    company_name = serializers.CharField(
        help_text="Nom de la compagnie du trajet."
    )
    company_sigle = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        help_text="Sigle de la compagnie (null si absent).",
    )


class NotificationSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    title = serializers.CharField()
    body = serializers.CharField()
    is_read = serializers.BooleanField()
    created_at = serializers.DateTimeField()
    # Type technique (booking, payment, parcel, trip, claim, system...) : le
    # mapping icone + couleur reste cote Flutter (cf. CLAUDE.md, jamais de libelle).
    # ChoiceField pour que l'enum soit figee dans le schema OpenAPI (codegen Flutter).
    type = serializers.ChoiceField(
        choices=NotificationType.choices,
        help_text="Valeur technique du type (mapping icone/couleur cote client).",
    )
    type_display = serializers.CharField(
        allow_blank=True,
        allow_null=True,
        help_text="Libelle FR du type, si disponible.",
    )


class TravelerDashboardSerializer(serializers.Serializer):
    next_trips = TravelerNextTripSerializer(many=True)
    active_bookings_count = serializers.IntegerField()
    pending_count = serializers.IntegerField()
    # Compteurs de la carte « Statut des billets » (Paye / En attente / Annule).
    paid_count = serializers.IntegerField(
        help_text="Nombre de billets au statut `paid`."
    )
    cancelled_count = serializers.IntegerField(
        help_text=(
            "Nombre de billets annules (`cancelled`) + rembourses (`refunded`)."
        )
    )
    recent_notifications = NotificationSummarySerializer(many=True)


# --------------------------------------------------------------------------- #
# Agent
# --------------------------------------------------------------------------- #
class AgentDepartureSerializer(serializers.Serializer):
    trip_id = serializers.IntegerField()
    origin = serializers.CharField()
    destination = serializers.CharField()
    departure_time = serializers.DateTimeField()
    registration_closes_at = serializers.DateTimeField()
    available_seats = serializers.IntegerField()
    passenger_count = serializers.IntegerField()
    vehicle_type = serializers.CharField(allow_null=True)
    total_seats = serializers.IntegerField()


class AgentTodayStatsSerializer(serializers.Serializer):
    """Bloc « Indicateurs du jour » du tableau de bord agent desktop."""

    passengers_registered = serializers.IntegerField()
    passengers_registered_yesterday = serializers.IntegerField()
    parcels_registered = serializers.IntegerField()
    parcels_registered_yesterday = serializers.IntegerField()
    upcoming_departures = serializers.IntegerField()
    upcoming_departures_yesterday = serializers.IntegerField()


class AgentDashboardSerializer(serializers.Serializer):
    next_departures = AgentDepartureSerializer(many=True)
    pending_alerts = serializers.IntegerField()
    connection_status = serializers.CharField()
    today_stats = AgentTodayStatsSerializer()


# --------------------------------------------------------------------------- #
# Company admin
# --------------------------------------------------------------------------- #
class CompanyOverviewDeltaSerializer(serializers.Serializer):
    revenue_total = serializers.FloatField()
    fill_rate_avg = serializers.FloatField()
    bookings_count = serializers.IntegerField()


class CompanyOverviewSerializer(serializers.Serializer):
    period = serializers.CharField()
    revenue_total = serializers.FloatField()
    fill_rate_avg = serializers.FloatField()
    bookings_count = serializers.IntegerField()
    avg_rating = serializers.FloatField(allow_null=True)
    vs_previous_period = CompanyOverviewDeltaSerializer()


class RevenuePointSerializer(serializers.Serializer):
    date = serializers.DateField()
    revenue = serializers.FloatField()


class FillRateByRouteSerializer(serializers.Serializer):
    route_label = serializers.CharField()
    fill_rate_pct = serializers.FloatField()


class PaymentBreakdownSerializer(serializers.Serializer):
    method = serializers.CharField()
    amount = serializers.FloatField()
    pct = serializers.FloatField()


class TopRouteSerializer(serializers.Serializer):
    route = serializers.CharField()
    revenue = serializers.FloatField()
    passengers = serializers.IntegerField()


class AgentActivitySerializer(serializers.Serializer):
    agent_name = serializers.CharField()
    bookings_today = serializers.IntegerField()
    parcels_today = serializers.IntegerField()


class CompanyAlertsSerializer(serializers.Serializer):
    unresolved_claims = serializers.IntegerField()
    unreturned_parcels = serializers.IntegerField()
    speed_reports_pending = serializers.IntegerField()


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #
class SuperOverviewSerializer(serializers.Serializer):
    total_companies = serializers.IntegerField()
    active_companies = serializers.IntegerField()
    total_bookings = serializers.IntegerField()
    total_commission_revenue = serializers.FloatField()
    active_users = serializers.IntegerField()


class RevenueByCompanySerializer(serializers.Serializer):
    company = serializers.CharField()
    revenue = serializers.FloatField()
    commission = serializers.FloatField()


class BookingsChartPointSerializer(serializers.Serializer):
    date = serializers.DateField()
    count = serializers.IntegerField()
