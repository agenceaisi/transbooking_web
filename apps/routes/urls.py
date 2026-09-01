from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import RouteStopViewSet, RouteViewSet


app_name = "routes"

router = DefaultRouter()
router.register("company/routes", RouteViewSet, basename="company-routes")

stop_list = RouteStopViewSet.as_view({"get": "list", "post": "create"})
stop_detail = RouteStopViewSet.as_view(
    {"get": "retrieve", "patch": "partial_update", "delete": "destroy"}
)

urlpatterns = [
    path(
        "company/routes/<int:route_pk>/stops/",
        stop_list,
        name="company-route-stops",
    ),
    path(
        "company/routes/<int:route_pk>/stops/<int:pk>/",
        stop_detail,
        name="company-route-stop-detail",
    ),
    path("", include(router.urls)),
]
