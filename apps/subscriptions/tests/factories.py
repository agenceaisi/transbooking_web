from datetime import timedelta

import factory
from django.utils import timezone
from factory.django import DjangoModelFactory

from apps.companies.tests.factories import CompanyFactory
from apps.subscriptions.models import (
    Subscription,
    SubscriptionPlan,
    SubscriptionStatus,
)


class SubscriptionPlanFactory(DjangoModelFactory):
    class Meta:
        model = SubscriptionPlan

    name = factory.Sequence(lambda n: f"Forfait {n}")
    price = 50000
    duration_months = 1
    is_active = True


class SubscriptionFactory(DjangoModelFactory):
    class Meta:
        model = Subscription

    company = factory.SubFactory(CompanyFactory)
    plan = factory.SubFactory(SubscriptionPlanFactory)
    start_date = factory.LazyFunction(lambda: timezone.localdate() - timedelta(days=20))
    end_date = factory.LazyFunction(lambda: timezone.localdate() + timedelta(days=10))
    status = SubscriptionStatus.ACTIVE
    auto_renew = False
    expiry_reminder_sent = False
