from django.db import models

from utils.models import TimeStampedModel


class Route(TimeStampedModel):
    """Trajet commercial d'une compagnie entre deux villes."""

    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="routes",
    )
    origin_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="routes_departing",
    )
    destination_city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="routes_arriving",
    )
    origin_station = models.ForeignKey(
        "geography.Station",
        on_delete=models.SET_NULL,
        related_name="routes_origin",
        null=True,
        blank=True,
    )
    destination_station = models.ForeignKey(
        "geography.Station",
        on_delete=models.SET_NULL,
        related_name="routes_destination",
        null=True,
        blank=True,
    )
    # Distance utilisee notamment pour le calcul du tarif colis (tranches).
    distance_km = models.DecimalField(max_digits=7, decimal_places=2, default=0)
    base_price = models.DecimalField(max_digits=10, decimal_places=2)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["origin_city__name", "destination_city__name"]
        verbose_name = "Trajet"
        verbose_name_plural = "Trajets"

    def __str__(self) -> str:
        return f"{self.origin_city} -> {self.destination_city}"


class RouteStop(TimeStampedModel):
    """Escale intermediaire d'un trajet, avec son prix partiel."""

    route = models.ForeignKey(
        Route,
        on_delete=models.CASCADE,
        related_name="stops",
    )
    city = models.ForeignKey(
        "geography.City",
        on_delete=models.PROTECT,
        related_name="route_stops",
    )
    stop_order = models.PositiveIntegerField()
    # Nom affiche de l'arret (peut differer du nom officiel de la ville).
    display_name = models.CharField(max_length=150, blank=True)
    stop_price = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["stop_order"]
        unique_together = ("route", "stop_order")
        verbose_name = "Escale"
        verbose_name_plural = "Escales"

    def __str__(self) -> str:
        return f"{self.route} - escale {self.stop_order} ({self.city})"
