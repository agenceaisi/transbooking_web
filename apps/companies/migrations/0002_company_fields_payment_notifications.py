import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

import utils.validators


class Migration(migrations.Migration):

    dependencies = [
        ("companies", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AlterModelOptions(
            name="company",
            options={
                "ordering": ["name"],
                "verbose_name": "Compagnie",
                "verbose_name_plural": "Compagnies",
            },
        ),
        migrations.AlterField(
            model_name="company",
            name="name",
            field=models.CharField(max_length=150, unique=True),
        ),
        migrations.AlterField(
            model_name="company",
            name="phone",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AlterField(
            model_name="company",
            name="status",
            field=models.CharField(
                choices=[
                    ("pending", "En attente"),
                    ("active", "Active"),
                    ("suspended", "Suspendue"),
                    ("rejected", "Rejetee"),
                ],
                default="pending",
                max_length=20,
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="sigle",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="company",
            name="description",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="company",
            name="logo",
            field=models.ImageField(blank=True, null=True, upload_to="companies/logos/"),
        ),
        migrations.AddField(
            model_name="company",
            name="banner",
            field=models.ImageField(blank=True, null=True, upload_to="companies/banners/"),
        ),
        migrations.AddField(
            model_name="company",
            name="primary_color",
            field=models.CharField(blank=True, max_length=7),
        ),
        migrations.AddField(
            model_name="company",
            name="welcome_message",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="company",
            name="responsible_phone",
            field=models.CharField(
                blank=True,
                max_length=30,
                validators=[utils.validators.validate_phone_bf],
            ),
        ),
        migrations.AddField(
            model_name="company",
            name="rccm",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="company",
            name="ifu",
            field=models.CharField(blank=True, max_length=50),
        ),
        migrations.AddField(
            model_name="company",
            name="rejection_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="company",
            name="suspension_reason",
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name="company",
            name="admin_user",
            field=models.OneToOneField(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="administered_company",
                to=settings.AUTH_USER_MODEL,
            ),
        ),
        migrations.CreateModel(
            name="CompanyPaymentMethod",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "method",
                    models.CharField(
                        choices=[
                            ("cash", "Especes"),
                            ("orange_money", "Orange Money"),
                            ("moov_money", "Moov Money"),
                            ("coris_money", "Coris Money"),
                            ("telecel_money", "Telecel Money"),
                            ("card", "Carte bancaire"),
                        ],
                        max_length=20,
                    ),
                ),
                ("is_active", models.BooleanField(default=True)),
                (
                    "company",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="payment_methods",
                        to="companies.company",
                    ),
                ),
            ],
            options={
                "ordering": ["method"],
                "unique_together": {("company", "method")},
            },
        ),
        migrations.CreateModel(
            name="CompanyNotificationSettings",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("sms_booking_confirmation", models.BooleanField(default=True)),
                ("sms_departure_reminder", models.BooleanField(default=True)),
                ("sms_parcel_arrival", models.BooleanField(default=True)),
                (
                    "company",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notification_settings",
                        to="companies.company",
                    ),
                ),
            ],
            options={
                "verbose_name": "Parametres de notification",
                "verbose_name_plural": "Parametres de notification",
            },
        ),
    ]
