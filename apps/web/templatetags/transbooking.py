"""Filtres de mise en forme propres au Burkina Faso.

Les conventions viennent du systeme de design : montants entiers separes par
une espace insecable, heures sur 24 h, durees ecrites « 5 h 30 ». Elles sont
regroupees ici plutot que repetees dans chaque gabarit — un montant mal
formate sur une page de paiement inquiete plus qu'il n'informe.
"""
from django import template
from django.utils.safestring import mark_safe

from apps.vehicles.services import COMFORT_BY_TIER

register = template.Library()

#: Espace insecable : « 6 500 FCFA » ne doit jamais se couper en fin de ligne.
INSECABLE = " "


@register.filter
def fcfa(valeur) -> str:
    """Format an amount in whole CFA francs.

    Le franc CFA n'a pas de subdivision : les decimales du modele sont
    toujours nulles et n'ont rien a faire a l'ecran.

    Args:
        valeur: The amount, as a number or numeric string.

    Returns:
        The grouped amount, e.g. ``6 500``. The raw value is returned
        unchanged when it cannot be read — mieux vaut un montant brut qu'un
        montant faux.
    """
    try:
        entier = int(round(float(valeur)))
    except (TypeError, ValueError):
        return str(valeur)

    signe = "-" if entier < 0 else ""
    chiffres = str(abs(entier))
    tranches = []
    while len(chiffres) > 3:
        tranches.insert(0, chiffres[-3:])
        chiffres = chiffres[:-3]
    tranches.insert(0, chiffres)
    return signe + INSECABLE.join(tranches)


@register.filter
def duree(minutes) -> str:
    """Format a duration in hours and minutes.

    Args:
        minutes: The duration in minutes.

    Returns:
        ``5 h 30``, or an empty string when unknown.
    """
    try:
        total = int(minutes)
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    heures, reste = divmod(total, 60)
    if not heures:
        return f"{reste}{INSECABLE}min"
    return f"{heures}{INSECABLE}h{INSECABLE}{reste:02d}"


@register.filter
def duree_entre(depart, arrivee) -> str:
    """Format the gap between two datetimes.

    Args:
        depart: The departure time.
        arrivee: The arrival time, possibly None.

    Returns:
        The formatted duration, or an empty string.
    """
    if not depart or not arrivee:
        return ""
    return duree(int((arrivee - depart).total_seconds() // 60))


@register.filter
def initiales(nom: str) -> str:
    """Return up to four letters standing in for a company logo.

    Args:
        nom: The company name or acronym.

    Returns:
        The shortened mark.
    """
    propre = (nom or "").strip()
    if not propre:
        return "?"
    if len(propre) <= 4:
        return propre.upper()
    mots = propre.split()
    if len(mots) > 1:
        sigle = "".join(m[0] for m in mots[:4]).upper()
        # « STAF Transport » donnerait « ST », qu'aucun voyageur ne reconnait.
        # En dessous de trois lettres, le premier mot est plus parlant.
        if len(sigle) >= 3:
            return sigle
    return propre.split()[0][:4].upper()


#: Indigo de la marque, servant de repli quand une compagnie n'a pas choisi de
#: couleur — ou en a choisi une que l'on refuse.
COULEUR_DEFAUT = "#1B2A4A"


@register.filter
def cle(mapping: dict, valeur):
    """Look up a dict value from a template — Django has no builtin for it.

    Used to resolve the accented, human-facing status labels the code
    deliberately keeps out of model `choices` (cf. `web.views.STATUTS_LISIBLES`).

    Args:
        mapping: The dict to look up.
        valeur: The key to resolve.

    Returns:
        ``mapping[valeur]``, or ``valeur`` unchanged when absent.
    """
    if not isinstance(mapping, dict):
        return valeur
    return mapping.get(valeur, valeur)


@register.filter
def prenom_initiale(user) -> str:
    """Display a traveler as first name + last initial, e.g. « Aminata T. ».

    Used wherever a traveler's name appears on a public page (testimonials) :
    a full name is more than the page needs to show.

    Args:
        user: The traveler.

    Returns:
        ``"Prénom N."``, or ``"Voyageur"`` when the name is unknown.
    """
    prenom = getattr(user, "prenom", "") or ""
    nom = getattr(user, "nom", "") or ""
    if not prenom:
        return "Voyageur"
    if not nom:
        return prenom
    return f"{prenom} {nom[0].upper()}."


@register.filter
def masquer_telephone(numero: str) -> str:
    """Mask all but the last two digits of a phone number for public display.

    Mirrors ``apps.parcels.serializers._mask_phone`` — the parcel-tracking
    widget on the public site shows exactly what the public tracking API
    shows, never the sender/recipient's full number.

    Args:
        numero: The phone number.

    Returns:
        The masked number, e.g. ``**********01``.
    """
    if not numero:
        return ""
    visible = numero[-2:]
    return f"{'*' * max(len(numero) - 2, 0)}{visible}"


@register.filter
def etoiles(note) -> str:
    """Render a rating out of 5 as filled/empty star glyphs.

    Args:
        note: The rating, from 0 to 5 (accepts ``None``, treated as 0).

    Returns:
        Five ``★`` characters, the ones beyond the rounded rating wrapped in
        ``<span class="v">`` (dimmed by the ``.etoiles .v`` rule).
    """
    try:
        pleines = round(float(note))
    except (TypeError, ValueError):
        pleines = 0
    pleines = max(0, min(5, pleines))
    glyphes = ["★" if i < pleines else '<span class="v">★</span>' for i in range(5)]
    return mark_safe("".join(glyphes))


#: Traits interieurs des pictogrammes de confort — meme grammaire que les
#: icones du chrome (trait 2, bouts et jonctions arrondis, sans remplissage).
#: Stockes sans <svg> englobant : la taille se decide en CSS (badge de ligne
#: vs. liste detaillee de la fenetre au survol), jamais ici.
_TRAITS_CONFORT = {
    "clim": '<path d="M12 2v20M4.5 6.5l15 11M19.5 6.5l-15 11"/>'
    '<path d="M9 3.5 12 6l3-2.5M9 20.5 12 18l3 2.5M3.5 9l3 3-3 3M20.5 9l-3 3 3 3"/>',
    "prises": '<path d="M9 2v4M15 2v4M7 8h10v4a5 5 0 0 1-5 5 5 5 0 0 1-5-5V8Z"/><path d="M12 17v5"/>',
    "wifi": '<path d="M2 8.5a15 15 0 0 1 20 0"/><path d="M5.5 12.3a10 10 0 0 1 13 0"/>'
    '<path d="M9 16.1a5 5 0 0 1 6 0"/><circle cx="12" cy="19.5" r="1.1" fill="currentColor" stroke="none"/>',
    "toilettes": '<circle cx="12" cy="5" r="2.2"/>'
    '<path d="M8 21v-7H6l1.4-5.7A2 2 0 0 1 9.3 7h5.4a2 2 0 0 1 1.9 1.3L18 14h-2v7"/>'
    '<path d="M10 14v7M14 14v7"/>',
    "collation": '<path d="M6 8h11l-1 8a3 3 0 0 1-3 2.6h-3A3 3 0 0 1 7 16L6 8Z"/>'
    '<path d="M17 9h1.5a2.5 2.5 0 0 1 0 5H17"/><path d="M9 4.3c.5-1 1.5-1 2 0M13 4.3c.5-1 1.5-1 2 0"/>',
    "divertissement": '<rect x="3" y="4" width="18" height="12" rx="1.6"/><path d="M8 20h8M12 16v4"/>',
    "sieges": '<path d="M5 12V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v3"/>'
    '<path d="M5 12h11a2 2 0 0 1 2 2v2H7a2 2 0 0 1-2-2v-2Z"/><path d="M5 16v3M18 16v3"/>',
    "bagages": '<rect x="4" y="8" width="16" height="11" rx="2"/><path d="M9 8V6a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2M4 13h16"/>',
}

#: Libelle affiche a cote de (ou a la place de) chaque pictogramme.
_LIBELLES_CONFORT = {
    "clim": "Climatisation",
    "prises": "Prises & USB",
    "wifi": "Wi-Fi à bord",
    "toilettes": "Toilettes à bord",
    "collation": "Collation offerte",
    "divertissement": "Écran multimédia",
    "sieges": "Sièges inclinables",
    "bagages": "Bagages en soute",
}

_LIBELLE_PALIER = {"standard": "Standard", "vip": "VIP", "vvip": "VVIP"}
_DESCRIPTION_PALIER = {
    "standard": "Car classique : sièges numérotés, climatisation et bagages en soute.",
    "vip": "Sièges plus larges, climatisation renforcée, prises et Wi-Fi à bord.",
    "vvip": "Le haut de gamme : sièges inclinables, collation, écran multimédia et toilettes à bord.",
}


def _svg_confort(code: str, taille: int) -> str:
    traits = _TRAITS_CONFORT.get(code, "")
    return (
        f'<svg width="{taille}" height="{taille}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{traits}</svg>'
    )


@register.filter
def confort(vehicle_type: str):
    """List the comfort amenities implied by a vehicle's tier.

    Args:
        vehicle_type: The raw ``Vehicle.vehicle_type`` value (``standard``,
            ``vip`` or ``vvip``).

    Returns:
        A list of ``{"code", "libelle", "icone"}`` dicts, richest tier first
        in insertion order — ``icone`` is a 18 px inline SVG, safe to render.
    """
    codes = COMFORT_BY_TIER.get(
        (vehicle_type or "").lower(), COMFORT_BY_TIER["standard"]
    )
    return [
        {
            "code": code,
            "libelle": _LIBELLES_CONFORT[code],
            "icone": mark_safe(_svg_confort(code, 18)),
        }
        for code in codes
    ]


@register.filter
def palier(vehicle_type: str) -> str:
    """Return the human-facing tier label, e.g. ``VIP``.

    Args:
        vehicle_type: The raw ``Vehicle.vehicle_type`` value.

    Returns:
        ``Standard``, ``VIP`` or ``VVIP``.
    """
    return _LIBELLE_PALIER.get((vehicle_type or "").lower(), _LIBELLE_PALIER["standard"])


@register.filter
def palier_description(vehicle_type: str) -> str:
    """Return a one-sentence description of a vehicle tier's comfort level.

    Args:
        vehicle_type: The raw ``Vehicle.vehicle_type`` value.

    Returns:
        The description shown in the vehicle's hover detail window.
    """
    return _DESCRIPTION_PALIER.get(
        (vehicle_type or "").lower(), _DESCRIPTION_PALIER["standard"]
    )


@register.filter
def couleur_sure(valeur) -> str:
    """Return a company colour only when it is a plain hexadecimal code.

    La couleur vient du profil d'une compagnie, donc d'une saisie exterieure,
    et finit dans un attribut ``style``. Django echappe les guillemets, ce qui
    empeche de sortir de l'attribut, mais on ne laisse pas pour autant une
    chaine arbitraire entrer dans une feuille de style : seul ``#RRGGBB`` ou
    ``#RGB`` passe.

    Args:
        valeur: The stored colour.

    Returns:
        The colour, or the brand indigo.
    """
    texte = (valeur or "").strip()
    if len(texte) in (4, 7) and texte.startswith("#"):
        if all(c in "0123456789abcdefABCDEF" for c in texte[1:]):
            return texte
    return COULEUR_DEFAUT


# ============================================================================
# Rail de filtres — bascule d'un critere dans l'URL courante.
#
# La page de resultats reste un GET pur (pas de JS pour poser un filtre) :
# chaque case a cocher est un lien qui ajoute ou retire une valeur du
# parametre de requete, tout le reste de l'URL — date, autres filtres, tri —
# passe inchange. `request.GET.copy()` porte deja tout ca ; ces tags ne font
# que muter une (ou deux) cle(s) avant de re-encoder.
# ============================================================================
@register.simple_tag(takes_context=True)
def lien_valeur(context, cle: str, valeur) -> str:
    """Set a query parameter unconditionally (never a toggle).

    Used for navigation that always lands on a specific value — changer de
    jour, changer de tri — jamais pour une case a cocher : re-cliquer sur le
    jour ou le tri deja actif ne doit rien effacer.

    Args:
        context: The template context (reads ``request`` for the current URL).
        cle: The query parameter name, e.g. ``"date"`` or ``"tri"``.
        valeur: The value to set.

    Returns:
        The current URL's query string with that one parameter set.
    """
    requete = context["request"]
    params = requete.GET.copy()
    params[cle] = valeur
    return f"?{params.urlencode()}"


@register.simple_tag(takes_context=True)
def lien_compagnie(context, valeur, options) -> str:
    """Toggle one company, starting from an "every company checked" baseline.

    Contrairement aux autres facettes du rail (decochees par defaut = aucune
    restriction), la compagnie demarre **tout coché** : ne rien avoir choisi
    revient a n'exclure personne (cf. capture de reference). Decocher une
    compagnie doit donc construire la liste explicite de toutes les autres,
    pas ajouter une valeur a une liste qui serait sinon vide.

    Args:
        context: The template context (reads ``request`` for the current URL).
        valeur: The company id being toggled.
        options: The full list of company facet options (each exposing
            ``id``), needed to expand the implicit "everyone" baseline.

    Returns:
        The current URL's query string with that one company toggled.
    """
    requete = context["request"]
    valeur = str(valeur)
    toutes = [str(option["id"]) for option in options]
    actives = requete.GET.getlist("compagnie") or toutes
    if valeur in actives:
        actives = [v for v in actives if v != valeur]
    else:
        actives = [*actives, valeur]

    params = requete.GET.copy()
    if set(actives) == set(toutes):
        # De retour a « tout coché » : redevenir l'etat implicite (aucun
        # parametre) plutot que lister explicitement toutes les compagnies.
        params.pop("compagnie", None)
    else:
        params.setlist("compagnie", actives)
    return f"?{params.urlencode()}"


@register.simple_tag(takes_context=True)
def lien_facette(context, cle: str, valeur) -> str:
    """Toggle one value in or out of a multi-valued filter parameter.

    Args:
        context: The template context (reads ``request`` for the current URL).
        cle: The query parameter name, e.g. ``"compagnie"``.
        valeur: The value to add when absent, remove when present.

    Returns:
        The current URL's query string with that one change — every other
        parameter, including repeats of ``cle``, untouched.
    """
    requete = context["request"]
    valeur = str(valeur)
    valeurs = requete.GET.getlist(cle)
    if valeur in valeurs:
        valeurs = [v for v in valeurs if v != valeur]
    else:
        valeurs = [*valeurs, valeur]

    params = requete.GET.copy()
    params.setlist(cle, valeurs)
    return f"?{params.urlencode()}"


@register.simple_tag(takes_context=True)
def lien_scalaire(context, cle: str, valeur) -> str:
    """Toggle a single-valued filter parameter — set it, or clear it if active.

    Args:
        context: The template context (reads ``request`` for the current URL).
        cle: The query parameter name, e.g. ``"heure"``.
        valeur: The value to set. Clicking the already-active value clears it.

    Returns:
        The current URL's query string with that one change.
    """
    requete = context["request"]
    valeur = str(valeur)
    params = requete.GET.copy()
    if params.get(cle) == valeur:
        params.pop(cle, None)
    else:
        params[cle] = valeur
    return f"?{params.urlencode()}"


@register.simple_tag(takes_context=True)
def lien_sans(context, *cles: str) -> str:
    """Build the current URL with the given query parameters removed.

    Used by each filter group's « Tout » reset link.

    Args:
        context: The template context (reads ``request`` for the current URL).
        cles: The parameter names to drop.

    Returns:
        The current URL's query string without those parameters.
    """
    requete = context["request"]
    params = requete.GET.copy()
    for cle in cles:
        params.pop(cle, None)
    return f"?{params.urlencode()}"
