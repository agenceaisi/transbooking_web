import factory
from factory.django import DjangoModelFactory

from apps.companies.models import (
    Company,
    CompanyNotificationSettings,
    CompanyPaymentMethod,
    CompanyStatus,
    PaymentMethodChoice,
)


class CompanyFactory(DjangoModelFactory):
    class Meta:
        model = Company

    name = factory.Sequence(lambda n: f"Compagnie {n}")
    city = "Ouagadougou"
    phone = factory.Sequence(lambda n: f"+2267{n:07d}")
    responsible_name = "Adama Sawadogo"
    responsible_phone = factory.Sequence(lambda n: f"+2265{n:07d}")
    status = CompanyStatus.ACTIVE
    commission_rate = 10


class CompanyPaymentMethodFactory(DjangoModelFactory):
    class Meta:
        model = CompanyPaymentMethod

    company = factory.SubFactory(CompanyFactory)
    method = PaymentMethodChoice.CASH
    is_active = True


class CompanyNotificationSettingsFactory(DjangoModelFactory):
    class Meta:
        model = CompanyNotificationSettings

    company = factory.SubFactory(CompanyFactory)
