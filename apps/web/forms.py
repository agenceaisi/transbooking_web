"""Formulaires du tunnel de reservation."""
from django import forms


class PassagerForm(forms.Form):
    """Identite du passager et siege souhaite.

    Volontairement court : chaque champ supplementaire coute des reservations
    abandonnees. Le sexe et la piece d'identite existent dans le modele mais ne
    sont pas demandes en ligne — l'agent les releve a l'embarquement quand la
    compagnie l'exige.
    """

    first_name = forms.CharField(
        label="Prenom", max_length=100, strip=True,
    )
    last_name = forms.CharField(
        label="Nom", max_length=100, strip=True,
    )
    phone = forms.CharField(
        label="Telephone",
        max_length=30,
        help_text="Le billet et les alertes de depart arrivent sur ce numero.",
    )
    seat_number = forms.CharField(
        label="Siege", max_length=10, required=False,
    )

    def clean_phone(self) -> str:
        """Normalise a Burkinabe phone number.

        On accepte ce que les gens tapent — espaces, indicatif, zero initial —
        et on range en format international. Refuser une saisie pour un espace
        de trop est le genre de detail qui fait abandonner un achat.

        Returns:
            The number in ``+226XXXXXXXX`` form.

        Raises:
            ValidationError: If the number is not eight local digits.
        """
        brut = "".join(c for c in self.cleaned_data["phone"] if c.isdigit())
        if brut.startswith("226"):
            brut = brut[3:]
        brut = brut.lstrip("0")
        if len(brut) != 8:
            raise forms.ValidationError(
                "Un numero burkinabe compte huit chiffres, par exemple 70 12 34 56."
            )
        return f"+226{brut}"


class PaiementForm(forms.Form):
    """Choix du moyen de paiement.

    Les choix ne sont pas figes : ils viennent des moyens actives sur la
    plateforme. Un operateur qu'on n'a pas encore contractualise ne doit pas
    apparaitre, meme grise.
    """

    method = forms.ChoiceField(label="Moyen de paiement", choices=())
    payer_phone = forms.CharField(
        label="Numero a debiter", max_length=30, required=False,
    )

    def __init__(self, *args, moyens=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = moyens or []
