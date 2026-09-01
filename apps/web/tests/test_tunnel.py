"""Le tunnel de reservation, de la recherche au billet paye.

Ces tests ne verifient pas des fonctions isolees : ils suivent le chemin qu'un
voyageur emprunte, en passant par les vraies vues, les vraies URL et le vrai
webhook. C'est le seul niveau ou les pannes qui coutent de l'argent se voient —
une notification perdue ou doublee ne se manifeste jamais dans un test unitaire.

Le scenario rejoue par l'operateur simule se lit dans les deux derniers
chiffres du prix (cf. ``MockRedirectProvider``), ce qui permet de commander la
panne depuis la fabrique.
"""
import pytest
from django.test import override_settings
from django.urls import reverse

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking
from apps.payments.models import Payment, PaymentStatus, PaymentWebhook
from apps.payments.reconciliation import reconcilier
from apps.web.tokens import jeton

from .factories import voyage_reservable

#: Reglages communs : bac a sable en parcours par redirection, secret de
#: notification connu, page operateur simulee accessible.
SANDBOX = override_settings(
    PAYMENT_SANDBOX=True,
    PAYMENT_SANDBOX_FLOW="redirect",
    PAYMENT_WEBHOOK_SECRET="secret-de-test",
    SITE_BASE_URL="http://testserver",
    DEBUG=True,
)

PASSAGER = {
    "first_name": "Aicha",
    "last_name": "Ouedraogo",
    "phone": "70 12 34 56",
}


def _reserver(client, trajet):
    """Fill the passenger form and follow through to the payment step.

    Args:
        client: The Django test client.
        trajet: The trip being booked.

    Returns:
        The created booking.
    """
    reponse = client.post(reverse("web:reserver", kwargs={"pk": trajet.pk}), PASSAGER)
    assert reponse.status_code == 302, reponse.content[:400]
    return Booking.objects.get(trip=trajet)


def _payer(client, reservation):
    """Choose Orange Money and follow the redirect to the operator page.

    Args:
        client: The Django test client.
        reservation: The booking to pay.

    Returns:
        The opened payment.
    """
    url = reverse(
        "web:paiement",
        kwargs={"pk": reservation.pk, "signature": jeton(reservation.pk)},
    )
    reponse = client.post(url, {"method": "orange_money", "payer_phone": ""})
    assert reponse.status_code == 302
    assert "/_dev/operateur/" in reponse["Location"]
    return Payment.objects.get(booking=reservation)


def _valider_chez_operateur(client, reglement):
    """Press « Valider » on the simulated operator page.

    Args:
        client: The Django test client.
        reglement: The payment being settled.

    Returns:
        The HTTP response.
    """
    return client.post(
        reverse("web:dev-operateur", kwargs={"payment_id": reglement.pk}),
        {"decision": "valider"},
    )


# --------------------------------------------------------------------------- #
# Le chemin nominal
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
@SANDBOX
def test_le_tunnel_mene_du_trajet_au_billet_paye(client):
    trajet = voyage_reservable(prix=6500, places=30)

    reservation = _reserver(client, trajet)
    assert reservation.status == BookingStatus.PENDING
    assert reservation.phone == "+22670123456"  # normalise a la saisie
    trajet.refresh_from_db()
    assert trajet.available_seats == 29  # la place est retenue des la creation

    reglement = _payer(client, reservation)
    assert reglement.status == PaymentStatus.OTP_REQUIRED
    assert reglement.provider_ref  # enregistre avant de repondre au navigateur

    _valider_chez_operateur(client, reglement)

    reservation.refresh_from_db()
    reglement.refresh_from_db()
    assert reglement.status == PaymentStatus.PAID
    assert reservation.status == BookingStatus.PAID

    billet = client.get(
        reverse(
            "web:billet",
            kwargs={"pk": reservation.pk, "signature": jeton(reservation.pk)},
        )
    )
    assert billet.status_code == 200
    assert reservation.ticket_number.encode() in billet.content


@pytest.mark.django_db
@SANDBOX
def test_reserver_un_siege_deja_pris_reaffiche_le_formulaire(client):
    """Un siege deja attribue ne doit jamais faire planter la vue (500)."""
    trajet = voyage_reservable(prix=6500, places=30)
    create_booking(
        {
            "trip": trajet,
            "first_name": "Issa",
            "last_name": "Sawadogo",
            "phone": "+22670000000",
            "seat_number": "12",
            "amount": trajet.price,
            "status": BookingStatus.PAID,
        }
    )

    reponse = client.post(
        reverse("web:reserver", kwargs={"pk": trajet.pk}),
        {**PASSAGER, "seat_number": "12"},
    )

    assert reponse.status_code == 409
    assert not Booking.objects.filter(phone="+22670123456").exists()


@pytest.mark.django_db
@SANDBOX
def test_la_page_de_resultats_liste_les_departs(client):
    trajet = voyage_reservable(prix=6500)

    reponse = client.get(
        reverse(
            "web:resultats",
            kwargs={"origine": "ouagadougou", "destination": "bobo-dioulasso"},
        ),
        {"date": trajet.departure_time.astimezone().date().isoformat()},
    )

    assert reponse.status_code == 200
    contenu = reponse.content.decode()
    assert "Gare Ouaga-Inter" in contenu
    # Montant groupe par une espace insecable, sans decimales.
    assert "6 500" in contenu
    assert reverse("web:voyage", kwargs={"pk": trajet.pk}) in contenu


# --------------------------------------------------------------------------- #
# Les pannes qui coutent de l'argent
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
@SANDBOX
def test_une_notification_perdue_est_rattrapee_par_la_reconciliation(client):
    """Le payeur est debite, l'operateur ne previent jamais.

    Sans la tache de reconciliation, ce client a paye un billet qu'il n'a
    jamais recu. C'est la panne la plus couteuse du systeme.
    """
    trajet = voyage_reservable(prix=6503)  # ...03 -> notification perdue
    reservation = _reserver(client, trajet)
    reglement = _payer(client, reservation)

    _valider_chez_operateur(client, reglement)

    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PENDING
    assert PaymentWebhook.objects.count() == 0  # aucune notification emise

    # La reconciliation ne regarde que les transactions assez anciennes : on
    # antidate plutot que d'attendre trois minutes.
    Payment.objects.filter(pk=reglement.pk).update(
        created_at=reglement.created_at.replace(year=reglement.created_at.year - 1)
    )
    comptes = reconcilier()

    assert comptes["rattrapes"] == 1
    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PAID


@pytest.mark.django_db
@SANDBOX
def test_une_notification_doublee_n_emet_qu_un_billet(client):
    """L'operateur reemet faute d'avoir vu notre 200. Un seul billet doit sortir."""
    trajet = voyage_reservable(prix=6504)  # ...04 -> notification doublee
    reservation = _reserver(client, trajet)
    reglement = _payer(client, reservation)

    _valider_chez_operateur(client, reglement)

    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PAID
    # Deux envois, une seule notification retenue : la contrainte d'unicite sur
    # l'empreinte du corps fait l'idempotence.
    assert PaymentWebhook.objects.count() == 1
    assert Payment.objects.filter(booking=reservation).count() == 1


@pytest.mark.django_db
@SANDBOX
def test_un_montant_divergent_ne_confirme_pas_le_paiement(client):
    """L'operateur annonce un autre montant : on n'emet rien, on alerte."""
    trajet = voyage_reservable(prix=6505)  # ...05 -> montant divergent
    reservation = _reserver(client, trajet)
    reglement = _payer(client, reservation)

    _valider_chez_operateur(client, reglement)

    reservation.refresh_from_db()
    reglement.refresh_from_db()
    assert reservation.status == BookingStatus.PENDING
    assert reglement.status != PaymentStatus.PAID
    # La notification est bien arrivee et journalisee : c'est son contenu qu'on
    # refuse, pas sa reception.
    assert PaymentWebhook.objects.count() == 1


@pytest.mark.django_db
@SANDBOX
def test_le_payeur_qui_renonce_laisse_la_reservation_en_attente(client):
    trajet = voyage_reservable(prix=6500)
    reservation = _reserver(client, trajet)
    reglement = _payer(client, reservation)

    client.post(
        reverse("web:dev-operateur", kwargs={"payment_id": reglement.pk}),
        {"decision": "annuler"},
    )

    reservation.refresh_from_db()
    reglement.refresh_from_db()
    assert reglement.status == PaymentStatus.FAILED
    assert reservation.status == BookingStatus.PENDING  # la place reste retenue


# --------------------------------------------------------------------------- #
# Ce que les URL publiques ne doivent pas laisser passer
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
@SANDBOX
def test_le_billet_exige_une_url_signee(client):
    """Le numero de billet est sequentiel : sans signature, on parcourt les
    billets des autres en incrementant un identifiant."""
    trajet = voyage_reservable()
    reservation = _reserver(client, trajet)

    refuse = client.get(
        reverse(
            "web:billet",
            kwargs={"pk": reservation.pk, "signature": "signature-inventee"},
        )
    )
    assert refuse.status_code == 404

    accepte = client.get(
        reverse(
            "web:billet",
            kwargs={"pk": reservation.pk, "signature": jeton(reservation.pk)},
        )
    )
    assert accepte.status_code == 200


@pytest.mark.django_db
@SANDBOX
def test_une_notification_mal_signee_est_refusee_et_journalisee(client):
    trajet = voyage_reservable()
    reservation = _reserver(client, trajet)
    _payer(client, reservation)

    reponse = client.post(
        reverse("payments:payment-webhook", kwargs={"provider": "mock_redirect"}),
        data=b'{"order_id":"1","status":"paid","amount":6500}',
        content_type="application/json",
        headers={"x-sandbox-signature": "0" * 64},
    )

    assert reponse.status_code == 400
    reservation.refresh_from_db()
    assert reservation.status == BookingStatus.PENDING
    # Journalisee quand meme : une signature invalide est une piste, pas un
    # non-evenement.
    assert PaymentWebhook.objects.filter(signature_valid=False).count() == 1


@pytest.mark.django_db
def test_la_page_operateur_simulee_n_existe_pas_en_production(client):
    """Le garde-fou vit dans la vue, pas dans la table des URL : c'est ce qui
    permet de le tester."""
    trajet = voyage_reservable()
    with override_settings(
        PAYMENT_SANDBOX=True,
        PAYMENT_SANDBOX_FLOW="redirect",
        PAYMENT_WEBHOOK_SECRET="secret-de-test",
        DEBUG=True,
    ):
        reservation = _reserver(client, trajet)
        reglement = _payer(client, reservation)

    with override_settings(DEBUG=False):
        reponse = client.get(
            reverse("web:dev-operateur", kwargs={"payment_id": reglement.pk})
        )
    assert reponse.status_code == 404
