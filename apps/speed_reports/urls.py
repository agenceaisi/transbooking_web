from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanySpeedReportViewSet,
    SpeedReportViewSet,
    SuperSpeedReportViewSet,
)


app_name = "speed_reports"

router = DefaultRouter()
router.register("speed-reports", SpeedReportViewSet, basename="speed-reports")
router.register(
    "company/speed-reports",
    CompanySpeedReportViewSet,
    basename="company-speed-reports",
)
router.register(
    "super/speed-reports",
    SuperSpeedReportViewSet,
    basename="super-speed-reports",
)

urlpatterns = [
    path("", include(router.urls)),
]
