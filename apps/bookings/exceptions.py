from rest_framework import status
from rest_framework.exceptions import APIException


class TripFull(APIException):
    """Le voyage n'a plus de place disponible (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ce voyage est complet."
    default_code = "trip_full"


class SeatTaken(APIException):
    """Le siege demande est deja attribue (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ce siege est deja attribue."
    default_code = "seat_taken"


class CancellationTooLate(APIException):
    """Annulation refusee : trop proche du depart (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = (
        "Annulation impossible a moins de 2h du depart. "
        "Contactez la compagnie."
    )
    default_code = "cancellation_too_late"


class TripUnavailable(APIException):
    """Le voyage est annule ou termine (HTTP 410)."""

    status_code = status.HTTP_410_GONE
    default_detail = "Ce voyage n'est plus ouvert a la reservation."
    default_code = "trip_unavailable"


class BookingNotCancellable(APIException):
    """Le billet est deja embarque ou rembourse : annulation refusee (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ce billet ne peut plus etre annule (deja embarque ou rembourse)."
    default_code = "booking_not_cancellable"
