# Generated manually for PROMPT 03 (apps geography & vehicles).
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("geography", "0001_initial"),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="city",
            options={
                "ordering": ["name"],
                "verbose_name": "Ville",
                "verbose_name_plural": "Villes",
            },
        ),
        migrations.AlterModelOptions(
            name="station",
            options={
                "ordering": ["name"],
                "verbose_name": "Gare",
                "verbose_name_plural": "Gares",
            },
        ),
    ]
