from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    OfflineDataView,
    SyncConflictListView,
    SyncLogViewSet,
    SyncView,
)


app_name = "sync"

router = DefaultRouter()
router.register("agent/sync/logs", SyncLogViewSet, basename="agent-sync-logs")

urlpatterns = [
    path("agent/sync/", SyncView.as_view(), name="agent-sync"),
    path(
        "agent/sync/conflicts/",
        SyncConflictListView.as_view(),
        name="agent-sync-conflicts",
    ),
    path("agent/offline-data/", OfflineDataView.as_view(), name="agent-offline-data"),
    path("", include(router.urls)),
]
