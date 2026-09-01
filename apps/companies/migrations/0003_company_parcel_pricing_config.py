from django.db import migrations, models

import apps.companies.models


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0002_company_fields_payment_notifications"),
    ]

    operations = [
        migrations.AddField(
            model_name="company",
            name="parcel_pricing_config",
            field=models.JSONField(
                default=apps.companies.models.default_parcel_pricing_config
            ),
        ),
    ]
