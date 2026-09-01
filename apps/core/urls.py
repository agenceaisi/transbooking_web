from django.urls import path

from .views import (
    SuperActivityLogListView,
    SuperCommissionSettingsView,
    SuperNotificationListView,
    SuperPaymentMethodsView,
    SuperSettingsView,
)


app_name = "core"

urlpatterns = [
    path(
        "super/activity-logs/",
        SuperActivityLogListView.as_view(),
        name="super-activity-logs",
    ),
    path(
        "super/notifications/",
        SuperNotificationListView.as_view(),
        name="super-notifications",
    ),
    path(
        "super/settings/commissions/",
        SuperCommissionSettingsView.as_view(),
        name="super-settings-commissions",
    ),
    path(
        "super/settings/payment-methods/",
        SuperPaymentMethodsView.as_view(),
        name="super-settings-payment-methods",
    ),
    path("super/settings/", SuperSettingsView.as_view(), name="super-settings"),
]
