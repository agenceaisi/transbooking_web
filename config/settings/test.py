"""Test settings for TransBooking BF."""
import tempfile

from .base import *  # noqa: F403
from .base import REST_FRAMEWORK


# Les uploads de test (pieces jointes de reclamation) sont ecrits dans un dossier
# temporaire, jamais dans le `media/` du depot.
MEDIA_ROOT = tempfile.mkdtemp(prefix="transbooking-test-media-")

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": ":memory:",
    }
}

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

# Pas de Redis en CI/test : cache mémoire local.
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
    }
}

# Throttling désactivé pour éviter des tests flaky.
REST_FRAMEWORK = {
    **REST_FRAMEWORK,
    "DEFAULT_THROTTLE_CLASSES": [],
    "DEFAULT_THROTTLE_RATES": {},
}

# Celery exécute les tâches en synchrone (pas de broker en test).
CELERY_TASK_ALWAYS_EAGER = True
CELERY_TASK_EAGER_PROPAGATES = True

# Rate limiting désactivé en test pour éviter des résultats flaky.
RATELIMIT_ENABLE = False
