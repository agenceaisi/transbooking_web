"""Espace voyageur connecte : tableau de bord, reservations, bagages,
reclamations, avis, signalements et profil.

Meme convention que le tunnel anonyme (`views.py`) : les vues appellent
**directement** les services du domaine, jamais l'API HTTP. L'authentification
est une session Django classique (distincte du JWT de l'API mobile) : chaque
vue porte `@login_required` et filtre systematiquement par `request.user` — pas
de filtre par compagnie ici, c'est l'appartenance au voyageur qui isole les
donnees.
"""
import logging

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods
from rest_framework.exceptions import APIException

from apps.bookings.models import Booking, BookingStatus
from apps.bookings.services import cancel_booking, create_booking
from apps.claims.models import Claim, ClaimStatus
from apps.claims.services import (
    accept_claim_response,
    add_claim_attachment,
    annotated_claims,
    create_claim,
    escalate_claim,
    unresolved_first,
)
from apps.notifications.models import Notification
from apps.parcels.models import Parcel, ParcelStatus
from apps.payments.exceptions import (
    OtpExpired,
    OtpInvalid,
    OtpMaxAttemptsReached,
    OtpNotRequired,
    OtpResendTooSoon,
    PaymentProviderError,
)
from apps.payments.models import Payment, PaymentMethod, PaymentStatus
from apps.payments.services import (
    initiate_payment,
    resend_payment_otp,
    verify_payment_otp,
)
from apps.reviews.services import can_review, create_review
from apps.routes.models import RouteStop
from apps.speed_reports.services import create_speed_report
from apps.trips.models import Trip
from apps.users.services import change_password, create_voyageur
from apps.vehicles.services import get_available_seats

from .auth_forms import ConnexionForm, InscriptionForm
from .espace_forms import (
    AvisForm,
    BagageDeclarationForm,
    MotDePasseForm,
    OtpForm,
    PaiementMethodeForm,
    PassagerConnecteForm,
    ProfilForm,
    ReclamationForm,
    SignalementForm,
)
from .views import MOYENS_LISIBLES, STATUTS_LISIBLES, _moyens_disponibles, _trajet_reservable

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# Connexion / inscription
# --------------------------------------------------------------------------- #
@require_http_methods(["GET", "POST"])
def connexion(request: HttpRequest) -> HttpResponse:
    """Login page for the traveler session.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the dashboard on success, or the rendered login form.
    """
    if request.user.is_authenticated:
        return redirect("web:espace-tableau-de-bord")

    form = ConnexionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        utilisateur = authenticate(
            request,
            phone=form.cleaned_data["phone"],
            password=form.cleaned_data["password"],
        )
        if utilisateur is None:
            messages.error(request, "Telephone ou mot de passe incorrect.")
        else:
            login(request, utilisateur)
            suite = request.GET.get("suivant")
            return redirect(suite or "web:espace-tableau-de-bord")

    return render(request, "espace/connexion.html", {"form": form})


@require_http_methods(["GET", "POST"])
def inscription(request: HttpRequest) -> HttpResponse:
    """Traveler account creation.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the dashboard on success, or the rendered form.
    """
    if request.user.is_authenticated:
        return redirect("web:espace-tableau-de-bord")

    form = InscriptionForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            utilisateur = create_voyageur(form.cleaned_data)
        except DjangoValidationError as exc:
            for erreurs in exc.message_dict.values():
                for erreur in erreurs:
                    messages.error(request, erreur)
        else:
            login(request, utilisateur)
            return redirect("web:espace-tableau-de-bord")

    return render(request, "espace/inscription.html", {"form": form})


@require_http_methods(["POST"])
def deconnexion(request: HttpRequest) -> HttpResponse:
    """Log the traveler out.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the home page.
    """
    logout(request)
    return redirect("web:accueil")


# --------------------------------------------------------------------------- #
# Ecran 1 — Tableau de bord
# --------------------------------------------------------------------------- #
@login_required
@require_GET
def tableau_de_bord(request: HttpRequest) -> HttpResponse:
    """Traveler dashboard: next trip, to-dos, notifications and parcels.

    Args:
        request: The incoming request.

    Returns:
        The rendered dashboard.
    """
    utilisateur = request.user
    maintenant = timezone.now()

    prochaine = (
        Booking.objects.filter(
            user=utilisateur,
            status=BookingStatus.PAID,
            trip__departure_time__gte=maintenant,
        )
        .exclude(trip__status__in=[Trip.TripStatus.CANCELLED, Trip.TripStatus.COMPLETED])
        .select_related(
            "trip__route__company",
            "trip__route__origin_city",
            "trip__route__destination_city",
        )
        .order_by("trip__departure_time")
        .first()
    )

    a_payer = (
        Booking.objects.filter(
            user=utilisateur,
            status=BookingStatus.PENDING,
            trip__registration_closes_at__gte=maintenant,
        )
        .select_related("trip__route__origin_city", "trip__route__destination_city")
        .order_by("trip__registration_closes_at")[:5]
    )

    a_noter = (
        Booking.objects.filter(
            user=utilisateur,
            status=BookingStatus.PAID,
            trip__status=Trip.TripStatus.COMPLETED,
        )
        .exclude(trip__reviews__user=utilisateur)
        .select_related("trip__route__company")
        .order_by("-trip__departure_time")[:3]
    )

    # Rapprochement approximatif par numero de telephone : Parcel n'a pas de FK
    # `user` (colis pouvant etre envoyes/recus par des non-inscrits).
    colis = Parcel.objects.filter(
        recipient_phone=utilisateur.phone,
        status__in=[ParcelStatus.ARRIVED, ParcelStatus.NOTIFIED],
    ).select_related("destination_city")[:3]

    notifications = Notification.objects.filter(user=utilisateur).order_by("-created_at")[:6]

    return render(
        request,
        "espace/tableau_de_bord.html",
        {
            "prochaine": prochaine,
            "a_payer": a_payer,
            "a_noter": a_noter,
            "colis": colis,
            "notifications": notifications,
        },
    )


# --------------------------------------------------------------------------- #
# Ecran 2 — Reservation (trajet, escale, passager, siege)
# --------------------------------------------------------------------------- #
def _plan_sieges(trajet: Trip) -> list[list[dict]]:
    """Build the seat grid rows shown on the reservation screen.

    Uses the vehicle's own ``seat_plan.layout`` when configured, so rows match
    the real bus layout; falls back to a plain 4-across grid otherwise.

    Args:
        trajet: The trip whose vehicle and taken seats are read.

    Returns:
        Rows of ``{"numero": str, "libre": bool}`` dicts.
    """
    vehicule = trajet.vehicle
    libres = set(get_available_seats(vehicule, trajet))
    plan = vehicule.seat_plan or {}
    layout = plan.get("layout")

    if layout:
        rangees = layout
    else:
        tous = [str(i) for i in range(1, vehicule.total_seats + 1)]
        rangees = [tous[i : i + 4] for i in range(0, len(tous), 4)]

    return [
        [{"numero": str(siege), "libre": str(siege) in libres} for siege in rangee]
        for rangee in rangees
    ]


@login_required
@require_GET
def voyage(request: HttpRequest, pk: int) -> HttpResponse:
    """Trip detail with stop selection, seat map and a prefilled passenger form.

    Args:
        request: The incoming request.
        pk: The trip identifier.

    Returns:
        The rendered trip page.
    """
    trajet = _trajet_reservable(pk)
    form = PassagerConnecteForm(
        initial={
            "first_name": request.user.prenom,
            "last_name": request.user.nom,
            "phone": request.user.phone,
        }
    )
    return render(
        request,
        "espace/voyage.html",
        {
            "trajet": trajet,
            "escales": trajet.route.stops.select_related("city").all(),
            "plan_sieges": _plan_sieges(trajet),
            "form": form,
            "etape": 2,
        },
    )


@login_required
@require_http_methods(["POST"])
def reserver(request: HttpRequest, pk: int) -> HttpResponse:
    """Create the booking (full fare or a partial-fare stop) for the traveler.

    Args:
        request: The incoming request.
        pk: The trip identifier.

    Returns:
        A redirect to the payment step, or the form with its errors.
    """
    trajet = _trajet_reservable(pk)
    form = PassagerConnecteForm(request.POST)

    if not form.is_valid():
        return render(
            request,
            "espace/voyage.html",
            {
                "trajet": trajet,
                "escales": trajet.route.stops.select_related("city").all(),
                "form": form,
                "etape": 2,
            },
            status=400,
        )

    origin_city = trajet.route.origin_city
    destination_city = trajet.route.destination_city
    montant = trajet.price

    escale_id = form.cleaned_data.get("destination_stop")
    if escale_id:
        escale = get_object_or_404(RouteStop, pk=escale_id, route=trajet.route)
        destination_city = escale.city
        montant = escale.stop_price

    try:
        reservation = create_booking(
            {
                "trip": trajet,
                "first_name": form.cleaned_data["first_name"],
                "last_name": form.cleaned_data["last_name"],
                "phone": form.cleaned_data["phone"],
                "seat_number": form.cleaned_data.get("seat_number") or None,
                "amount": montant,
                "origin_city": origin_city,
                "destination_city": destination_city,
                "has_luggage": form.cleaned_data.get("has_luggage", False),
                "luggage_qty": form.cleaned_data.get("luggage_qty") or None,
                "user": request.user,
            }
        )
    except APIException as exc:
        messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        return redirect("web:espace-voyage", pk=pk)

    logger.info("Reservation %s creee depuis l'espace voyageur", reservation.ticket_number)
    return redirect("web:espace-paiement", pk=reservation.pk)


# --------------------------------------------------------------------------- #
# Ecrans 3 et 4 — Paiement et recu
# --------------------------------------------------------------------------- #
def _reservation_du_voyageur(request: HttpRequest, pk: int) -> Booking:
    """Load a booking, scoped to the current traveler.

    Args:
        request: The incoming request.
        pk: The booking identifier.

    Returns:
        The booking.

    Raises:
        Http404: If the booking is unknown or belongs to another user.
    """
    return get_object_or_404(
        Booking.objects.select_related(
            "trip__route__company",
            "trip__route__origin_city",
            "trip__route__destination_city",
        ),
        pk=pk,
        user=request.user,
    )


@login_required
@require_http_methods(["GET", "POST"])
def paiement(request: HttpRequest, pk: int) -> HttpResponse:
    """Payment method choice, then the self-service OTP confirmation step.

    Le parcours reprend l'etat existant de `payments.services` (le code de
    confirmation est envoye par SMS via `initiate_payment`/`start_otp_flow`,
    jamais genere par un flux USSD auto-compose : cf. CLAUDE.md « pas de
    logique Mobile Money directe »).

    Args:
        request: The incoming request.
        pk: The booking identifier.

    Returns:
        The rendered payment page, or a redirect once paid / for cash.
    """
    reservation = _reservation_du_voyageur(request, pk)

    if reservation.status == BookingStatus.PAID:
        return redirect("web:espace-billet", ticket_number=reservation.ticket_number)

    paiement_en_cours = (
        reservation.payments.filter(status=PaymentStatus.OTP_REQUIRED)
        .order_by("-created_at")
        .first()
    )

    if paiement_en_cours is not None:
        return _etape_otp(request, reservation, paiement_en_cours)

    moyens = _moyens_disponibles()
    form = PaiementMethodeForm(request.POST or None, moyens=moyens)

    if request.method == "POST" and form.is_valid():
        methode = form.cleaned_data["method"]
        try:
            reglement = initiate_payment(
                reservation,
                method=methode,
                phone=form.cleaned_data.get("payer_phone", ""),
            )
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        else:
            if methode == PaymentMethod.CASH:
                return redirect(
                    "web:espace-billet", ticket_number=reservation.ticket_number
                )
            return redirect("web:espace-paiement", pk=pk)

    return render(
        request,
        "espace/paiement.html",
        {
            "reservation": reservation,
            "trajet": reservation.trip,
            "form": form,
            "moyens": moyens,
            "otp_form": None,
            "etape": 3,
        },
    )


def _etape_otp(request: HttpRequest, reservation: Booking, reglement: Payment) -> HttpResponse:
    """Render and process the OTP entry step of the payment screen.

    Args:
        request: The incoming request.
        reservation: The booking being paid.
        reglement: The Mobile Money payment awaiting its code.

    Returns:
        The rendered OTP step, or a redirect to the receipt once confirmed.
    """
    if request.method == "POST" and request.POST.get("action") == "renvoyer":
        try:
            resend_payment_otp(reglement)
            messages.success(request, "Un nouveau code vous a ete envoye.")
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        return redirect("web:espace-paiement", pk=reservation.pk)

    otp_form = OtpForm(request.POST or None)
    if request.method == "POST" and request.POST.get("action") == "valider" and otp_form.is_valid():
        try:
            verify_payment_otp(reglement, otp_form.cleaned_data["code"])
        except (OtpExpired, OtpMaxAttemptsReached, OtpNotRequired, OtpResendTooSoon) as exc:
            messages.error(request, str(exc.detail))
            return redirect("web:espace-paiement", pk=reservation.pk)
        except OtpInvalid as exc:
            otp_form.add_error("code", str(exc.detail.get("otp", [exc.default_detail])[0]))
        except PaymentProviderError as exc:
            messages.error(request, str(exc.detail))
        else:
            return redirect("web:espace-recu", pk=reglement.pk)

    return render(
        request,
        "espace/paiement.html",
        {
            "reservation": reservation,
            "trajet": reservation.trip,
            "form": None,
            "moyens": None,
            "otp_form": otp_form,
            "reglement": reglement,
            "methode_libelle": MOYENS_LISIBLES.get(reglement.method, reglement.method),
            "etape": 3,
        },
    )


@login_required
@require_GET
def recu(request: HttpRequest, pk: int) -> HttpResponse:
    """Payment receipt (écran 4).

    Args:
        request: The incoming request.
        pk: The payment identifier.

    Returns:
        The rendered receipt.
    """
    reglement = get_object_or_404(
        Payment.objects.select_related(
            "booking__trip__route__company",
            "booking__trip__route__origin_city",
            "booking__trip__route__destination_city",
        ),
        pk=pk,
        booking__user=request.user,
    )
    return render(
        request,
        "espace/recu.html",
        {
            "reglement": reglement,
            "reservation": reglement.booking,
            "methode_libelle": MOYENS_LISIBLES.get(reglement.method, reglement.method),
        },
    )


# --------------------------------------------------------------------------- #
# Ecran 5 — Mes reservations
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def reservations(request: HttpRequest) -> HttpResponse:
    """List of the traveler's bookings, filterable by tab.

    Args:
        request: The incoming request.

    Returns:
        The rendered list, or a redirect after cancelling one.
    """
    if request.method == "POST" and request.POST.get("action") == "annuler":
        reservation = _reservation_du_voyageur(request, request.POST.get("pk"))
        try:
            cancel_booking(reservation, cancelled_by=request.user)
            messages.success(request, "Reservation annulee.")
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        return redirect("web:espace-reservations")

    maintenant = timezone.now()
    base = Booking.objects.filter(user=request.user).select_related(
        "trip__route__company",
        "trip__route__origin_city",
        "trip__route__destination_city",
    )

    onglets = {
        "a_venir": base.filter(
            status=BookingStatus.PAID, trip__departure_time__gte=maintenant
        ).exclude(trip__status=Trip.TripStatus.CANCELLED),
        "a_payer": base.filter(status=BookingStatus.PENDING),
        "passees": base.filter(status=BookingStatus.PAID, trip__departure_time__lt=maintenant),
        "annulees": base.filter(status__in=[BookingStatus.CANCELLED, BookingStatus.REFUNDED]),
    }
    onglet = request.GET.get("onglet", "a_venir")
    if onglet not in onglets:
        onglet = "a_venir"

    return render(
        request,
        "espace/reservations.html",
        {
            "reservations": onglets[onglet].order_by("-trip__departure_time"),
            "compteurs": {cle: qs.count() for cle, qs in onglets.items()},
            "onglet": onglet,
            "statuts": STATUTS_LISIBLES,
        },
    )


# --------------------------------------------------------------------------- #
# Ecran 6 — Mon billet
# --------------------------------------------------------------------------- #
@login_required
@require_GET
def billet(request: HttpRequest, ticket_number: str) -> HttpResponse:
    """The traveler's own ticket, looked up by its public ticket number.

    Args:
        request: The incoming request.
        ticket_number: The booking's ticket number.

    Returns:
        The rendered ticket page.
    """
    reservation = get_object_or_404(
        Booking.objects.select_related(
            "trip__route__company",
            "trip__route__origin_city",
            "trip__route__destination_city",
            "trip__route__origin_station",
            "trip__route__destination_station",
            "trip__vehicle",
        ),
        ticket_number=ticket_number,
        user=request.user,
    )
    return render(
        request,
        "espace/billet.html",
        {
            "reservation": reservation,
            "trajet": reservation.trip,
            "statut": STATUTS_LISIBLES.get(reservation.status, reservation.status),
        },
    )


# --------------------------------------------------------------------------- #
# Ecran 7 — Bagages
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def bagages(request: HttpRequest) -> HttpResponse:
    """Baggage declared on upcoming bookings, and the carrier's baggage policy.

    Args:
        request: The incoming request.

    Returns:
        The rendered baggage page.
    """
    maintenant = timezone.now()
    a_venir = (
        Booking.objects.filter(
            user=request.user,
            status=BookingStatus.PAID,
            trip__departure_time__gte=maintenant,
        )
        .exclude(trip__status=Trip.TripStatus.CANCELLED)
        .select_related("trip__route__company")
        .prefetch_related("baggage")
        .order_by("trip__departure_time")
    )

    if request.method == "POST":
        reservation = _reservation_du_voyageur(request, request.POST.get("pk"))
        form = BagageDeclarationForm(request.POST)
        if form.is_valid():
            reservation.has_luggage = form.cleaned_data["has_luggage"]
            reservation.luggage_qty = form.cleaned_data.get("luggage_qty") or None
            reservation.save(update_fields=["has_luggage", "luggage_qty", "updated_at"])
            messages.success(request, "Bagage mis a jour.")
        return redirect("web:espace-bagages")

    compagnies = {
        reservation.trip.route.company_id: reservation.trip.route.company
        for reservation in a_venir
    }

    return render(
        request,
        "espace/bagages.html",
        {"reservations": a_venir, "compagnies": compagnies.values()},
    )


# --------------------------------------------------------------------------- #
# Ecrans 8 et 9 — Reclamations
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def reclamations(request: HttpRequest) -> HttpResponse:
    """List of the traveler's claims, with accept / escalate actions.

    Args:
        request: The incoming request.

    Returns:
        The rendered list, or a redirect after an action.
    """
    if request.method == "POST":
        reclamation = get_object_or_404(Claim, pk=request.POST.get("pk"), user=request.user)
        action = request.POST.get("action")
        try:
            if action == "accepter":
                accept_claim_response(reclamation, request.user)
                messages.success(request, "Proposition acceptee.")
            elif action == "escalader":
                escalate_claim(reclamation)
                messages.success(request, "Reclamation transmise a TransBooking BF.")
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        return redirect("web:espace-reclamations")

    base = annotated_claims(Claim.objects.filter(user=request.user)).select_related(
        "company", "booking__trip__route__origin_city", "booking__trip__route__destination_city"
    )
    filtre = request.GET.get("statut", "toutes")
    if filtre == "en_cours":
        base = base.exclude(status__in=[ClaimStatus.RESOLVED, ClaimStatus.CLOSED])
    elif filtre == "resolues":
        base = base.filter(status__in=[ClaimStatus.RESOLVED, ClaimStatus.CLOSED])

    return render(
        request,
        "espace/reclamations.html",
        {"reclamations": unresolved_first(base), "filtre": filtre},
    )


@login_required
@require_http_methods(["GET", "POST"])
def nouvelle_reclamation(request: HttpRequest) -> HttpResponse:
    """New claim form, restricted to the traveler's own bookings.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the claim list on success, or the rendered form.
    """
    reservations_utilisateur = Booking.objects.filter(user=request.user).select_related(
        "trip__route__company", "trip__route__origin_city", "trip__route__destination_city"
    )
    booking_initial = request.GET.get("reservation")
    form = ReclamationForm(
        request.POST or None,
        request.FILES or None,
        initial={"booking": booking_initial} if booking_initial else None,
    )

    if request.method == "POST" and form.is_valid():
        booking = None
        if form.cleaned_data.get("booking"):
            booking = get_object_or_404(
                reservations_utilisateur, ticket_number=form.cleaned_data["booking"]
            )
        try:
            reclamation = create_claim(
                {
                    "booking": booking,
                    "claim_type": form.cleaned_data["claim_type"],
                    "subject": form.cleaned_data["subject"],
                    "description": form.cleaned_data["description"],
                },
                request.user,
            )
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        else:
            if form.cleaned_data.get("attachment"):
                add_claim_attachment(reclamation, form.cleaned_data["attachment"])
            messages.success(request, "Reclamation envoyee. Reponse attendue sous 48 heures.")
            return redirect("web:espace-reclamations")

    return render(
        request,
        "espace/nouvelle_reclamation.html",
        {"form": form, "reservations": reservations_utilisateur},
    )


# --------------------------------------------------------------------------- #
# Ecran 10 — Avis
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def avis(request: HttpRequest, trip_pk: int) -> HttpResponse:
    """Review form for a completed, paid trip.

    Args:
        request: The incoming request.
        trip_pk: The trip being reviewed.

    Returns:
        A redirect to the dashboard on success, or the rendered form.

    Raises:
        Http404: If the trip is not eligible for review by this user.
    """
    trajet = get_object_or_404(
        Trip.objects.select_related("route__company", "route__origin_city", "route__destination_city"),
        pk=trip_pk,
    )
    if not can_review(request.user, trajet):
        raise Http404

    form = AvisForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            create_review(
                {
                    "trip": trajet,
                    "rating": int(form.cleaned_data["rating"]),
                    "comment": form.cleaned_data.get("comment", ""),
                },
                request.user,
            )
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        else:
            messages.success(request, "Merci pour votre avis.")
            return redirect("web:espace-tableau-de-bord")

    return render(request, "espace/avis.html", {"trajet": trajet, "form": form})


# --------------------------------------------------------------------------- #
# Ecran 11 — Signalement d'exces de vitesse
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def signalement(request: HttpRequest) -> HttpResponse:
    """Speed report form, optionally tied to the traveler's ongoing trip.

    Args:
        request: The incoming request.

    Returns:
        A redirect to the dashboard on success, or the rendered form.
    """
    voyage_en_cours = (
        Booking.objects.filter(
            user=request.user, status=BookingStatus.PAID, trip__status=Trip.TripStatus.IN_PROGRESS
        )
        .select_related("trip__route__company", "trip__route__origin_city", "trip__route__destination_city")
        .order_by("-trip__departure_time")
        .first()
    )

    form = SignalementForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        trip = voyage_en_cours.trip if voyage_en_cours else None
        try:
            create_speed_report(
                {
                    "trip": trip,
                    "company": trip.route.company if trip else None,
                    "severity": form.cleaned_data.get("severity") or None,
                    "description": form.cleaned_data.get("description", ""),
                },
                request.user,
            )
        except APIException as exc:
            messages.error(request, str(exc.detail if hasattr(exc, "detail") else exc))
        else:
            messages.success(request, "Signalement envoye.")
            return redirect("web:espace-tableau-de-bord")

    return render(
        request, "espace/signalement.html", {"form": form, "voyage_en_cours": voyage_en_cours}
    )


# --------------------------------------------------------------------------- #
# Ecran 12 — Profil
# --------------------------------------------------------------------------- #
@login_required
@require_http_methods(["GET", "POST"])
def profil(request: HttpRequest) -> HttpResponse:
    """Traveler profile: identity, notification preferences and password.

    Args:
        request: The incoming request.

    Returns:
        The rendered profile page.
    """
    utilisateur = request.user
    form = ProfilForm(
        request.POST if request.POST.get("action") == "profil" else None,
        initial={
            "prenom": utilisateur.prenom,
            "nom": utilisateur.nom,
            "email": utilisateur.email,
            "notify_departure_reminder": utilisateur.notify_departure_reminder,
            "notify_parcel_arrival": utilisateur.notify_parcel_arrival,
            "notify_marketing": utilisateur.notify_marketing,
        },
    )
    mot_de_passe_form = MotDePasseForm(
        request.POST if request.POST.get("action") == "mot_de_passe" else None,
        user=utilisateur,
    )

    if request.method == "POST" and request.POST.get("action") == "profil" and form.is_valid():
        for champ in (
            "prenom",
            "nom",
            "email",
            "notify_departure_reminder",
            "notify_parcel_arrival",
            "notify_marketing",
        ):
            setattr(utilisateur, champ, form.cleaned_data[champ])
        utilisateur.save(
            update_fields=[
                "prenom",
                "nom",
                "email",
                "notify_departure_reminder",
                "notify_parcel_arrival",
                "notify_marketing",
                "updated_at",
            ]
        )
        messages.success(request, "Profil mis a jour.")
        return redirect("web:espace-profil")

    if (
        request.method == "POST"
        and request.POST.get("action") == "mot_de_passe"
        and mot_de_passe_form.is_valid()
    ):
        change_password(utilisateur, mot_de_passe_form.cleaned_data["new_password"])
        messages.success(request, "Mot de passe modifie.")
        return redirect("web:espace-profil")

    if request.method == "POST" and request.POST.get("action") == "supprimer":
        # Desactivation, pas de suppression reelle ni d'anonymisation : hors
        # perimetre de cette premiere version (cf. plan).
        utilisateur.is_active = False
        utilisateur.save(update_fields=["is_active", "updated_at"])
        logout(request)
        messages.info(request, "Votre compte a ete desactive.")
        return redirect("web:accueil")

    return render(
        request,
        "espace/profil.html",
        {
            "form": form,
            "mot_de_passe_form": mot_de_passe_form,
            "voyages_count": utilisateur.bookings.filter(status=BookingStatus.PAID).count(),
            "avis_count": utilisateur.reviews.count(),
        },
    )
