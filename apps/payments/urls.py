from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import AgentPaymentView, PaymentViewSet
from .webhooks import payment_webhook


app_name = "payments"

router = DefaultRouter()
router.register("payments", PaymentViewSet, basename="payments")

urlpatterns = [
    path("agent/payments/", AgentPaymentView.as_view(), name="agent-payments"),
    # Notification serveur-a-serveur de l'operateur. Publique et non
    # authentifiee : c'est la signature HMAC du corps qui fait foi.
    path(
        "webhooks/paiement/<str:provider>/",
        payment_webhook,
        name="payment-webhook",
    ),
    path("", include(router.urls)),
]
