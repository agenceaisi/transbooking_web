from datetime import timedelta

import pytest
from django.utils import timezone

from apps.claims.models import ClaimStatus
from apps.claims.services import annotated_claims

from .factories import ClaimFactory


@pytest.mark.django_db
def test_overdue_flag_set_after_48h():
    old = ClaimFactory(status=ClaimStatus.SUBMITTED)
    # Contourne auto_now_add pour simuler une reclamation ancienne.
    type(old).objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(hours=49)
    )

    claim = annotated_claims().get(pk=old.pk)
    assert claim.is_overdue is True


@pytest.mark.django_db
def test_recent_claim_is_not_overdue():
    claim = ClaimFactory(status=ClaimStatus.SUBMITTED)
    annotated = annotated_claims().get(pk=claim.pk)
    assert annotated.is_overdue is False


@pytest.mark.django_db
def test_resolved_old_claim_is_not_overdue():
    old = ClaimFactory(status=ClaimStatus.RESOLVED)
    type(old).objects.filter(pk=old.pk).update(
        created_at=timezone.now() - timedelta(hours=72)
    )
    annotated = annotated_claims().get(pk=old.pk)
    # Seules les reclamations encore « submitted » peuvent etre en retard.
    assert annotated.is_overdue is False
