from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import VehicleViewSet


app_name = "vehicles"

router = DefaultRouter()
router.register("company/vehicles", VehicleViewSet, basename="company-vehicles")

urlpatterns = [
    path("", include(router.urls)),
]
