from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AgentBookingViewSet,
    BoardingAllView,
    BoardingCheckInView,
    BoardingValidateView,
    BookingViewSet,
    CompanyBookingViewSet,
    ScanHistoryView,
    ScanView,
)


app_name = "bookings"

router = DefaultRouter()
router.register("bookings", BookingViewSet, basename="bookings")
router.register("agent/bookings", AgentBookingViewSet, basename="agent-bookings")
router.register("company/bookings", CompanyBookingViewSet, basename="company-bookings")

urlpatterns = [
    # L'historique doit preceder le scan pour ne pas etre capte par la vue POST.
    path("agent/scan/history/", ScanHistoryView.as_view(), name="agent-scan-history"),
    path("agent/scan/", ScanView.as_view(), name="agent-scan"),
    # L'ordre importe : les segments fixes avant le parametre booking_id.
    path(
        "agent/trips/<int:trip_id>/boarding/all/",
        BoardingAllView.as_view(),
        name="agent-boarding-all",
    ),
    path(
        "agent/trips/<int:trip_id>/boarding/validate/",
        BoardingValidateView.as_view(),
        name="agent-boarding-validate",
    ),
    path(
        "agent/trips/<int:trip_id>/boarding/<int:booking_id>/",
        BoardingCheckInView.as_view(),
        name="agent-boarding-checkin",
    ),
    path("", include(router.urls)),
]
