import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.speed_reports.models import SpeedReport, SpeedReportStatus
from apps.users.tests.factories import UserFactory


class SpeedReportFactory(DjangoModelFactory):
    class Meta:
        model = SpeedReport

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(UserFactory)
    estimated_speed = 120
    description = "Le chauffeur roulait bien au-dela de la limite autorisee."
    reported_at = factory.LazyFunction(timezone.now)
    status = SpeedReportStatus.PENDING
