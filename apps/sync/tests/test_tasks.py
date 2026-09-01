from datetime import timedelta

import pytest
from django.utils import timezone

from apps.sync.models import SyncLog
from apps.sync.tasks import cleanup_old_sync_logs

from .factories import SyncConflictFactory, SyncLogFactory


@pytest.mark.django_db
def test_cleanup_deletes_logs_older_than_30_days():
    old = SyncLogFactory()
    # created_at est auto_now_add : on le force dans le passe.
    SyncLog.objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(days=31)
    )
    recent = SyncLogFactory()

    deleted = cleanup_old_sync_logs()

    assert deleted >= 1
    assert not SyncLog.objects.filter(pk=old.pk).exists()
    assert SyncLog.objects.filter(pk=recent.pk).exists()


@pytest.mark.django_db
def test_cleanup_cascades_conflicts():
    conflict = SyncConflictFactory()
    log = conflict.sync_log
    SyncLog.objects.filter(pk=log.pk).update(
        created_at=timezone.now() - timedelta(days=40)
    )

    cleanup_old_sync_logs()

    assert not SyncLog.objects.filter(pk=log.pk).exists()
    assert type(conflict).objects.filter(pk=conflict.pk).count() == 0


@pytest.mark.django_db
def test_cleanup_is_idempotent():
    assert cleanup_old_sync_logs() == 0
