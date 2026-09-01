"""Fixtures partagees par les tests d'integration.

- ``api_client`` : client DRF non authentifie.
- ``sms_outbox`` : espionne tous les ``send_sms`` (services et taches Celery)
  et collecte les messages envoyes, sans jamais toucher un vrai fournisseur.
  Actif automatiquement pour verifier les envois SMS de bout en bout.
- ``_clear_cache`` : vide le cache entre les tests (les listes publiques
  utilisent ``cache_page`` sur un backend LocMem partage).
"""
import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

# Tous les modules qui font ``from utils.sms import send_sms`` gardent leur
# propre reference : il faut donc patcher chacun d'eux, pas seulement la source.
_SMS_TARGETS = [
    "apps.bookings.services.send_sms",
    "apps.bookings.tasks.send_sms",
    "apps.parcels.services.send_sms",
    "apps.parcels.tasks.send_sms",
    "apps.payments.services.send_sms",
    "apps.companies.services.send_sms",
]


class _SmsOutbox(list):
    """Liste des SMS captures, avec des helpers de recherche."""

    def to(self, phone: str) -> list:
        """Return the messages sent to ``phone``."""
        return [message for number, message in self if number == phone]

    def sent_to(self, phone: str) -> bool:
        """Whether at least one message was sent to ``phone``."""
        return any(number == phone for number, _ in self)


@pytest.fixture
def api_client() -> APIClient:
    return APIClient()


@pytest.fixture(autouse=True)
def sms_outbox(monkeypatch) -> _SmsOutbox:
    """Capture every outgoing SMS across services and Celery tasks."""
    outbox = _SmsOutbox()

    def _capture(phone, message):
        outbox.append((phone, message))

    for target in _SMS_TARGETS:
        monkeypatch.setattr(target, _capture)
    return outbox


@pytest.fixture(autouse=True)
def _clear_cache():
    cache.clear()
    yield
    cache.clear()
