from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import MessageViewSet, TripPassengerListView


app_name = "messaging"

router = DefaultRouter()
router.register("messages", MessageViewSet, basename="messages")

urlpatterns = [
    path(
        "agent/trips/<int:trip_id>/passenger-list/",
        TripPassengerListView.as_view(),
        name="trip-passenger-list",
    ),
    path("", include(router.urls)),
]
