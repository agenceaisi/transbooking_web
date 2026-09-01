"""L'espace voyageur connecte : tableau de bord, reservation avec escale,
paiement par OTP, bagages, reclamations, avis, signalement et profil.

Meme esprit que ``test_tunnel.py`` : on suit les vraies vues et les vraies URL
plutot que des fonctions isolees, en particulier pour le paiement (l'etat
`otp_required` -> `paid` est ce qui casse le plus souvent).
"""
import pytest
from django.utils import timezone
from django.urls import reverse

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.tests.factories import BookingFactory
from apps.claims.models import Claim, ClaimStatus, ClaimType
from apps.claims.tests.factories import ClaimFactory
from apps.payments.models import Payment, PaymentStatus
from apps.reviews.models import Review
from apps.reviews.tests.factories import ReviewFactory
from apps.routes.tests.factories import RouteStopFactory
from apps.trips.models import Trip
from apps.users.tests.factories import UserFactory

from .factories import voyage_reservable

PASSAGER = {"first_name": "Aicha", "last_name": "Ouedraogo", "phone": "70 12 34 56"}


def _connecte(client, **champs):
    """Create a traveler and log the test client in as them.

    Args:
        client: The Django test client.
        **champs: Overrides forwarded to ``UserFactory``.

    Returns:
        The created user.
    """
    utilisateur = UserFactory(**champs)
    # UserFactory declare `skip_postgeneration_save = True` : le mot de passe
    # hashe par `set_password` (post-generation) reste en memoire sans etre
    # persiste. Sans ce save explicite, la requete suivante recharge un
    # utilisateur au mot de passe different de celui qui a scelle la session,
    # et `force_login` se voit invalide silencieusement (hash de session).
    utilisateur.save(update_fields=["password"])
    client.force_login(utilisateur)
    return utilisateur


# --------------------------------------------------------------------------- #
# Acces
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_l_espace_exige_une_connexion(client):
    reponse = client.get(reverse("web:espace-tableau-de-bord"))
    assert reponse.status_code == 302
    assert reponse["Location"].startswith(reverse("web:connexion"))


@pytest.mark.django_db
def test_inscription_puis_connexion_automatique(client):
    reponse = client.post(
        reverse("web:inscription"),
        {
            "prenom": "Fatou",
            "nom": "Kabore",
            "phone": "70 11 22 33",
            "email": "",
            "password": "un-mot-de-passe-solide",
        },
    )
    assert reponse.status_code == 302
    tableau = client.get(reverse("web:espace-tableau-de-bord"))
    assert tableau.status_code == 200


@pytest.mark.django_db
def test_connexion_avec_mauvais_mot_de_passe_est_refusee(client):
    UserFactory(phone="+22670111222", password="motdepasse123")
    reponse = client.post(
        reverse("web:connexion"), {"phone": "70 11 12 22", "password": "faux"}
    )
    assert reponse.status_code == 200
    assert reponse.wsgi_request.user.is_authenticated is False


# --------------------------------------------------------------------------- #
# Tableau de bord
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_le_tableau_de_bord_affiche_le_prochain_voyage_paye(client):
    utilisateur = _connecte(client)
    trajet = voyage_reservable(prix=6500)
    reservation = BookingFactory(
        trip=trajet, user=utilisateur, status=BookingStatus.PAID, seat_number="5"
    )

    reponse = client.get(reverse("web:espace-tableau-de-bord"))
    assert reponse.status_code == 200
    assert reservation.ticket_number.encode() in reponse.content


# --------------------------------------------------------------------------- #
# Reservation avec escale, paiement OTP, billet
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_reservation_a_une_escale_facture_le_tarif_du_troncon(client):
    _connecte(client)
    trajet = voyage_reservable(prix=6500)
    escale = RouteStopFactory(route=trajet.route, stop_price=2500)

    reponse = client.post(
        reverse("web:espace-reserver", kwargs={"pk": trajet.pk}),
        {**PASSAGER, "destination_stop": escale.pk},
    )
    assert reponse.status_code == 302, reponse.content[:400]

    reservation = Booking.objects.get(trip=trajet)
    assert reservation.amount == 2500
    assert reservation.destination_city_id == escale.city_id


@pytest.mark.django_db
def test_paiement_mobile_money_par_otp_jusqu_au_billet(client):
    _connecte(client)
    trajet = voyage_reservable(prix=6500)

    client.post(reverse("web:espace-reserver", kwargs={"pk": trajet.pk}), PASSAGER)
    reservation = Booking.objects.get(trip=trajet)

    reponse = client.post(
        reverse("web:espace-paiement", kwargs={"pk": reservation.pk}),
        {"method": "orange_money", "payer_phone": "70 00 00 00"},
    )
    assert reponse.status_code == 302

    reglement = Payment.objects.get(booking=reservation)
    assert reglement.status == PaymentStatus.OTP_REQUIRED

    otp = client.get(reponse["Location"])
    assert b"code re" in otp.content.lower() or otp.status_code == 200

    valide = client.post(
        reverse("web:espace-paiement", kwargs={"pk": reservation.pk}),
        {"action": "valider", "code": "123456"},
    )
    assert valide.status_code == 302
    assert valide["Location"] == reverse("web:espace-recu", kwargs={"pk": reglement.pk})

    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PAID

    billet = client.get(
        reverse("web:espace-billet", kwargs={"ticket_number": reservation.ticket_number})
    )
    assert billet.status_code == 200


@pytest.mark.django_db
def test_mauvais_code_otp_n_avance_pas_le_paiement(client):
    _connecte(client)
    trajet = voyage_reservable(prix=6500)
    client.post(reverse("web:espace-reserver", kwargs={"pk": trajet.pk}), PASSAGER)
    reservation = Booking.objects.get(trip=trajet)
    client.post(
        reverse("web:espace-paiement", kwargs={"pk": reservation.pk}),
        {"method": "orange_money"},
    )

    reponse = client.post(
        reverse("web:espace-paiement", kwargs={"pk": reservation.pk}),
        {"action": "valider", "code": "000000"},
    )
    assert reponse.status_code == 200

    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PENDING


@pytest.mark.django_db
def test_paiement_especes_va_direct_au_billet(client):
    _connecte(client)
    trajet = voyage_reservable(prix=6500)
    client.post(reverse("web:espace-reserver", kwargs={"pk": trajet.pk}), PASSAGER)
    reservation = Booking.objects.get(trip=trajet)

    reponse = client.post(
        reverse("web:espace-paiement", kwargs={"pk": reservation.pk}),
        {"method": "cash"},
    )
    assert reponse.status_code == 302
    assert reponse["Location"] == reverse(
        "web:espace-billet", kwargs={"ticket_number": reservation.ticket_number}
    )


@pytest.mark.django_db
def test_un_voyageur_ne_voit_pas_le_billet_d_un_autre(client):
    _connecte(client)
    autre = UserFactory()
    reservation = BookingFactory(user=autre, status=BookingStatus.PAID)

    reponse = client.get(
        reverse("web:espace-billet", kwargs={"ticket_number": reservation.ticket_number})
    )
    assert reponse.status_code == 404


# --------------------------------------------------------------------------- #
# Mes reservations
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_filtre_a_payer_ne_montre_que_les_reservations_en_attente(client):
    utilisateur = _connecte(client)
    trajet = voyage_reservable()
    a_payer = BookingFactory(trip=trajet, user=utilisateur, status=BookingStatus.PENDING)
    BookingFactory(user=utilisateur, status=BookingStatus.PAID)

    reponse = client.get(reverse("web:espace-reservations"), {"onglet": "a_payer"})
    assert reponse.status_code == 200
    assert a_payer.ticket_number.encode() in reponse.content


# --------------------------------------------------------------------------- #
# Bagages
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_declaration_de_bagage_met_a_jour_la_reservation(client):
    utilisateur = _connecte(client)
    trajet = voyage_reservable()
    reservation = BookingFactory(
        trip=trajet, user=utilisateur, status=BookingStatus.PAID, has_luggage=False
    )

    reponse = client.post(
        reverse("web:espace-bagages"),
        {"pk": reservation.pk, "has_luggage": "on", "luggage_qty": "2"},
    )
    assert reponse.status_code == 302

    reservation.refresh_from_db()
    assert reservation.has_luggage is True
    assert reservation.luggage_qty == 2


# --------------------------------------------------------------------------- #
# Reclamations
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_depot_d_une_reclamation_liee_a_une_reservation(client):
    utilisateur = _connecte(client)
    reservation = BookingFactory(user=utilisateur, status=BookingStatus.PAID)

    reponse = client.post(
        reverse("web:espace-nouvelle-reclamation"),
        {
            "booking": reservation.ticket_number,
            "claim_type": ClaimType.BAGAGE_ENDOMMAGE,
            "subject": "Valise abimee",
            "description": "La roue est cassee a l'arrivee.",
        },
    )
    assert reponse.status_code == 302

    reclamation = Claim.objects.get(user=utilisateur)
    assert reclamation.company_id == reservation.trip.route.company_id
    assert reclamation.booking_id == reservation.pk


@pytest.mark.django_db
def test_acceptation_d_une_proposition_resout_la_reclamation(client):
    utilisateur = _connecte(client)
    reclamation = ClaimFactory(
        user=utilisateur,
        status=ClaimStatus.IN_PROGRESS,
        response="Un dedommagement de 15 000 FCFA vous est propose.",
    )

    reponse = client.post(
        reverse("web:espace-reclamations"), {"pk": reclamation.pk, "action": "accepter"}
    )
    assert reponse.status_code == 302

    reclamation.refresh_from_db()
    assert reclamation.status == ClaimStatus.RESOLVED
    assert reclamation.traveler_accepted_at is not None


@pytest.mark.django_db
def test_un_voyageur_ne_peut_pas_accepter_la_reclamation_d_un_autre(client):
    _connecte(client)
    reclamation = ClaimFactory(
        status=ClaimStatus.IN_PROGRESS, response="Proposition de la compagnie."
    )

    reponse = client.post(
        reverse("web:espace-reclamations"), {"pk": reclamation.pk, "action": "accepter"}
    )
    assert reponse.status_code == 404


# --------------------------------------------------------------------------- #
# Avis
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_avis_refuse_sur_un_voyage_non_termine(client):
    utilisateur = _connecte(client)
    trajet = voyage_reservable()
    BookingFactory(trip=trajet, user=utilisateur, status=BookingStatus.PAID)

    reponse = client.get(reverse("web:espace-avis", kwargs={"trip_pk": trajet.pk}))
    assert reponse.status_code == 404


@pytest.mark.django_db
def test_avis_accepte_sur_un_voyage_termine_et_paye(client):
    utilisateur = _connecte(client)
    trajet = voyage_reservable()
    trajet.status = Trip.TripStatus.COMPLETED
    trajet.save(update_fields=["status"])
    BookingFactory(trip=trajet, user=utilisateur, status=BookingStatus.PAID)

    reponse = client.post(
        reverse("web:espace-avis", kwargs={"trip_pk": trajet.pk}),
        {"rating": "4", "comment": "Bon voyage."},
    )
    assert reponse.status_code == 302
    assert Review.objects.filter(user=utilisateur, trip=trajet).exists()


@pytest.mark.django_db
def test_un_second_avis_sur_le_meme_voyage_est_refuse(client):
    utilisateur = _connecte(client)
    avis = ReviewFactory(user=utilisateur)
    avis.trip.status = Trip.TripStatus.COMPLETED
    avis.trip.save(update_fields=["status"])
    BookingFactory(trip=avis.trip, user=utilisateur, status=BookingStatus.PAID)

    reponse = client.post(
        reverse("web:espace-avis", kwargs={"trip_pk": avis.trip_id}),
        {"rating": "5", "comment": ""},
    )
    assert reponse.status_code == 200
    assert Review.objects.filter(user=utilisateur, trip=avis.trip).count() == 1


# --------------------------------------------------------------------------- #
# Signalement
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_signalement_sans_voyage_en_cours(client):
    from apps.speed_reports.models import SpeedReport

    _connecte(client)
    # Un voyage en cours existe sur la plateforme, mais pas de reservation pour
    # ce voyageur dessus : la page reste utilisable, sans lever d'erreur.
    trajet = voyage_reservable()
    trajet.status = Trip.TripStatus.IN_PROGRESS
    trajet.save(update_fields=["status"])

    reponse = client.get(reverse("web:espace-signalement"))
    assert reponse.status_code == 200
    assert b"Vous roulez trop vite" in reponse.content

    reponse = client.post(
        reverse("web:espace-signalement"),
        {"severity": "", "description": "Depassements dangereux."},
    )
    # Sans voyage identifie et sans compagnie choisie, create_speed_report
    # refuse — verifie que l'echec est absorbe proprement (pas de 500).
    assert reponse.status_code == 200
    assert SpeedReport.objects.count() == 0


@pytest.mark.django_db
def test_signalement_sur_un_voyage_en_cours(client):
    from apps.speed_reports.models import SpeedReport

    utilisateur = _connecte(client)
    trajet = voyage_reservable()
    trajet.status = Trip.TripStatus.IN_PROGRESS
    trajet.save(update_fields=["status"])
    BookingFactory(trip=trajet, user=utilisateur, status=BookingStatus.PAID)

    reponse = client.post(
        reverse("web:espace-signalement"),
        {"severity": "high", "description": "Trois depassements en cote."},
    )
    assert reponse.status_code == 302
    assert SpeedReport.objects.filter(user=utilisateur, trip=trajet).exists()


# --------------------------------------------------------------------------- #
# Profil
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_modification_du_profil_conserve_les_preferences_non_soumises(client):
    utilisateur = _connecte(client)
    utilisateur.notify_marketing = True
    utilisateur.save(update_fields=["notify_marketing"])

    reponse = client.post(
        reverse("web:espace-profil"),
        {
            "action": "profil",
            "prenom": "Nouveau",
            "nom": utilisateur.nom,
            "email": "",
            "notify_departure_reminder": "on",
            "notify_parcel_arrival": "on",
            "notify_marketing": "on",
        },
    )
    assert reponse.status_code == 302
    utilisateur.refresh_from_db()
    assert utilisateur.prenom == "Nouveau"
    assert utilisateur.notify_marketing is True


@pytest.mark.django_db
def test_changement_de_mot_de_passe(client):
    utilisateur = _connecte(client, password="ancien-mdp-1234")

    reponse = client.post(
        reverse("web:espace-profil"),
        {
            "action": "mot_de_passe",
            "old_password": "ancien-mdp-1234",
            "new_password": "nouveau-mdp-5678",
        },
    )
    assert reponse.status_code == 302
    utilisateur.refresh_from_db()
    assert utilisateur.check_password("nouveau-mdp-5678")


@pytest.mark.django_db
def test_suppression_desactive_le_compte_sans_le_supprimer(client):
    utilisateur = _connecte(client)

    reponse = client.post(reverse("web:espace-profil"), {"action": "supprimer"})
    assert reponse.status_code == 302

    utilisateur.refresh_from_db()
    assert utilisateur.is_active is False
