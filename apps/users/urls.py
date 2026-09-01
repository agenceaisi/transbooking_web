from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyAgentViewSet,
    LogoutView,
    PasswordChangeView,
    TransBookingTokenObtainPairView,
    TransBookingTokenRefreshView,
    UserMeView,
    UserRegistrationView,
)


app_name = "users"

router = DefaultRouter()
router.register("company/agents", CompanyAgentViewSet, basename="company-agents")

urlpatterns = [
    path("auth/register/", UserRegistrationView.as_view(), name="register"),
    path("auth/login/", TransBookingTokenObtainPairView.as_view(), name="login"),
    path("auth/token/refresh/", TransBookingTokenRefreshView.as_view(), name="token_refresh"),
    path("auth/logout/", LogoutView.as_view(), name="logout"),
    path("auth/password/change/", PasswordChangeView.as_view(), name="password-change"),
    path("users/me/", UserMeView.as_view(), name="me"),
    path("", include(router.urls)),
]
