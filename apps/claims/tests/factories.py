import factory
from factory.django import DjangoModelFactory

from apps.claims.models import Claim, ClaimStatus, ClaimType
from apps.companies.tests.factories import CompanyFactory
from apps.users.tests.factories import UserFactory


class ClaimFactory(DjangoModelFactory):
    class Meta:
        model = Claim

    company = factory.SubFactory(CompanyFactory)
    user = factory.SubFactory(UserFactory)
    claim_type = ClaimType.RETARD
    subject = "Bus parti en retard"
    description = "Le bus est parti avec deux heures de retard sans explication."
    status = ClaimStatus.SUBMITTED
