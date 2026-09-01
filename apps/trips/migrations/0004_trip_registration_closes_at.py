from django.db import migrations, models


def backfill_registration_closes_at(apps, schema_editor):
    Trip = apps.get_model("trips", "Trip")
    Trip.objects.filter(registration_closes_at__isnull=True).update(
        registration_closes_at=models.F("departure_time")
    )


class Migration(migrations.Migration):

    dependencies = [
        ('trips', '0003_trip_driver_phone'),
    ]

    operations = [
        migrations.AddField(
            model_name='trip',
            name='registration_closes_at',
            field=models.DateTimeField(null=True),
        ),
        migrations.RunPython(
            backfill_registration_closes_at, migrations.RunPython.noop
        ),
        migrations.AlterField(
            model_name='trip',
            name='registration_closes_at',
            field=models.DateTimeField(),
        ),
    ]
