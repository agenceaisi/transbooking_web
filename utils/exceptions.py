from django_ratelimit.exceptions import Ratelimited
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler


def custom_exception_handler(exc, context):
    """Map django-ratelimit's Ratelimited exception to an HTTP 429 response.

    DRF does not know about ``Ratelimited`` and would otherwise return a 500.

    Also merges an exception's ``extra_detail`` mapping into the response body
    when it exposes one. DRF coerces every scalar of an exception detail into a
    string ``ErrorDetail``; ``extra_detail`` lets an exception attach typed
    machine-readable context (e.g. ``{"attempts_remaining": 2}``) without
    changing the error format.

    Args:
        exc: The exception raised while processing the request.
        context: The DRF context dict (view, request, args, kwargs).

    Returns:
        An HTTP 429 response for rate-limit hits, otherwise DRF's default
        handling for the exception.
    """
    if isinstance(exc, Ratelimited):
        return Response(
            {"detail": "Trop de tentatives. Reessayez plus tard."},
            status=status.HTTP_429_TOO_MANY_REQUESTS,
        )

    response = drf_exception_handler(exc, context)

    extra_detail = getattr(exc, "extra_detail", None)
    if extra_detail and response is not None and isinstance(response.data, dict):
        response.data.update(extra_detail)
    return response
