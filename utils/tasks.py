"""Helpers communs aux taches Celery.

Toutes les taches asynchrones du projet doivent etre idempotentes et ne jamais
laisser remonter d'exception au worker : une erreur est journalisee (Sentry en
production, console en dev) puis avalee. Le decorateur ``log_task_errors``
centralise ce comportement.
"""
import functools
import logging
from typing import Any, Callable

logger = logging.getLogger("tasks")


def report_exception(message: str, exc: Exception) -> None:
    """Log an exception and forward it to Sentry when available.

    Args:
        message: Human-readable context for the failure.
        exc: The caught exception instance.
    """
    logger.exception(message)
    try:
        import sentry_sdk  # noqa: WPS433 (import optionnel)

        sentry_sdk.capture_exception(exc)
    except ImportError:
        # Sentry n'est pas installe en dev : la trace console suffit.
        pass


def log_task_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap a Celery task body so any exception is logged instead of raised.

    Keeps the worker healthy and the task idempotent-friendly: a failed run is
    reported (Sentry/console) and returns ``None`` rather than crashing.

    Args:
        func: The task function to protect.

    Returns:
        The wrapped function.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return func(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 (capture volontaire et journalisee)
            report_exception(f"Echec de la tache {func.__name__}", exc)
            return None

    return wrapper
