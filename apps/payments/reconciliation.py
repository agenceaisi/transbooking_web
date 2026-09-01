"""Rattrapage des transactions restees sans reponse.

Une notification se perd : le serveur redemarre au mauvais moment, le reseau de
l'operateur hoquette, un deploiement passe. Chaque notification perdue est un
client debite qui n'a pas recu son billet, et qui appellera — ou n'appellera
pas, ce qui est pire.

Cette tache est le filet. Sans elle, la promesse « votre argent n'est pas
perdu » affichee sur l'ecran de paiement est un mensonge.

A brancher dans Celery beat :

    "reconcilier-paiements": {
        "task": "apps.payments.tasks.reconcilier_paiements",
        "schedule": crontab(minute="*/5"),
    }
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from .exceptions import PaymentAlreadyConfirmed, PaymentProviderError
from .models import MOBILE_MONEY_METHODS, Payment, PaymentStatus
from .providers import PAYMENT_FLOW_REDIRECT, get_payment_provider
from .services import confirm_payment

logger = logging.getLogger(__name__)

#: Au-dela de ce delai sans reponse, on interroge l'operateur. Assez long pour
#: laisser le payeur saisir son code PIN, assez court pour qu'il n'ait pas
#: raccroche.
DELAI_AVANT_VERIFICATION = timedelta(minutes=3)

#: Au-dela, une transaction toujours « en cours » releve du traitement manuel :
#: on alerte, on ne tranche pas. Declarer echouee une transaction qui aboutira
#: dans dix minutes revient a revendre une place deja payee.
DELAI_ALERTE = timedelta(hours=24)


def reconcilier(limite: int = 200) -> dict:
    """Poll the operator for every payment left hanging.

    Args:
        limite: Maximum number of payments examined in one pass.

    Returns:
        A count per outcome. ``rattrapes`` climbing is the signal that
        notifications are no longer arriving — well before customers call.
    """
    horizon = timezone.now() - DELAI_AVANT_VERIFICATION
    en_attente = Payment.objects.filter(
        status__in=[PaymentStatus.PENDING, PaymentStatus.OTP_REQUIRED],
        method__in=MOBILE_MONEY_METHODS,
        created_at__lt=horizon,
    ).order_by("created_at")[:limite]

    comptes = {"examines": 0, "rattrapes": 0, "echoues": 0, "erreurs": 0}

    for paiement in en_attente:
        comptes["examines"] += 1
        try:
            issue = _rafraichir(paiement)
        except PaymentProviderError:
            comptes["erreurs"] += 1
            logger.warning("Statut indisponible pour le paiement %s", paiement.pk)
            continue
        if issue:
            comptes[issue] += 1

    if comptes["rattrapes"]:
        logger.error(
            "%s paiement(s) rattrapes par reconciliation — verifier la reception "
            "des notifications d'operateur.",
            comptes["rattrapes"],
        )
    return comptes


@transaction.atomic
def _rafraichir(paiement: Payment) -> str | None:
    """Re-read one payment's status at the operator and apply it.

    Args:
        paiement: The payment to refresh.

    Returns:
        The outcome key, or None when nothing changed.
    """
    verrouille = Payment.objects.select_for_update().filter(pk=paiement.pk).first()
    if verrouille is None or verrouille.status == PaymentStatus.PAID:
        return None

    fournisseur = get_payment_provider(verrouille.method)
    if fournisseur.flow != PAYMENT_FLOW_REDIRECT:
        # Le parcours OTP se resout a la saisie du payeur : rien a interroger.
        return None

    if not verrouille.provider_ref:
        # La transaction n'a jamais ete ouverte chez l'operateur : rien n'a pu
        # etre debite, on peut abandonner sans risque.
        if timezone.now() - verrouille.created_at > DELAI_ALERTE:
            verrouille.status = PaymentStatus.FAILED
            verrouille.save(update_fields=["status", "updated_at"])
            return "echoues"
        return None

    statut = fournisseur.fetch_status(verrouille)

    if statut == PaymentStatus.PAID:
        try:
            confirm_payment(verrouille, transaction_ref=verrouille.provider_ref)
        except PaymentAlreadyConfirmed:
            return None
        return "rattrapes"

    if statut == PaymentStatus.FAILED:
        verrouille.status = PaymentStatus.FAILED
        verrouille.save(update_fields=["status", "updated_at"])
        return "echoues"

    if timezone.now() - verrouille.created_at > DELAI_ALERTE:
        logger.critical(
            "Paiement %s en attente depuis plus de 24 h — traitement manuel.",
            verrouille.pk,
        )
    return None
