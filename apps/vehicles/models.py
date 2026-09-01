from django.db import models

from utils.models import TimeStampedModel


class Vehicle(TimeStampedModel):
    class VehicleStatus(models.TextChoices):
        ACTIVE = "active", "Active"
        MAINTENANCE = "maintenance", "Maintenance"
        INACTIVE = "inactive", "Inactive"

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="vehicles",
    )
    registration = models.CharField(max_length=50, unique=True)
    brand = models.CharField(max_length=50, blank=True)
    model = models.CharField(max_length=50, blank=True)
    vehicle_type = models.CharField(max_length=30, blank=True)
    total_seats = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=VehicleStatus.choices,
        default=VehicleStatus.ACTIVE,
    )
    # Plan des sieges stocke en JSON.
    # Format : {"layout": [[1, 2], [3, 4], ...], "reserved": [0]}
    #   - layout   : liste de rangees, chaque rangee = liste de numeros de siege
    #   - reserved : numeros de siege non commercialisables (chauffeur, hotesse...)
    seat_plan = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["registration"]
        verbose_name = "Vehicule"
        verbose_name_plural = "Vehicules"

    def __str__(self) -> str:
        return self.registration
