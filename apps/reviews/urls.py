from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CompanyReviewViewSet,
    PublicTestimonialListView,
    ReviewViewSet,
    SuperReviewViewSet,
)


app_name = "reviews"

router = DefaultRouter()
router.register("reviews", ReviewViewSet, basename="reviews")
router.register("company/reviews", CompanyReviewViewSet, basename="company-reviews")
router.register("super/reviews", SuperReviewViewSet, basename="super-reviews")

urlpatterns = [
    path(
        "public/testimonials/",
        PublicTestimonialListView.as_view(),
        name="public-testimonials",
    ),
    path("", include(router.urls)),
]
