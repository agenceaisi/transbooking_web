"""Page operateur simulee — developpement uniquement.

Tient lieu de la page Orange Money tant que le compte marchand n'est pas
ouvert : le voyageur y « valide » ou « annule », et la notification part comme
elle partira en production — signee, asynchrone, vers notre propre webhook.

Elle emprunte volontairement le chemin HTTP complet plutot que d'appeler la
logique en direct : c'est ainsi qu'on eprouve la verification de signature et
la deduplication, qui sont precisement ce qui casse en production.

Le scenario rejoue se lit dans les deux derniers chiffres du montant
(cf. ``MockRedirectProvider``), ce qui rend les essais reproductibles sans rien
configurer : un billet a 6 503 FCFA n'emet jamais sa notification, et seule la
reconciliation le rattrape.
"""
import hashlib
import hmac
import json
import logging

from django.conf import settings
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.payments.models import Payment, PaymentStatus
from apps.payments.providers import MockRedirectProvider

from .tokens import jeton

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def operateur_simule(request: HttpRequest, payment_id: int) -> HttpResponse:
    """Stand in for the operator's payment page.

    Args:
        request: The incoming request.
        payment_id: The payment being settled.

    Returns:
        The fake operator page, or a redirect back to the waiting page.

    Raises:
        Http404: Outside DEBUG — this page must never exist in production.
    """
    if not settings.DEBUG:
        raise Http404

    reglement = get_object_or_404(
        Payment.objects.select_related("booking"), pk=payment_id
    )
    scenario = MockRedirectProvider.scenario(reglement)
    reservation = reglement.booking

    if request.method == "POST":
        accepte = request.POST.get("decision") == "valider"
        _notifier(request, reglement, accepte=accepte, scenario=scenario)
        return redirect(
            reverse(
                "web:attente",
                kwargs={
                    "pk": reservation.pk,
                    "signature": jeton(reservation.pk),
                },
            )
        )

    return render(
        request,
        "dev/operateur.html",
        {
            "paiement": reglement,
            "reservation": reservation,
            "scenario": scenario,
            "explication": _EXPLICATIONS.get(scenario, ""),
        },
    )


_EXPLICATIONS = {
    "succes": "Notification immediate. Le billet est emis a la validation.",
    "annulation": "Le payeur renonce : le paiement passe en echec.",
    "expiration": "La transaction expire chez l'operateur.",
    "notification_perdue": (
        "Le payeur est debite mais AUCUNE notification n'est emise. "
        "Seule la tache de reconciliation doit rattraper ce paiement."
    ),
    "notification_doublee": (
        "La notification est emise deux fois. Un seul billet doit etre emis, "
        "une seule ecriture au grand livre."
    ),
    "montant_divergent": (
        "L'operateur annonce un montant different de celui demande. "
        "Le paiement ne doit PAS etre confirme, une alerte doit se lever."
    ),
}


def _notifier(request, reglement: Payment, *, accepte: bool, scenario: str) -> None:
    """Emit the simulated operator notification, exactly as production would.

    Args:
        request: The incoming request, for the absolute webhook URL.
        reglement: The payment being settled.
        accepte: Whether the payer validated.
        scenario: The replayed scenario.
    """
    if scenario == "notification_perdue" and accepte:
        logger.warning(
            "Scenario « notification perdue » : paiement %s laisse sans reponse.",
            reglement.pk,
        )
        return

    if not accepte or scenario in {"annulation", "expiration"}:
        statut = PaymentStatus.FAILED
    else:
        statut = PaymentStatus.PAID

    montant = int(reglement.amount)
    if scenario == "montant_divergent" and statut == PaymentStatus.PAID:
        montant = max(montant - 500, 0)

    corps = json.dumps(
        {
            "order_id": str(reglement.pk),
            "pay_token": reglement.provider_ref,
            "status": statut,
            "amount": montant,
            "txnid": f"SANDBOX{reglement.pk:08d}REF",
        },
        separators=(",", ":"),
    ).encode("utf-8")

    signature = hmac.new(
        (settings.PAYMENT_WEBHOOK_SECRET or "").encode("utf-8"),
        corps,
        hashlib.sha256,
    ).hexdigest()

    url = reverse(
        "payments:payment-webhook", kwargs={"provider": MockRedirectProvider.name}
    )

    # Client de test plutot qu'un vrai appel reseau : on veut le chemin HTTP
    # complet (signature, deduplication, transaction) sans dependre d'un
    # serveur joignable depuis lui-meme.
    from django.test import Client

    client = Client()
    envois = 2 if scenario == "notification_doublee" else 1
    for numero in range(envois):
        reponse = client.post(
            url,
            data=corps,
            content_type="application/json",
            headers={"x-sandbox-signature": signature},
        )
        logger.info(
            "Notification simulee %s/%s -> HTTP %s (%s)",
            numero + 1,
            envois,
            reponse.status_code,
            reponse.content.decode()[:40],
        )
