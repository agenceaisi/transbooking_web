"""URL publiques du site.

Les adresses sont lisibles et stables : elles se partagent sur WhatsApp et se
referencient sur Google. ``/trajets/ouagadougou/bobo-dioulasso/`` dit ce qu'elle
montre ; un identifiant numerique ne dit rien et ne se retient pas.
"""
from django.urls import path

from . import dev, espace_views, views


app_name = "web"

urlpatterns = [
    path("", views.accueil, name="accueil"),
    # Connexion voyageur (session Django, distincte du JWT de l'API mobile).
    path("connexion/", espace_views.connexion, name="connexion"),
    path("inscription/", espace_views.inscription, name="inscription"),
    path("deconnexion/", espace_views.deconnexion, name="deconnexion"),
    # Espace voyageur connecte — module voyageur (12 ecrans).
    path("espace/", espace_views.tableau_de_bord, name="espace-tableau-de-bord"),
    path("espace/voyage/<int:pk>/", espace_views.voyage, name="espace-voyage"),
    path(
        "espace/voyage/<int:pk>/reserver/",
        espace_views.reserver,
        name="espace-reserver",
    ),
    path(
        "espace/reservations/<int:pk>/paiement/",
        espace_views.paiement,
        name="espace-paiement",
    ),
    path("espace/paiements/<int:pk>/recu/", espace_views.recu, name="espace-recu"),
    path("espace/reservations/", espace_views.reservations, name="espace-reservations"),
    path(
        "espace/reservations/<str:ticket_number>/",
        espace_views.billet,
        name="espace-billet",
    ),
    path("espace/bagages/", espace_views.bagages, name="espace-bagages"),
    path("espace/reclamations/", espace_views.reclamations, name="espace-reclamations"),
    path(
        "espace/reclamations/nouvelle/",
        espace_views.nouvelle_reclamation,
        name="espace-nouvelle-reclamation",
    ),
    path("espace/voyages/<int:trip_pk>/avis/", espace_views.avis, name="espace-avis"),
    path("espace/signalement/", espace_views.signalement, name="espace-signalement"),
    path("espace/profil/", espace_views.profil, name="espace-profil"),
    path(
        "trajets/<slug:origine>/<slug:destination>/",
        views.resultats,
        name="resultats",
    ),
    path("voyage/<int:pk>/", views.voyage, name="voyage"),
    path("voyage/<int:pk>/reserver/", views.reserver, name="reserver"),
    # Les etapes suivantes portent une signature : le numero de billet est
    # sequentiel, une URL non signee laisserait parcourir les billets des autres.
    path(
        "reservation/<int:pk>/<str:signature>/paiement/",
        views.paiement,
        name="paiement",
    ),
    path(
        "reservation/<int:pk>/<str:signature>/attente/",
        views.attente,
        name="attente",
    ),
    path(
        "reservation/<int:pk>/<str:signature>/statut/",
        views.statut,
        name="statut",
    ),
    path("billet/<int:pk>/<str:signature>/", views.billet, name="billet"),
    # Page operateur simulee. La route existe toujours — c'est la **vue** qui
    # refuse de repondre hors DEBUG. Un garde-fou porte par la table des URL
    # serait invisible aux tests, qui s'executent justement avec DEBUG a faux :
    # on ne verifierait jamais que la porte est bien fermee.
    path(
        "_dev/operateur/<int:payment_id>/",
        dev.operateur_simule,
        name="dev-operateur",
    ),
]
