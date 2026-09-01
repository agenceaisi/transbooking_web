# Generated manually for PROMPT 03 (apps geography & vehicles).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vehicles", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle",
            name="seat_plan",
            field=models.JSONField(blank=True, default=dict),
        ),
        migrations.AlterModelOptions(
            name="vehicle",
            options={
                "ordering": ["registration"],
                "verbose_name": "Vehicule",
                "verbose_name_plural": "Vehicules",
            },
        ),
    ]
