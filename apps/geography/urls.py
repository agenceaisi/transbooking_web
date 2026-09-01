from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import PublicCityViewSet, StationViewSet, SuperCityViewSet


app_name = "geography"

router = DefaultRouter()
router.register("cities", PublicCityViewSet, basename="cities")
router.register("super/cities", SuperCityViewSet, basename="super-cities")
router.register("company/stations", StationViewSet, basename="company-stations")

urlpatterns = [
    path("", include(router.urls)),
]
