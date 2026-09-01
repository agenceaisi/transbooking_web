from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ClaimViewSet, CompanyClaimViewSet, SuperClaimViewSet


app_name = "claims"

router = DefaultRouter()
router.register("claims", ClaimViewSet, basename="claims")
router.register("company/claims", CompanyClaimViewSet, basename="company-claims")
router.register("super/claims", SuperClaimViewSet, basename="super-claims")

urlpatterns = [
    path("", include(router.urls)),
]
