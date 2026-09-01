import pytest
from rest_framework.exceptions import ValidationError

from apps.bookings.tests.factories import BookingFactory
from apps.claims.models import ClaimStatus, ClaimType
from apps.claims.services import (
    accept_claim_response,
    close_claim,
    create_claim,
    escalate_claim,
    respond_to_claim,
)
from apps.users.tests.factories import UserFactory

from .factories import ClaimFactory


@pytest.mark.django_db
def test_create_claim_deduces_company_from_booking():
    booking = BookingFactory()
    claim = create_claim(
        {
            "booking": booking,
            "claim_type": ClaimType.RETARD,
            "subject": "Retard important",
            "description": "Le bus est parti avec deux heures de retard.",
        },
        booking.user,
    )
    assert claim.company_id == booking.trip.route.company_id


@pytest.mark.django_db
def test_create_claim_rejects_a_booking_owned_by_someone_else():
    booking = BookingFactory()
    autre = UserFactory()
    with pytest.raises(ValidationError):
        create_claim(
            {
                "booking": booking,
                "claim_type": ClaimType.RETARD,
                "subject": "Retard important",
                "description": "...",
            },
            autre,
        )


@pytest.mark.django_db
def test_create_claim_requires_a_booking_or_a_company():
    with pytest.raises(ValidationError):
        create_claim(
            {"claim_type": ClaimType.AUTRE, "subject": "Sujet", "description": "..."},
            UserFactory(),
        )


@pytest.mark.django_db
def test_accept_claim_response_resolves_the_claim():
    claim = ClaimFactory(status=ClaimStatus.IN_PROGRESS, response="Dedommagement propose.")
    accept_claim_response(claim, claim.user)
    assert claim.status == ClaimStatus.RESOLVED
    assert claim.traveler_accepted_at is not None


@pytest.mark.django_db
def test_accept_claim_response_rejects_another_traveler():
    claim = ClaimFactory(status=ClaimStatus.IN_PROGRESS, response="Dedommagement propose.")
    with pytest.raises(ValidationError):
        accept_claim_response(claim, UserFactory())


@pytest.mark.django_db
def test_accept_claim_response_requires_a_pending_response():
    claim = ClaimFactory(status=ClaimStatus.SUBMITTED, response="")
    with pytest.raises(ValidationError):
        accept_claim_response(claim, claim.user)


@pytest.mark.django_db
def test_respond_rejects_invalid_status():
    claim = ClaimFactory()
    with pytest.raises(ValidationError):
        respond_to_claim(claim, response="ok", status="submitted", responder=None)


@pytest.mark.django_db
def test_escalate_then_close_keeps_response_timestamp():
    claim = ClaimFactory(status=ClaimStatus.SUBMITTED)
    escalate_claim(claim)
    assert claim.status == ClaimStatus.ESCALATED

    close_claim(claim)
    assert claim.status == ClaimStatus.CLOSED
    # Cloture directe sans reponse prealable => horodatage de cloture pose.
    assert claim.responded_at is not None
