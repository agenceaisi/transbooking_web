from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    AgentTodayTripsView,
    CompanyTripViewSet,
    PublicTripDetailView,
    PublicTripSearchView,
    TripDelayView,
)


app_name = "trips"

router = DefaultRouter()
router.register("company/trips", CompanyTripViewSet, basename="company-trips")

urlpatterns = [
    path("trips/search/", PublicTripSearchView.as_view(), name="trip-search"),
    path("trips/<int:pk>/", PublicTripDetailView.as_view(), name="trip-detail"),
    path("agent/trips/today/", AgentTodayTripsView.as_view(), name="agent-trips-today"),
    path(
        "agent/trips/<int:trip_id>/delay/",
        TripDelayView.as_view(),
        name="agent-trip-delay",
    ),
    path("", include(router.urls)),
]
