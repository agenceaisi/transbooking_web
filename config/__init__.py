"""Expose the Celery app so shared_task autodiscovery works at Django startup."""
from .celery import app as celery_app


__all__ = ("celery_app",)
