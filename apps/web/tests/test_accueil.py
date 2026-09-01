"""La page d'accueil publique : departs reels, recherche, colis.

Comme pour le tunnel (cf. test_tunnel.py), ces tests passent par la vraie vue
et la vraie base — la page d'accueil n'a de valeur que si les chiffres qu'elle
affiche viennent reellement de la base, jamais de donnees inventees dans le
gabarit.
"""
import pytest
from django.urls import reverse

from apps.parcels.tests.factories import ParcelFactory
from apps.routes.tests.factories import RouteFactory

from .factories import voyage_reservable


@pytest.mark.django_db
def test_accueil_liste_les_departs_de_la_ville_de_reference(client):
    trajet = voyage_reservable(prix=7500)

    reponse = client.get(reverse("web:accueil"))

    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert trajet.route.destination_city.name in contenu
    assert "7\xa0500" in contenu


@pytest.mark.django_db
def test_recherche_valide_redirige_vers_les_resultats(client):
    voyage_reservable()

    reponse = client.get(
        reverse("web:accueil"),
        {"origine": "Ouagadougou", "destination": "Bobo-Dioulasso"},
    )

    assert reponse.status_code == 302
    assert reponse["Location"] == reverse(
        "web:resultats",
        kwargs={"origine": "ouagadougou", "destination": "bobo-dioulasso"},
    )


@pytest.mark.django_db
def test_recherche_ville_inconnue_affiche_un_message_et_reste_sur_l_accueil(client):
    reponse = client.get(
        reverse("web:accueil"),
        {"origine": "Villequinexistepas", "destination": "Bobo-Dioulasso"},
        follow=True,
    )

    assert reponse.status_code == 200
    assert "introuvable" in reponse.content.decode()


@pytest.mark.django_db
def test_suivi_colis_affiche_le_statut_reel(client):
    colis = ParcelFactory(tracking_number="COL2026009999")

    reponse = client.get(reverse("web:accueil"), {"suivi": "col2026009999"})

    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert colis.tracking_number in contenu
    assert colis.destination_city.name in contenu


@pytest.mark.django_db
def test_suivi_colis_introuvable_le_signale(client):
    reponse = client.get(reverse("web:accueil"), {"suivi": "COL2026000000"})

    assert reponse.status_code == 200
    assert "Aucun colis ne correspond" in reponse.content.decode()


@pytest.mark.django_db
def test_estimation_colis_calcule_un_tarif_reel(client):
    route = RouteFactory(distance_km=50)  # tranche courte : sous 100 km
    config = route.company.parcel_pricing_config
    tarif_attendu = 4 * config["tier_short"]["price_per_kg"] + config["tier_short"]["fixed_fee"]

    reponse = client.get(
        reverse("web:accueil"),
        {
            "colis_origine": route.origin_city.name,
            "colis_destination": route.destination_city.name,
            "colis_poids": "4",
        },
    )

    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert f"{int(tarif_attendu):,}".replace(",", "\xa0") in contenu
