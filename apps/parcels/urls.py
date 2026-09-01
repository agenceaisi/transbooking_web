from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AgentParcelViewSet, CompanyParcelViewSet, ParcelTrackView


app_name = "parcels"

router = DefaultRouter()
router.register("agent/parcels", AgentParcelViewSet, basename="agent-parcels")
router.register("company/parcels", CompanyParcelViewSet, basename="company-parcels")

urlpatterns = [
    path(
        "parcels/track/<str:tracking_number>/",
        ParcelTrackView.as_view(),
        name="parcel-track",
    ),
    path("", include(router.urls)),
]
