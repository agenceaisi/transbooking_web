"""Pages publiques et tunnel de reservation, rendus cote serveur.

Ces vues appellent **directement les services du domaine**, jamais l'API par
HTTP. Faire un aller-retour reseau vers son propre serveur pour afficher une
liste de departs coute une serialisation, une re-authentification et une
latence, pour une donnee que la base rend en quelques millisecondes.

Les URL du tunnel portent une signature (cf. `tokens.py`) : le numero de billet
est sequentiel, une page accessible par ce seul numero laisserait parcourir les
billets des autres.
"""
import datetime as dt
import logging
from decimal import Decimal, InvalidOperation

from django.conf import settings
from django.contrib import messages
from django.db.models import F, Min
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.http import require_GET, require_http_methods

from apps.bookings.exceptions import SeatTaken, TripFull, TripUnavailable
from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import create_booking
from apps.companies.models import Company, CompanyStatus, default_parcel_pricing_config
from apps.companies.services import public_company_directory
from apps.core.services import is_payment_method_enabled
from apps.geography.models import City
from apps.parcels.models import Parcel, ParcelStatus
from apps.parcels.services import build_tracking_history, estimate_price_range
from apps.payments.models import Payment, PaymentMethod, PaymentStatus
from apps.payments.services import initiate_payment, start_redirect_flow
from apps.reviews.models import Review
from apps.routes.models import RouteStop
from apps.trips.models import Trip
from apps.trips.services import (
    NOTES_SEUILS,
    ORDRES_RECHERCHE,
    axis_overview,
    axis_summary,
    search_facets,
    search_trips,
)
from apps.trips.views import with_read_annotations

from .forms import PaiementForm, PassagerForm
from .tokens import jeton, jeton_valide

logger = logging.getLogger(__name__)

#: Libelles affiches au voyageur. Les libelles des modeles sont ecrits sans
#: accents (convention du backend) ; on ne les montre pas tels quels a un
#: client — « Paye » sur un billet fait negligé.
STATUTS_LISIBLES = {
    BookingStatus.PENDING: "En attente de paiement",
    BookingStatus.PAID: "Payé",
    BookingStatus.CANCELLED: "Annulé",
    BookingStatus.REFUNDED: "Remboursé",
}

#: Classe d'etiquette par statut de colis, pour le suivi public de l'accueil.
STATUTS_COLIS_CLASSES = {
    ParcelStatus.REGISTERED: "e-neutre",
    ParcelStatus.IN_TRANSIT: "e-info",
    ParcelStatus.ARRIVED: "e-att",
    ParcelStatus.NOTIFIED: "e-att",
    ParcelStatus.COLLECTED: "e-ok",
}

#: Libelles accentues des statuts de colis. ``ParcelStatus.choices`` (donc
#: ``get_status_display()`` et ``build_tracking_history()``) reprend la
#: convention sans accents du backend (cf. STATUTS_LISIBLES ci-dessus) — on ne
#: les montre pas tels quels a un voyageur.
STATUTS_COLIS_LISIBLES = {
    ParcelStatus.REGISTERED: "Enregistré",
    ParcelStatus.IN_TRANSIT: "En transit",
    ParcelStatus.ARRIVED: "Arrivé",
    ParcelStatus.NOTIFIED: "Destinataire prévenu",
    ParcelStatus.COLLECTED: "Remis",
}

MOYENS_LISIBLES = {
    PaymentMethod.ORANGE_MONEY: "Orange Money",
    PaymentMethod.MOOV_MONEY: "Moov Money",
    PaymentMethod.CORIS_MONEY: "Coris Money",
    PaymentMethod.TELECEL_MONEY: "Telecel Money",
    PaymentMethod.CASH: "Espèces au guichet",
}


# --------------------------------------------------------------------------- #
# Pages publiques
# --------------------------------------------------------------------------- #
#: Ville prise comme reference pour le tableau de gare et la grille de
#: destinations. A defaut (base vide ou ville renommee), la premiere ville
#: connue prend le relais plutot que de faire echouer la page.
VILLE_REFERENCE_SLUG = "ouagadougou"


@require_GET
def accueil(request: HttpRequest) -> HttpResponse:
    """Landing page accessible to everyone: search panel, live departures,
    destinations, fares, partner companies, parcel tools and FAQ.

    Un depart de recherche avec origine et destination renseignees redirige
    directement vers la page de resultats — la page d'accueil ne duplique pas
    cette logique, elle se contente de resoudre les noms de ville saisis.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the results page when a trip search is submitted, or the
        rendered home page.
    """
    redirection = _rediriger_recherche(request)
    if redirection is not None:
        return redirection

    villes = City.objects.order_by("name")
    ville_reference = City.objects.filter(
        slug=VILLE_REFERENCE_SLUG
    ).first() or villes.first()

    aujourdhui = timezone.localdate()
    departs_reference: list[Trip] = []
    if ville_reference is not None:
        departs_reference = list(
            search_trips(
                origin_city_id=ville_reference.id, date=aujourdhui, order="depart"
            )[:24]
        )
        if len(departs_reference) < 4:
            # Peu ou pas de departs aujourd'hui (base peu remplie, ou soiree
            # avancee) : on montre les prochains departs, quelle que soit la
            # date, plutot qu'une page vide.
            departs_reference = list(
                search_trips(origin_city_id=ville_reference.id, order="depart")[:24]
            )

    context = {
        "villes": villes,
        "ville_reference": ville_reference,
        "departs_gare": departs_reference[:6],
        "departs": departs_reference,
        "depart_moins_cher_id": (
            min(departs_reference, key=lambda d: d.price).id
            if departs_reference
            else None
        ),
        "destinations_frequentes": _destinations_frequentes(departs_reference),
        "destinations": axis_overview(
            origin_slug=ville_reference.slug if ville_reference else "", limit=8
        ),
        "tarifs_par_axe": axis_overview(limit=8),
        "compagnies": public_company_directory(limit=4),
        "compagnies_total": Company.objects.filter(
            status=CompanyStatus.ACTIVE
        ).count(),
        "departs_aujourdhui_total": Trip.objects.filter(
            status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
            departure_time__date=aujourdhui,
        ).count(),
        "temoignages": Review.objects.filter(is_testimonial=True)
        .select_related("company", "user")
        .order_by("-created_at")[:3],
        "exemple_troncon": _exemple_troncon(),
    }
    context.update(_suivi_colis(request))
    context.update(_estimation_colis(request))
    moyens = _moyens_disponibles()
    context["moyens_paiement"] = moyens
    context["moyens_mobile_money"] = [
        m for m in moyens if m[0] != PaymentMethod.CASH
    ]
    context["statuts_colis_classes"] = STATUTS_COLIS_CLASSES
    context["statuts_colis_lisibles"] = STATUTS_COLIS_LISIBLES
    context["grille_colis_reference"] = default_parcel_pricing_config()

    if context["estimation"] or context["estimation_erreur"]:
        context["onglet_actif"] = "envoi"
    elif context["suivi_colis"] or context["suivi_introuvable"]:
        context["onglet_actif"] = "suivi"
    else:
        context["onglet_actif"] = "voyage"

    return render(request, "public/accueil.html", context)


def _rediriger_recherche(request: HttpRequest) -> HttpResponse | None:
    """Resolve a homepage trip search into a redirect to the results page.

    Args:
        request: The incoming request.

    Returns:
        A redirect when both cities are given and recognised, ``None``
        otherwise (an unresolved city name adds a flash message and lets the
        caller fall back to rendering the home page).
    """
    origine = (request.GET.get("origine") or "").strip()
    destination = (request.GET.get("destination") or "").strip()
    if not origine or not destination:
        return None

    ville_depart = City.objects.filter(name__iexact=origine).first()
    ville_arrivee = City.objects.filter(name__iexact=destination).first()
    if ville_depart is None or ville_arrivee is None:
        messages.error(
            request,
            "Ville de départ ou d'arrivée introuvable. Vérifiez l'orthographe "
            "ou choisissez-la dans la liste proposée.",
        )
        return None

    parametres = {}
    if request.GET.get("date"):
        parametres["date"] = request.GET["date"]
    if request.GET.get("passagers"):
        parametres["passagers"] = request.GET["passagers"]

    url = reverse(
        "web:resultats",
        kwargs={"origine": ville_depart.slug, "destination": ville_arrivee.slug},
    )
    if parametres:
        url = f"{url}?{urlencode(parametres)}"
    return redirect(url)


def _destinations_frequentes(departs: list[Trip], limite: int = 6) -> list[dict]:
    """Tally destination cities among a list of departures, most frequent first.

    Feeds the quick-filter chips above the departures list: real counts from
    the departures actually shown, not a separate query.

    Args:
        departs: The departures currently displayed.
        limite: Maximum number of destinations returned.

    Returns:
        Dicts with ``ville`` (the ``City``) and ``nombre`` of departures.
    """
    comptes: dict[int, dict] = {}
    for depart in departs:
        ville = depart.route.destination_city
        entree = comptes.setdefault(ville.id, {"ville": ville, "nombre": 0})
        entree["nombre"] += 1
    return sorted(comptes.values(), key=lambda e: -e["nombre"])[:limite]


def _exemple_troncon() -> dict | None:
    """Find one real intermediate stop cheaper than its route's full fare.

    Backs the "vous ne payez que jusqu'à votre arrêt" claim with an actual
    route rather than an invented example.

    Returns:
        ``{"route": Route, "stop": RouteStop}`` for the first matching stop
        found, or ``None`` when no route currently has one.
    """
    stop = (
        RouteStop.objects.filter(route__is_active=True, stop_price__lt=F("route__base_price"))
        .select_related("route__origin_city", "route__destination_city", "city")
        .order_by("route_id", "stop_order")
        .first()
    )
    if stop is None:
        return None
    return {"route": stop.route, "stop": stop}


def _suivi_colis(request: HttpRequest) -> dict:
    """Look up a parcel by tracking number for the public tracking widget.

    Args:
        request: The incoming request, possibly carrying ``?suivi=``.

    Returns:
        ``{"suivi_numero", "suivi_colis", "suivi_jalons", "suivi_introuvable"}``.
    """
    vide = {
        "suivi_numero": "",
        "suivi_colis": None,
        "suivi_jalons": [],
        "suivi_position_actuelle": None,
        "suivi_introuvable": False,
    }
    numero = (request.GET.get("suivi") or "").strip().upper()
    if not numero:
        return vide

    colis = (
        Parcel.objects.select_related("origin_city", "destination_city", "company")
        .prefetch_related("notifications")
        .filter(tracking_number=numero)
        .first()
    )
    if colis is None:
        return {**vide, "suivi_numero": numero, "suivi_introuvable": True}
    return {
        "suivi_numero": numero,
        "suivi_colis": colis,
        "suivi_jalons": build_tracking_history(colis),
        "suivi_position_actuelle": _position_colis(colis),
        "suivi_introuvable": False,
    }


def _position_colis(colis: Parcel):
    """Where a parcel honestly is, without inventing an in-transit position.

    Mirrors ``ParcelTrackSerializer.get_current_location`` (cf.
    ``apps.parcels.serializers``) so the server-rendered tracking widget says
    exactly what the public tracking API says.

    Args:
        colis: The parcel being tracked.

    Returns:
        The known city name, or ``None`` while in transit — a real transit
        position isn't tracked, so nothing is shown rather than guessed.
    """
    if colis.status == ParcelStatus.REGISTERED:
        return colis.origin_city.name if colis.origin_city_id else None
    if colis.status in {
        ParcelStatus.ARRIVED,
        ParcelStatus.NOTIFIED,
        ParcelStatus.COLLECTED,
    }:
        return colis.destination_city.name if colis.destination_city_id else None
    return None


def _estimation_colis(request: HttpRequest) -> dict:
    """Estimate a parcel's price range from the "Envoyer un colis" mini-form.

    Args:
        request: The incoming request, possibly carrying ``colis_origine``,
            ``colis_destination`` and ``colis_poids``.

    Returns:
        ``{"colis_origine", "colis_destination", "colis_poids", "estimation",
        "estimation_erreur"}``.
    """
    origine = (request.GET.get("colis_origine") or "").strip()
    destination = (request.GET.get("colis_destination") or "").strip()
    poids_brut = (request.GET.get("colis_poids") or "").strip()

    resultat = {
        "colis_origine": origine,
        "colis_destination": destination,
        "colis_poids": poids_brut,
        "estimation": None,
        "estimation_erreur": None,
    }
    if not (origine and destination and poids_brut):
        return resultat

    poids = _decimal(poids_brut)
    ville_depart = City.objects.filter(name__iexact=origine).first()
    ville_arrivee = City.objects.filter(name__iexact=destination).first()
    if poids is None or poids <= 0 or ville_depart is None or ville_arrivee is None:
        resultat["estimation_erreur"] = (
            "Vérifiez les deux villes et le poids saisis."
        )
        return resultat

    resultat["estimation"] = estimate_price_range(
        poids, ville_depart.id, ville_arrivee.id
    )
    if resultat["estimation"] is None:
        resultat["estimation_erreur"] = (
            "Aucune compagnie active ne dessert encore cet axe pour les colis."
        )
    return resultat


def _decimal(valeur: str) -> Decimal | None:
    """Parse a user-entered decimal, accepting a comma as separator.

    Args:
        valeur: The raw text.

    Returns:
        The parsed ``Decimal``, or ``None`` when unreadable.
    """
    try:
        return Decimal(valeur.replace(",", ".").strip())
    except (InvalidOperation, AttributeError):
        return None


@require_GET
def resultats(request: HttpRequest, origine: str, destination: str) -> HttpResponse:
    """Search results for one city pair and one date.

    C'est la page la plus importante du site : celle qui convertit **et** celle
    qui se referencie. Son URL est donc lisible et stable
    (``/trajets/ouagadougou/bobo-dioulasso/``), et ses filtres vivent dans la
    chaine de requete pour rester partageables.

    Args:
        request: The incoming request.
        origine: Departure city slug.
        destination: Arrival city slug.

    Returns:
        The rendered results page.

    Raises:
        Http404: If either city slug is unknown.
    """
    ville_depart = get_object_or_404(City, slug=origine)
    ville_arrivee = get_object_or_404(City, slug=destination)
    date = _date_demandee(request)
    passagers = _entier(request.GET.get("passagers"), defaut=1)

    # Etat du rail de filtres : lu une fois, partage entre le comptage par
    # facette (`search_facets`, sur le jour de base) et la recherche
    # effective (`search_trips`, qui applique la combinaison).
    compagnie_ids = request.GET.getlist("compagnie")
    heure = request.GET.get("heure") or None
    escales = request.GET.getlist("escales")
    services = request.GET.getlist("service")
    paliers = request.GET.getlist("palier")
    note = request.GET.get("note") or None
    prix_min = _decimal(request.GET.get("prix_min", ""))
    prix_max = _decimal(request.GET.get("prix_max", ""))
    seuil_note = next((s for c, l, s in NOTES_SEUILS if c == note), None)
    tri = request.GET.get("tri", "prix")

    facettes = search_facets(
        origin_slug=origine,
        destination_slug=destination,
        date=date,
        passengers=passagers,
        company_ids=compagnie_ids,
        heure=heure,
        escales=escales,
        services=services,
        vehicle_types=paliers,
        note=note,
    )
    if "compagnie" not in request.GET:
        # Rien de coché = aucune restriction : contrairement aux autres
        # facettes, la compagnie part de « tout coché » (cf. lien_compagnie).
        for c in facettes["compagnies"]:
            c["actif"] = True

    voyages = search_trips(
        origin_slug=origine,
        destination_slug=destination,
        date=date,
        passengers=passagers,
        company_ids=[c for c in compagnie_ids if c.isdigit()],
        min_price=prix_min,
        max_price=prix_max,
        min_rating=seuil_note,
        heure=heure,
        escales=escales,
        services=services,
        vehicle_types=paliers,
        order=tri,
    )
    # `prefetch_related` : la fenetre au survol du trajet liste les escales,
    # et `search_trips` ne les charge pas d'office (page detail seule avant).
    voyages = list(voyages.prefetch_related("route__stops__city")[:60])

    return render(
        request,
        "public/resultats.html",
        {
            "ville_depart": ville_depart,
            "ville_arrivee": ville_arrivee,
            "date": date,
            "voyages": voyages,
            "prix_mini": min((v.price for v in voyages), default=None),
            "jours": _prix_par_jour(origine, destination, date),
            "facettes": facettes,
            "prix_min_saisi": request.GET.get("prix_min", ""),
            "prix_max_saisi": request.GET.get("prix_max", ""),
            "champs_caches_prix": [
                (cle, valeur)
                for cle, valeurs in request.GET.lists()
                if cle not in ("prix_min", "prix_max")
                for valeur in valeurs
            ],
            **_plage_prix(facettes, prix_min, prix_max),
            "tri": tri,
            "ordres": ORDRES_RECHERCHE,
            "passagers": passagers,
            "resume_axe": axis_summary(origin_slug=origine, destination_slug=destination),
            "autres_destinations": [
                a
                for a in axis_overview(origin_slug=origine, limit=9)
                if a["destination_city"]["slug"] != destination
            ][:8],
        },
    )


def _plage_prix(facettes: dict, prix_min, prix_max) -> dict:
    """Position the price filter's visual range track (`.piste`).

    Purement decoratif : la vraie restriction vient des deux champs
    numeriques du formulaire, ce calcul ne fait que placer les deux poignees
    en pourcentage entre le prix le plus bas et le plus haut du jour.

    Args:
        facettes: The `search_facets` result (reads ``prix_plancher``/``prix_plafond``).
        prix_min: The traveler's selected lower bound, or ``None``.
        prix_max: The traveler's selected upper bound, or ``None``.

    Returns:
        ``{"prix_pct_min", "prix_pct_max_droite"}`` — CSS ``left``/``right``
        percentages for the range track's two handles.
    """
    plancher = facettes["prix_plancher"]
    plafond = facettes["prix_plafond"]
    if plancher is None or plafond is None or plafond <= plancher:
        return {"prix_pct_min": 0, "prix_pct_max_droite": 0}

    etendue = float(plafond - plancher)
    selection_min = float(prix_min) if prix_min is not None else float(plancher)
    selection_max = float(prix_max) if prix_max is not None else float(plafond)
    selection_min = max(float(plancher), min(selection_min, float(plafond)))
    selection_max = max(float(plancher), min(selection_max, float(plafond)))

    return {
        "prix_pct_min": round((selection_min - float(plancher)) / etendue * 100, 1),
        "prix_pct_max_droite": round((float(plafond) - selection_max) / etendue * 100, 1),
    }


# --------------------------------------------------------------------------- #
# Tunnel de reservation
# --------------------------------------------------------------------------- #
@require_GET
def voyage(request: HttpRequest, pk: int) -> HttpResponse:
    """Trip detail and passenger form.

    Args:
        request: The incoming request.
        pk: The trip identifier.

    Returns:
        The rendered trip page.
    """
    trajet = _trajet_reservable(pk)
    return render(
        request,
        "tunnel/voyage.html",
        {
            "trajet": trajet,
            "escales": trajet.route.stops.select_related("city").all(),
            "form": PassagerForm(),
            "etape": 2,
        },
    )


@require_http_methods(["POST"])
def reserver(request: HttpRequest, pk: int) -> HttpResponse:
    """Create the booking, then hand over to the payment step.

    La place n'est retenue qu'ici : ``create_booking`` decremente les sieges
    sous verrou de ligne. Tant que le voyageur remplit le formulaire, rien ne
    lui est reserve — et c'est volontaire, sinon quelques paniers abandonnes
    afficheraient « complet » sur un car vide.

    Args:
        request: The incoming request.
        pk: The trip identifier.

    Returns:
        A redirect to the payment step, or the form with its errors.
    """
    trajet = _trajet_reservable(pk)
    form = PassagerForm(request.POST)

    if not form.is_valid():
        return render(
            request,
            "tunnel/voyage.html",
            {
                "trajet": trajet,
                "escales": trajet.route.stops.select_related("city").all(),
                "form": form,
                "etape": 2,
            },
            status=400,
        )

    try:
        reservation = create_booking(
            {
                "trip": trajet,
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data["last_name"],
                "phone": form.cleaned_data["phone"],
                "seat_number": form.cleaned_data.get("seat_number") or None,
                "amount": trajet.price,
                # Pas de compte obligatoire : on rattache la reservation a
                # l'utilisateur seulement s'il se trouve deja connecte.
                "user": request.user if request.user.is_authenticated else None,
            }
        )
    except SeatTaken:
        # Course sur le siege choisi : on renvoie au formulaire pour qu'il en
        # choisisse un autre, plutot que de laisser remonter une 500.
        messages.error(
            request,
            "Ce siege vient d'etre attribue a un autre passager. "
            "Merci d'en choisir un autre.",
        )
        return render(
            request,
            "tunnel/voyage.html",
            {
                "trajet": trajet,
                "escales": trajet.route.stops.select_related("city").all(),
                "form": form,
                "etape": 2,
            },
            status=409,
        )
    except TripFull:
        messages.error(request, "Ce voyage est complet.")
        return render(
            request,
            "tunnel/voyage.html",
            {
                "trajet": trajet,
                "escales": trajet.route.stops.select_related("city").all(),
                "form": form,
                "etape": 2,
            },
            status=409,
        )
    except TripUnavailable:
        messages.error(request, "Ce voyage n'est plus ouvert a la reservation.")
        return render(
            request,
            "tunnel/voyage.html",
            {
                "trajet": trajet,
                "escales": trajet.route.stops.select_related("city").all(),
                "form": form,
                "etape": 2,
            },
            status=410,
        )

    logger.info("Reservation %s creee depuis le site", reservation.ticket_number)
    return redirect("web:paiement", pk=reservation.pk, signature=jeton(reservation.pk))


@require_http_methods(["GET", "POST"])
def paiement(request: HttpRequest, pk: int, signature: str) -> HttpResponse:
    """Choose a payment method, then open the operator transaction.

    Args:
        request: The incoming request.
        pk: The booking identifier.
        signature: The URL signature protecting the booking.

    Returns:
        A redirect to the operator page, or the rendered payment step.
    """
    reservation = _reservation(pk, signature)

    if reservation.status == BookingStatus.PAID:
        return redirect("web:billet", pk=pk, signature=signature)

    moyens = _moyens_disponibles()
    form = PaiementForm(request.POST or None, moyens=moyens)

    if request.method == "POST" and form.is_valid():
        methode = form.cleaned_data["method"]
        reglement = initiate_payment(
            reservation,
            method=methode,
            phone=form.cleaned_data.get("payer_phone", ""),
        )

        if methode == PaymentMethod.CASH:
            # Especes : la place est retenue, le reglement se fait au guichet.
            return redirect("web:billet", pk=pk, signature=signature)

        url_operateur = start_redirect_flow(
            reglement,
            return_url=_absolue(request, "web:attente", pk=pk, signature=signature),
            cancel_url=_absolue(request, "web:paiement", pk=pk, signature=signature),
            notify_url=_absolue_webhook(request, reglement),
        )
        return redirect(url_operateur)

    return render(
        request,
        "tunnel/paiement.html",
        {
            "reservation": reservation,
            "trajet": reservation.trip,
            "form": form,
            "moyens": moyens,
            "etape": 3,
        },
    )


@require_GET
def attente(request: HttpRequest, pk: int, signature: str) -> HttpResponse:
    """Waiting page the operator sends the browser back to.

    **Cette page n'accorde jamais le paiement.** Un retour de navigateur se
    falsifie en modifiant une URL ; seule la notification signee de l'operateur
    fait foi. La page interroge donc notre propre statut, en boucle, jusqu'a ce
    que le webhook ait fait son travail.

    Args:
        request: The incoming request.
        pk: The booking identifier.
        signature: The URL signature.

    Returns:
        The rendered waiting page.
    """
    reservation = _reservation(pk, signature)
    if reservation.status == BookingStatus.PAID:
        return redirect("web:billet", pk=pk, signature=signature)
    return render(
        request,
        "tunnel/attente.html",
        {"reservation": reservation, "signature": signature, "etape": 3},
    )


@require_GET
def statut(request: HttpRequest, pk: int, signature: str) -> HttpResponse:
    """Status fragment polled by the waiting page.

    Args:
        request: The incoming request.
        pk: The booking identifier.
        signature: The URL signature.

    Returns:
        A small HTML fragment describing where the payment stands.
    """
    reservation = _reservation(pk, signature)
    dernier = reservation.payments.order_by("-created_at").first()
    return render(
        request,
        "partiels/statut_paiement.html",
        {
            "reservation": reservation,
            "paiement": dernier,
            "signature": signature,
            "payee": reservation.status == BookingStatus.PAID,
            "echouee": dernier is not None and dernier.status == PaymentStatus.FAILED,
        },
    )


@require_GET
def billet(request: HttpRequest, pk: int, signature: str) -> HttpResponse:
    """The ticket itself, reachable by a signed link sent by SMS.

    Args:
        request: The incoming request.
        pk: The booking identifier.
        signature: The URL signature.

    Returns:
        The rendered ticket page.
    """
    reservation = _reservation(pk, signature)
    return render(
        request,
        "tunnel/billet.html",
        {
            "reservation": reservation,
            "trajet": reservation.trip,
            "statut": STATUTS_LISIBLES.get(reservation.status, reservation.status),
            "signature": signature,
        },
    )


# --------------------------------------------------------------------------- #
# Utilitaires
# --------------------------------------------------------------------------- #
def _reservation(pk: int, signature: str) -> Booking:
    """Load a booking from a signed public URL.

    Args:
        pk: The booking identifier.
        signature: The signature carried by the URL.

    Returns:
        The booking.

    Raises:
        Http404: If the signature does not match — indistinguishable, from the
            outside, from a booking that does not exist.
    """
    if not jeton_valide(pk, signature):
        raise Http404
    return get_object_or_404(
        Booking.objects.select_related(
            "trip__route__company",
            "trip__route__origin_city",
            "trip__route__destination_city",
            "trip__route__origin_station",
            "trip__route__destination_station",
        ),
        pk=pk,
    )


def _trajet_reservable(pk: int) -> Trip:
    """Load a trip still open to booking.

    Args:
        pk: The trip identifier.

    Returns:
        The annotated trip.

    Raises:
        Http404: If the trip is unknown, cancelled or already gone.
    """
    trajet = get_object_or_404(
        with_read_annotations(
            Trip.objects.select_related(
                "route__company",
                "route__origin_city",
                "route__destination_city",
                "route__origin_station",
                "route__destination_station",
                "vehicle",
            )
        ),
        pk=pk,
    )
    if trajet.status in {Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED}:
        raise Http404
    return trajet


def _moyens_disponibles() -> list[tuple[str, str]]:
    """List the payment methods currently offered to travellers.

    Returns:
        ``(valeur, libelle)`` pairs, Mobile Money first.
    """
    ordre = [
        PaymentMethod.ORANGE_MONEY,
        PaymentMethod.MOOV_MONEY,
        PaymentMethod.CORIS_MONEY,
        PaymentMethod.TELECEL_MONEY,
        PaymentMethod.CASH,
    ]
    return [
        (m.value, MOYENS_LISIBLES[m]) for m in ordre if is_payment_method_enabled(m)
    ]


def _prix_par_jour(origine: str, destination: str, date, marge: int = 3) -> list[dict]:
    """Cheapest price per day around the requested date.

    Une seule requete agregee pour toute la bande : la calculer jour par jour
    ferait sept allers-retours a chaque affichage de la page la plus consultee
    du site.

    Args:
        origine: Departure city slug.
        destination: Arrival city slug.
        date: The centre of the window.
        marge: Number of days shown on each side.

    Returns:
        One entry per day, with its lowest price when there is one.
    """
    debut = date - dt.timedelta(days=marge)
    fin = date + dt.timedelta(days=marge)
    lignes = (
        Trip.objects.filter(
            route__origin_city__slug=origine,
            route__destination_city__slug=destination,
            status__in=[Trip.TripStatus.SCHEDULED, Trip.TripStatus.DELAYED],
            departure_time__date__gte=debut,
            departure_time__date__lte=fin,
            available_seats__gt=0,
        )
        .values("departure_time__date")
        .annotate(prix=Min("price"))
    )
    par_date = {ligne["departure_time__date"]: ligne["prix"] for ligne in lignes}
    mini = min(par_date.values(), default=None)

    return [
        {
            "date": debut + dt.timedelta(days=i),
            "prix": par_date.get(debut + dt.timedelta(days=i)),
            "courant": (debut + dt.timedelta(days=i)) == date,
            "meilleur": mini is not None
            and par_date.get(debut + dt.timedelta(days=i)) == mini,
        }
        for i in range(marge * 2 + 1)
    ]


def _date_demandee(request: HttpRequest):
    """Read the requested date, defaulting to today.

    Une date illisible ne renvoie pas une erreur : elle retombe sur
    aujourd'hui. Un lien partage avec une date mal formee doit montrer des
    departs, pas une page d'erreur.

    Args:
        request: The incoming request.

    Returns:
        The date to search.
    """
    brut = request.GET.get("date")
    if brut:
        try:
            return dt.date.fromisoformat(brut)
        except ValueError:
            pass
    return timezone.localdate()


def _entier(valeur, defaut=None):
    """Parse an integer query parameter, falling back on a default.

    Args:
        valeur: The raw parameter.
        defaut: The value returned when parsing fails.

    Returns:
        The parsed integer, or the default.
    """
    try:
        return int(valeur)
    except (TypeError, ValueError):
        return defaut


def _absolue(request: HttpRequest, nom: str, **kwargs) -> str:
    """Build an absolute URL for a named route.

    Args:
        request: The incoming request.
        nom: The URL name.
        **kwargs: The URL keyword arguments.

    Returns:
        The absolute URL.
    """
    return request.build_absolute_uri(reverse(nom, kwargs=kwargs))


def _absolue_webhook(request: HttpRequest, reglement: Payment) -> str:
    """Build the notification URL the operator will call back.

    En developpement, ``request.build_absolute_uri`` produit une adresse
    ``localhost`` qu'aucun operateur ne peut joindre : ``SITE_BASE_URL`` prend
    alors le relais, ce qui permet de pointer un tunnel public.

    Args:
        request: The incoming request.
        reglement: The payment being opened.

    Returns:
        The absolute webhook URL.
    """
    from apps.payments.providers import get_payment_provider

    chemin = reverse(
        "payments:payment-webhook",
        kwargs={"provider": get_payment_provider(reglement.method).name},
    )
    base = (getattr(settings, "SITE_BASE_URL", "") or "").rstrip("/")
    return f"{base}{chemin}" if base else request.build_absolute_uri(chemin)
