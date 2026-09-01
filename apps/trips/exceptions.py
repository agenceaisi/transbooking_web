from rest_framework import status
from rest_framework.exceptions import APIException


class TripAlreadyCompleted(APIException):
    """Le voyage est deja termine : un report est refuse (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ce voyage est termine, il ne peut plus etre retarde."
    default_code = "trip_already_completed"
