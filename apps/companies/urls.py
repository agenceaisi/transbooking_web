from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyNotificationsView,
    CompanyPaymentMethodsView,
    CompanyRegistrationRequestView,
    CompanyRequestViewSet,
    CompanySettingsView,
    PublicCompanyViewSet,
    SuperCompanyViewSet,
)


app_name = "companies"

router = DefaultRouter()
router.register("super/companies", SuperCompanyViewSet, basename="super-companies")
router.register("super/company-requests", CompanyRequestViewSet, basename="company-requests")
router.register("public/companies", PublicCompanyViewSet, basename="public-companies")

urlpatterns = [
    path(
        "auth/company/register/",
        CompanyRegistrationRequestView.as_view(),
        name="company-register",
    ),
    path("company/settings/", CompanySettingsView.as_view(), name="company-settings"),
    path(
        "company/settings/payment-methods/",
        CompanyPaymentMethodsView.as_view(),
        name="company-payment-methods",
    ),
    path(
        "company/settings/notifications/",
        CompanyNotificationsView.as_view(),
        name="company-notifications",
    ),
    path("", include(router.urls)),
]
