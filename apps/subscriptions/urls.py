from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanySubscriptionInvoiceDownloadView,
    CompanySubscriptionInvoiceListView,
    CompanySubscriptionView,
    SuperSubscriptionPlanViewSet,
    SuperSubscriptionViewSet,
)


app_name = "subscriptions"

router = DefaultRouter()
router.register(
    "super/subscription-plans",
    SuperSubscriptionPlanViewSet,
    basename="super-subscription-plans",
)
router.register(
    "super/subscriptions",
    SuperSubscriptionViewSet,
    basename="super-subscriptions",
)

urlpatterns = [
    # L'ordre importe : les segments fixes avant le parametre {id}.
    path(
        "company/subscription/invoices/<int:pk>/download/",
        CompanySubscriptionInvoiceDownloadView.as_view(),
        name="company-subscription-invoice-download",
    ),
    path(
        "company/subscription/invoices/",
        CompanySubscriptionInvoiceListView.as_view(),
        name="company-subscription-invoices",
    ),
    path(
        "company/subscription/",
        CompanySubscriptionView.as_view(),
        name="company-subscription",
    ),
    path("", include(router.urls)),
]
