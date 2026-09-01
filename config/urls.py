"""Project URL configuration."""
from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularRedocView,
    SpectacularSwaggerView,
)
from rest_framework.routers import DefaultRouter


api_router = DefaultRouter()

urlpatterns = [
    path("admin/", admin.site.urls),
    # Documentation OpenAPI
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path(
        "api/docs/",
        SpectacularSwaggerView.as_view(url_name="schema"),
        name="swagger-ui",
    ),
    path(
        "api/redoc/",
        SpectacularRedocView.as_view(url_name="schema"),
        name="redoc",
    ),
    path("api/v1/", include("apps.core.urls")),
    path("api/v1/", include("apps.users.urls")),
    path("api/v1/", include("apps.companies.urls")),
    path("api/v1/", include("apps.subscriptions.urls")),
    path("api/v1/", include("apps.geography.urls")),
    path("api/v1/", include("apps.vehicles.urls")),
    path("api/v1/", include("apps.routes.urls")),
    path("api/v1/", include("apps.trips.urls")),
    path("api/v1/", include("apps.bookings.urls")),
    path("api/v1/", include("apps.payments.urls")),
    path("api/v1/", include("apps.parcels.urls")),
    path("api/v1/", include("apps.claims.urls")),
    path("api/v1/", include("apps.reviews.urls")),
    path("api/v1/", include("apps.speed_reports.urls")),
    path("api/v1/", include("apps.sync.urls")),
    path("api/v1/", include("apps.dashboard.urls")),
    path("api/v1/", include("apps.messaging.urls")),
    path("api/v1/", include("apps.notifications.urls")),
    path("api/v1/", include(api_router.urls)),
    # Le site public occupe la racine. Declare en dernier : ses routes
    # sont larges, elles ne doivent jamais masquer /api/ ni /admin/.
    path("", include("apps.web.urls")),
]
