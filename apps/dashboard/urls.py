from django.urls import path

from .views import (
    AgentDashboardView,
    CompanyAgentActivityView,
    CompanyAlertsView,
    CompanyDashboardExportView,
    CompanyDashboardView,
    CompanyFillRateByRouteView,
    CompanyPaymentBreakdownView,
    CompanyRevenueChartView,
    CompanyTopRoutesView,
    SuperBookingsChartView,
    SuperDashboardView,
    SuperRevenueByCompanyView,
    TravelerDashboardView,
)

app_name = "dashboard"

urlpatterns = [
    # Voyageur
    path(
        "dashboard/traveler/",
        TravelerDashboardView.as_view(),
        name="traveler",
    ),
    # Agent
    path(
        "agent/dashboard/",
        AgentDashboardView.as_view(),
        name="agent",
    ),
    # Company admin
    path(
        "company/dashboard/",
        CompanyDashboardView.as_view(),
        name="company",
    ),
    path(
        "company/dashboard/revenue-chart/",
        CompanyRevenueChartView.as_view(),
        name="company-revenue-chart",
    ),
    path(
        "company/dashboard/fill-rate-by-route/",
        CompanyFillRateByRouteView.as_view(),
        name="company-fill-rate-by-route",
    ),
    path(
        "company/dashboard/payment-breakdown/",
        CompanyPaymentBreakdownView.as_view(),
        name="company-payment-breakdown",
    ),
    path(
        "company/dashboard/top-routes/",
        CompanyTopRoutesView.as_view(),
        name="company-top-routes",
    ),
    path(
        "company/dashboard/agent-activity/",
        CompanyAgentActivityView.as_view(),
        name="company-agent-activity",
    ),
    path(
        "company/dashboard/alerts/",
        CompanyAlertsView.as_view(),
        name="company-alerts",
    ),
    path(
        "company/dashboard/export/",
        CompanyDashboardExportView.as_view(),
        name="company-export",
    ),
    # Super admin
    path(
        "super/dashboard/",
        SuperDashboardView.as_view(),
        name="super",
    ),
    path(
        "super/dashboard/revenue-by-company/",
        SuperRevenueByCompanyView.as_view(),
        name="super-revenue-by-company",
    ),
    path(
        "super/dashboard/bookings-chart/",
        SuperBookingsChartView.as_view(),
        name="super-bookings-chart",
    ),
]
