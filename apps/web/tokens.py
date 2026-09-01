"""Liens de suivi d'une reservation, non devinables.

Le numero de billet est sequentiel (``BF2026001234``) : une page accessible par
ce seul numero laisserait n'importe qui parcourir les billets des autres en
incrementant un compteur. Chaque URL du tunnel et du billet porte donc une
signature derivee de ``SECRET_KEY``.

Pas d'expiration : le lien du billet part par SMS et doit rester ouvrable le
jour du voyage, voire apres pour la reclamation.
"""
from django.core import signing

SEL = "transbooking.web.reservation"


def jeton(booking_id: int) -> str:
    """Return the signature protecting a booking's public URLs.

    Args:
        booking_id: The booking primary key.

    Returns:
        The signature (without the value itself).
    """
    return signing.Signer(salt=SEL).signature(str(booking_id))


def jeton_valide(booking_id: int, valeur: str) -> bool:
    """Check a signature against a booking id.

    Args:
        booking_id: The booking primary key taken from the URL.
        valeur: The signature taken from the URL.

    Returns:
        True when the signature matches.
    """
    return signing.constant_time_compare(jeton(booking_id), valeur or "")
