from django.db import models
from django.utils.text import slugify

from utils.models import TimeStampedModel


class City(TimeStampedModel):
    name = models.CharField(max_length=100)
    region = models.CharField(max_length=100, blank=True)
    # Identifiant lisible utilise dans les URL publiques :
    # /trajets/ouagadougou-bobo-dioulasso/. C'est la cle de l'acquisition
    # organique — une URL porteuse de sens se partage et se referencie, un
    # identifiant numerique non.
    slug = models.SlugField(max_length=120, unique=True, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Ville"
        verbose_name_plural = "Villes"

    def save(self, *args, **kwargs):
        # Le slug se derive du nom a la creation, puis ne bouge plus : une URL
        # publique deja indexee ne doit pas changer parce qu'on a corrige une
        # faute de frappe dans le nom d'une ville.
        if not self.slug:
            self.slug = slugify(self.name)[:120]
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class Station(TimeStampedModel):
    company = models.ForeignKey(
        "companies.Company",
        on_delete=models.CASCADE,
        related_name="stations",
    )
    city = models.ForeignKey(City, on_delete=models.PROTECT, related_name="stations")
    name = models.CharField(max_length=150)
    address = models.TextField(blank=True)
    localisation = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Gare"
        verbose_name_plural = "Gares"

    def __str__(self) -> str:
        return self.name
