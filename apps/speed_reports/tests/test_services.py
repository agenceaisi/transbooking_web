import pytest
from rest_framework.exceptions import ValidationError

from apps.speed_reports.models import SpeedReportStatus
from apps.speed_reports.services import create_speed_report, update_status
from apps.trips.tests.factories import TripFactory
from apps.users.tests.factories import UserFactory

from .factories import SpeedReportFactory


@pytest.mark.django_db
def test_create_resolves_company_from_trip():
    user = UserFactory()
    trip = TripFactory()
    report = create_speed_report({"trip": trip}, user=user)
    assert report.company_id == trip.route.company_id
    assert report.reported_at is not None


@pytest.mark.django_db
def test_create_requires_company_or_trip():
    user = UserFactory()
    with pytest.raises(ValidationError):
        create_speed_report({"estimated_speed": 100}, user=user)


@pytest.mark.django_db
def test_update_status_rejects_invalid():
    report = SpeedReportFactory()
    with pytest.raises(ValidationError):
        update_status(report, "unknown")
    update_status(report, SpeedReportStatus.CLOSED)
    assert report.status == SpeedReportStatus.CLOSED
