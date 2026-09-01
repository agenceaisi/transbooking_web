"""Ajoute un identifiant lisible aux villes, pour les URL publiques.

Trois temps, dans cet ordre : on cree le champ sans contrainte d'unicite, on
remplit, puis on impose l'unicite. Creer directement un champ unique sur une
table deja peuplee echoue des la deuxieme ligne.
"""
from django.db import migrations, models
from django.utils.text import slugify


def remplir_slugs(apps, schema_editor):
    """Derive a slug from each city name, de-duplicating on collision."""
    City = apps.get_model("geography", "City")
    vus = set()
    for ville in City.objects.all().order_by("pk"):
        base = slugify(ville.name)[:110] or f"ville-{ville.pk}"
        slug = base
        suffixe = 2
        while slug in vus:
            slug = f"{base}-{suffixe}"
            suffixe += 1
        vus.add(slug)
        ville.slug = slug
        ville.save(update_fields=["slug"])


def vider_slugs(apps, schema_editor):
    """Reverse operation: nothing to undo, the column is dropped."""


class Migration(migrations.Migration):

    dependencies = [("geography", "0002_city_station_options")]

    operations = [
        migrations.AddField(
            model_name="city",
            name="slug",
            field=models.SlugField(blank=True, db_index=False, default="", max_length=120),
            preserve_default=False,
        ),
        migrations.RunPython(remplir_slugs, vider_slugs),
        migrations.AlterField(
            model_name="city",
            name="slug",
            field=models.SlugField(blank=True, max_length=120, unique=True),
        ),
    ]
