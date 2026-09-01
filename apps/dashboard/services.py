"""Read-only aggregations powering the dashboards (PROMPT 10).

Every statistic is computed through the Django ORM (``Count``, ``Sum``,
``Avg``, ``annotate``, ``Trunc*``) — never raw SQL. Functions are pure: they
receive already-resolved objects (company, user, period range) and return
plain serialisable Python structures. The HTTP layer (``views.py``) handles
authentication, permissions, caching and request parsing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.apps import apps as django_apps
from django.db.models import (
    Avg,
    Count,
    DecimalField,
    ExpressionWrapper,
    F,
    FloatField,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce, TruncDate, TruncWeek
from django.utils import timezone

from apps.bookings.models import Booking, BookingStatus
from apps.claims.models import UNRESOLVED_STATUSES, Claim
from apps.companies.models import Company, CompanyStatus
from apps.parcels.models import Parcel, ParcelStatus
from apps.payments.models import Payment, PaymentStatus
from apps.reviews.models import Review
from apps.speed_reports.models import SpeedReport, SpeedReportStatus
from apps.trips.models import Trip


# Au-dela de cette duree, les courbes temporelles sont regroupees par semaine
# plutot que par jour (lisibilite des graphiques annuels).
_WEEK_GRANULARITY_THRESHOLD = timedelta(days=92)


@dataclass(frozen=True)
class PeriodRange:
    """Resolved time window for a dashboard query.

    Attributes:
        start: Inclusive lower bound (timezone-aware).
        end: Exclusive upper bound (timezone-aware).
        previous_start: Lower bound of the comparison window.
        previous_end: Upper bound of the comparison window (== ``start``).
        label: Human-readable period name.
    """

    start: datetime
    end: datetime
    previous_start: datetime
    previous_end: datetime
    label: str

    @property
    def group_by_week(self) -> bool:
        """Whether time series should be grouped weekly instead of daily."""
        return (self.end - self.start) > _WEEK_GRANULARITY_THRESHOLD


def _aware(value: date) -> datetime:
    """Return midnight of ``value`` in the active timezone."""
    return timezone.make_aware(datetime.combine(value, time.min))


def resolve_period(
    period: str = "month",
    start_date: date | None = None,
    end_date: date | None = None,
) -> PeriodRange:
    """Build the time window (and its comparison window) for a dashboard.

    The previous window is always the same duration immediately preceding
    ``start``, which keeps ``vs_previous_period`` deltas meaningful for every
    period type, including ``custom``.

    Args:
        period: One of ``today``, ``week``, ``month``, ``year`` or ``custom``.
        start_date: Required when ``period == 'custom'``.
        end_date: Required when ``period == 'custom'``.

    Returns:
        The resolved :class:`PeriodRange`.

    Raises:
        ValueError: If ``custom`` is requested without both bounds.
    """
    now = timezone.localtime()
    today = now.date()

    if period == "today":
        start = _aware(today)
        end = start + timedelta(days=1)
        label = "Aujourd'hui"
    elif period == "week":
        monday = today - timedelta(days=today.weekday())
        start = _aware(monday)
        end = start + timedelta(days=7)
        label = "Cette semaine"
    elif period == "year":
        start = _aware(date(today.year, 1, 1))
        end = _aware(date(today.year + 1, 1, 1))
        label = "Cette annee"
    elif period == "custom":
        if start_date is None or end_date is None:
            raise ValueError(
                "Les parametres start_date et end_date sont requis pour "
                "period=custom."
            )
        start = _aware(start_date)
        # Borne haute exclusive : on inclut toute la journee end_date.
        end = _aware(end_date) + timedelta(days=1)
        label = f"Du {start_date:%d/%m/%Y} au {end_date:%d/%m/%Y}"
    else:  # month (defaut)
        start = _aware(date(today.year, today.month, 1))
        if today.month == 12:
            end = _aware(date(today.year + 1, 1, 1))
        else:
            end = _aware(date(today.year, today.month + 1, 1))
        label = "Ce mois"

    span = end - start
    return PeriodRange(
        start=start,
        end=end,
        previous_start=start - span,
        previous_end=start,
        label=label,
    )


def _money(value) -> float:
    """Coerce a (possibly ``None``) money aggregate to a rounded float."""
    return float(Decimal(value or 0).quantize(Decimal("0.01")))


def _pct(part, whole) -> float:
    """Percentage of ``part`` over ``whole`` (0.0 when ``whole`` is falsy)."""
    if not whole:
        return 0.0
    return round(float(part) * 100.0 / float(whole), 2)


def _notification_model():
    """Return the Notification model, or ``None`` if the app has no models yet.

    The ``notifications`` app is wired in ``INSTALLED_APPS`` but only gains a
    model in PROMPT 11. Dashboards degrade gracefully until then.
    """
    try:
        return django_apps.get_model("notifications", "Notification")
    except LookupError:
        return None


def _recent_notifications(user, limit: int = 5) -> list[dict]:
    """Return the latest in-app notifications for ``user`` (empty if unavailable)."""
    model = _notification_model()
    if model is None:
        return []
    rows = (
        model.objects.filter(user=user).order_by("-created_at")[:limit]
    )
    result = []
    for row in rows:
        # get_type_display() n'existe que si le modele porte un champ `type`
        # (toujours vrai depuis PROMPT 11) ; on reste defensif si absent.
        get_display = getattr(row, "get_type_display", None)
        result.append(
            {
                "id": row.id,
                "title": getattr(row, "title", ""),
                "body": getattr(row, "body", ""),
                "is_read": getattr(row, "is_read", False),
                "created_at": row.created_at,
                "type": getattr(row, "type", "system"),
                "type_display": get_display() if callable(get_display) else None,
            }
        )
    return result


def _unread_notifications_count(user) -> int:
    """Return the unread in-app notification count (0 if app has no model yet)."""
    model = _notification_model()
    if model is None:
        return 0
    return model.objects.filter(user=user, is_read=False).count()


# --------------------------------------------------------------------------- #
# Voyageur
# --------------------------------------------------------------------------- #
def traveler_dashboard(user) -> dict:
    """Build the traveler home dashboard.

    Args:
        user: The authenticated voyageur.

    Returns:
        A dict with upcoming trips, booking counters and recent notifications.
    """
    now = timezone.now()
    upcoming = (
        Booking.objects.filter(
            user=user,
            trip__departure_time__gte=now,
        )
        .exclude(status=BookingStatus.CANCELLED)
        .select_related(
            "trip__route__origin_city",
            "trip__route__destination_city",
            "trip__route__company",
        )
        .order_by("trip__departure_time")[:3]
    )

    counters = Booking.objects.filter(user=user).aggregate(
        active=Count("id", filter=Q(status=BookingStatus.PAID)),
        pending=Count("id", filter=Q(status=BookingStatus.PENDING)),
        # Annules = statut annule + rembourse (carte « Statut des billets »).
        cancelled=Count(
            "id",
            filter=Q(
                status__in=[BookingStatus.CANCELLED, BookingStatus.REFUNDED]
            ),
        ),
    )

    next_trips = [
        {
            "ticket_number": booking.ticket_number,
            "origin": booking.trip.route.origin_city.name,
            "destination": booking.trip.route.destination_city.name,
            "departure_time": booking.trip.departure_time,
            "seat_number": booking.seat_number,
            "status": booking.status,
            "company_name": booking.trip.route.company.name,
            "company_sigle": booking.trip.route.company.sigle or None,
        }
        for booking in upcoming
    ]

    return {
        "next_trips": next_trips,
        "active_bookings_count": counters["active"] or 0,
        "pending_count": counters["pending"] or 0,
        # paid_count reprend le meme total que active_bookings_count (statut paid),
        # expose explicitement pour la carte « Statut des billets ».
        "paid_count": counters["active"] or 0,
        "cancelled_count": counters["cancelled"] or 0,
        "recent_notifications": _recent_notifications(user, limit=5),
    }


# --------------------------------------------------------------------------- #
# Agent guichet / controleur
# --------------------------------------------------------------------------- #
def agent_dashboard(agent) -> dict:
    """Build the agent dashboard for the agent's station/vehicle scope.

    Args:
        agent: The authenticated agent (must carry an ``agent_profile``).

    Returns:
        A dict with the next departures, pending alerts and a connection hint.
    """
    empty_stats = {
        "passengers_registered": 0,
        "passengers_registered_yesterday": 0,
        "parcels_registered": 0,
        "parcels_registered_yesterday": 0,
        "upcoming_departures": 0,
        "upcoming_departures_yesterday": 0,
    }

    profile = getattr(agent, "agent_profile", None)
    if profile is None or profile.company_id is None:
        return {
            "next_departures": [],
            "pending_alerts": 0,
            "connection_status": "online",
            "today_stats": empty_stats,
        }

    now = timezone.now()
    trips = Trip.objects.filter(
        route__company_id=profile.company_id,
        departure_time__gte=now,
    ).select_related("route__origin_city", "route__destination_city", "vehicle")

    # Perimetre de l'agent : son vehicule et/ou sa gare de rattachement.
    trip_scope = Q()
    if profile.vehicle_id:
        trip_scope |= Q(vehicle_id=profile.vehicle_id)
    if profile.station_id:
        trip_scope |= Q(route__origin_station_id=profile.station_id)
    if trip_scope:
        trips = trips.filter(trip_scope)

    trips = trips.annotate(
        passenger_count=Count(
            "bookings", filter=~Q(bookings__status=BookingStatus.CANCELLED)
        )
    ).order_by("departure_time")[:3]

    next_departures = [
        {
            "trip_id": trip.id,
            "origin": trip.route.origin_city.name,
            "destination": trip.route.destination_city.name,
            "departure_time": trip.departure_time,
            "registration_closes_at": trip.registration_closes_at,
            "available_seats": trip.available_seats,
            "passenger_count": trip.passenger_count,
            "vehicle_type": trip.vehicle.vehicle_type or None,
            "total_seats": trip.vehicle.total_seats,
        }
        for trip in trips
    ]

    return {
        "next_departures": next_departures,
        "pending_alerts": _unread_notifications_count(agent),
        "connection_status": "online",
        "today_stats": _agent_today_stats(profile, trip_scope),
    }


def _agent_today_stats(profile, trip_scope: Q) -> dict:
    """Build the « Indicateurs du jour » counters, with a comparison to yesterday.

    Args:
        profile: The agent's ``AgentProfile`` (carries company/station/vehicle).
        trip_scope: The ``Trip``-level ``Q`` scoping departures to the agent's
            station and/or vehicle (empty means the whole company).

    Returns:
        A dict with today/yesterday counts for registered passengers, registered
        parcels and scheduled departures (cf. requetes agent module §6).
    """
    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    booking_scope = Q()
    if profile.vehicle_id:
        booking_scope |= Q(trip__vehicle_id=profile.vehicle_id)
    if profile.station_id:
        booking_scope |= Q(trip__route__origin_station_id=profile.station_id)
    bookings = Booking.objects.filter(
        trip__route__company_id=profile.company_id
    ).exclude(status=BookingStatus.CANCELLED)
    if booking_scope:
        bookings = bookings.filter(booking_scope)

    parcels = Parcel.objects.filter(company_id=profile.company_id)
    if profile.station_id:
        parcels = parcels.filter(origin_station_id=profile.station_id)

    trips = Trip.objects.filter(route__company_id=profile.company_id).exclude(
        status=Trip.TripStatus.CANCELLED
    )
    if trip_scope:
        trips = trips.filter(trip_scope)

    return {
        "passengers_registered": bookings.filter(created_at__date=today).count(),
        "passengers_registered_yesterday": bookings.filter(
            created_at__date=yesterday
        ).count(),
        "parcels_registered": parcels.filter(created_at__date=today).count(),
        "parcels_registered_yesterday": parcels.filter(
            created_at__date=yesterday
        ).count(),
        "upcoming_departures": trips.filter(departure_time__date=today).count(),
        "upcoming_departures_yesterday": trips.filter(
            departure_time__date=yesterday
        ).count(),
    }


# --------------------------------------------------------------------------- #
# Company admin
# --------------------------------------------------------------------------- #
def _paid_payments(company: Company, start, end):
    """Paid payments of ``company`` confirmed within ``[start, end)``."""
    return Payment.objects.filter(
        booking__trip__route__company=company,
        status=PaymentStatus.PAID,
        paid_at__gte=start,
        paid_at__lt=end,
    )


def _company_revenue(company: Company, start, end) -> Decimal:
    """Total confirmed revenue of ``company`` over ``[start, end)``."""
    total = _paid_payments(company, start, end).aggregate(
        total=Coalesce(
            Sum("amount"), Value(0), output_field=DecimalField()
        )
    )["total"]
    return total or Decimal("0")


def _company_fill_rate(company: Company, start, end) -> float:
    """Average per-trip fill rate (%) of ``company`` over ``[start, end)``.

    Fill rate of a trip = active bookings / vehicle total seats.
    """
    fill_expr = ExpressionWrapper(
        F("seats_taken") * 100.0 / F("vehicle__total_seats"),
        output_field=FloatField(),
    )
    result = (
        Trip.objects.filter(
            route__company=company,
            departure_time__gte=start,
            departure_time__lt=end,
            vehicle__total_seats__gt=0,
        )
        .annotate(
            seats_taken=Count(
                "bookings", filter=~Q(bookings__status=BookingStatus.CANCELLED)
            )
        )
        .annotate(fill_rate=fill_expr)
        .aggregate(avg=Avg("fill_rate"))
    )
    return round(result["avg"] or 0.0, 2)


def company_overview(company: Company, period: PeriodRange) -> dict:
    """Build the company KPI overview with previous-period deltas.

    Args:
        company: The admin's company.
        period: Resolved time window.

    Returns:
        Revenue, fill rate, bookings count, average rating and the deltas
        against the previous equal-length period.
    """
    revenue = _company_revenue(company, period.start, period.end)
    prev_revenue = _company_revenue(
        company, period.previous_start, period.previous_end
    )

    fill_rate = _company_fill_rate(company, period.start, period.end)
    prev_fill_rate = _company_fill_rate(
        company, period.previous_start, period.previous_end
    )

    bookings_count = Booking.objects.filter(
        trip__route__company=company,
        created_at__gte=period.start,
        created_at__lt=period.end,
    ).count()
    prev_bookings_count = Booking.objects.filter(
        trip__route__company=company,
        created_at__gte=period.previous_start,
        created_at__lt=period.previous_end,
    ).count()

    avg_rating = Review.objects.filter(
        company=company,
        created_at__gte=period.start,
        created_at__lt=period.end,
    ).aggregate(avg=Avg("rating"))["avg"]

    return {
        "period": period.label,
        "revenue_total": _money(revenue),
        "fill_rate_avg": fill_rate,
        "bookings_count": bookings_count,
        "avg_rating": round(float(avg_rating), 2) if avg_rating is not None else None,
        "vs_previous_period": {
            "revenue_total": _money(revenue - prev_revenue),
            "fill_rate_avg": round(fill_rate - prev_fill_rate, 2),
            "bookings_count": bookings_count - prev_bookings_count,
        },
    }


def company_revenue_chart(company: Company, period: PeriodRange) -> list[dict]:
    """Return ``[{date, revenue}]`` for ``company`` over the period.

    Grouped by week for long periods (e.g. year), otherwise by day.
    """
    trunc = TruncWeek if period.group_by_week else TruncDate
    rows = (
        _paid_payments(company, period.start, period.end)
        .annotate(bucket=trunc("paid_at"))
        .values("bucket")
        .annotate(revenue=Sum("amount"))
        .order_by("bucket")
    )
    return [
        {"date": row["bucket"], "revenue": _money(row["revenue"])}
        for row in rows
    ]


def company_fill_rate_by_route(company: Company, period: PeriodRange) -> list[dict]:
    """Return ``[{route_label, fill_rate_pct}]`` for ``company`` over the period."""
    rows = (
        Trip.objects.filter(
            route__company=company,
            departure_time__gte=period.start,
            departure_time__lt=period.end,
        )
        .values(
            "route_id",
            "route__origin_city__name",
            "route__destination_city__name",
        )
        .annotate(
            seats_taken=Count(
                "bookings", filter=~Q(bookings__status=BookingStatus.CANCELLED)
            ),
            total_seats=Sum("vehicle__total_seats"),
        )
        .order_by("route__origin_city__name")
    )
    result = []
    for row in rows:
        label = (
            f"{row['route__origin_city__name']} -> "
            f"{row['route__destination_city__name']}"
        )
        result.append(
            {
                "route_label": label,
                "fill_rate_pct": _pct(row["seats_taken"], row["total_seats"]),
            }
        )
    return result


def company_payment_breakdown(company: Company, period: PeriodRange) -> list[dict]:
    """Return ``[{method, amount, pct}]`` of confirmed payments by method."""
    rows = (
        _paid_payments(company, period.start, period.end)
        .values("method")
        .annotate(amount=Sum("amount"))
        .order_by("-amount")
    )
    total = sum(row["amount"] for row in rows) or Decimal("0")
    return [
        {
            "method": row["method"],
            "amount": _money(row["amount"]),
            "pct": _pct(row["amount"], total),
        }
        for row in rows
    ]


def company_top_routes(company: Company, period: PeriodRange) -> list[dict]:
    """Return the top 5 routes by confirmed revenue over the period."""
    rows = (
        _paid_payments(company, period.start, period.end)
        .values(
            "booking__trip__route_id",
            "booking__trip__route__origin_city__name",
            "booking__trip__route__destination_city__name",
        )
        .annotate(revenue=Sum("amount"), passengers=Count("booking", distinct=True))
        .order_by("-revenue")[:5]
    )
    return [
        {
            "route": (
                f"{row['booking__trip__route__origin_city__name']} -> "
                f"{row['booking__trip__route__destination_city__name']}"
            ),
            "revenue": _money(row["revenue"]),
            "passengers": row["passengers"],
        }
        for row in rows
    ]


def company_agent_activity(company: Company) -> list[dict]:
    """Return today's booking/parcel activity per agent of ``company``."""
    today = timezone.localdate()
    profiles = (
        company.agent_profiles.select_related("user").all()
    )
    activity = []
    for profile in profiles:
        agent = profile.user
        bookings_today = Booking.objects.filter(
            agent=agent, created_at__date=today
        ).count()
        parcels_today = Parcel.objects.filter(
            registered_by=agent, created_at__date=today
        ).count()
        activity.append(
            {
                "agent_name": f"{agent.prenom} {agent.nom}".strip(),
                "bookings_today": bookings_today,
                "parcels_today": parcels_today,
            }
        )
    return activity


def company_alerts(company: Company) -> dict:
    """Return live operational alert counters for ``company``."""
    unresolved_claims = Claim.objects.filter(
        company=company, status__in=UNRESOLVED_STATUSES
    ).count()
    # Colis arrives a destination mais pas encore remis au destinataire.
    unreturned_parcels = Parcel.objects.filter(
        company=company,
        status__in=[ParcelStatus.ARRIVED, ParcelStatus.NOTIFIED],
    ).count()
    speed_reports_pending = SpeedReport.objects.filter(
        company=company, status=SpeedReportStatus.PENDING
    ).count()
    return {
        "unresolved_claims": unresolved_claims,
        "unreturned_parcels": unreturned_parcels,
        "speed_reports_pending": speed_reports_pending,
    }


# --------------------------------------------------------------------------- #
# Super admin
# --------------------------------------------------------------------------- #
def super_overview() -> dict:
    """Build the platform-wide super admin overview."""
    companies = Company.objects.aggregate(
        total=Count("id"),
        active=Count("id", filter=Q(status=CompanyStatus.ACTIVE)),
    )
    paid = Payment.objects.filter(status=PaymentStatus.PAID).aggregate(
        commission=Coalesce(
            Sum("commission"), Value(0), output_field=DecimalField()
        )
    )
    active_users = (
        django_apps.get_model("users", "User")
        .objects.filter(is_active=True)
        .count()
    )
    return {
        "total_companies": companies["total"] or 0,
        "active_companies": companies["active"] or 0,
        "total_bookings": Booking.objects.count(),
        "total_commission_revenue": _money(paid["commission"]),
        "active_users": active_users,
    }


def super_revenue_by_company() -> list[dict]:
    """Return ``[{company, revenue, commission}]`` across the platform."""
    rows = (
        Payment.objects.filter(status=PaymentStatus.PAID)
        .values("booking__trip__route__company__name")
        .annotate(revenue=Sum("amount"), commission=Sum("commission"))
        .order_by("-revenue")
    )
    return [
        {
            "company": row["booking__trip__route__company__name"],
            "revenue": _money(row["revenue"]),
            "commission": _money(row["commission"]),
        }
        for row in rows
    ]


def super_bookings_chart(period: PeriodRange) -> list[dict]:
    """Return global bookings counts over time for the super admin."""
    trunc = TruncWeek if period.group_by_week else TruncDate
    rows = (
        Booking.objects.filter(
            created_at__gte=period.start, created_at__lt=period.end
        )
        .annotate(bucket=trunc("created_at"))
        .values("bucket")
        .annotate(count=Count("id"))
        .order_by("bucket")
    )
    return [{"date": row["bucket"], "count": row["count"]} for row in rows]
