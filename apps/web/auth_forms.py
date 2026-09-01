"""Formulaires de connexion et d'inscription du voyageur."""
from django import forms


def _normalise_telephone(brut: str) -> str:
    """Normalise a Burkinabe phone number to its ``+226XXXXXXXX`` form.

    Args:
        brut: The raw, user-typed phone number.

    Returns:
        The number in ``+226XXXXXXXX`` form.

    Raises:
        forms.ValidationError: If the number is not eight local digits.
    """
    chiffres = "".join(c for c in brut if c.isdigit())
    if chiffres.startswith("226"):
        chiffres = chiffres[3:]
    chiffres = chiffres.lstrip("0")
    if len(chiffres) != 8:
        raise forms.ValidationError(
            "Un numero burkinabe compte huit chiffres, par exemple 70 12 34 56."
        )
    return f"+226{chiffres}"


class ConnexionForm(forms.Form):
    """Identifiants de connexion (telephone + mot de passe)."""

    phone = forms.CharField(label="Telephone", max_length=30)
    password = forms.CharField(label="Mot de passe", widget=forms.PasswordInput)

    def clean_phone(self) -> str:
        return _normalise_telephone(self.cleaned_data["phone"])


class InscriptionForm(forms.Form):
    """Creation d'un compte voyageur."""

    prenom = forms.CharField(label="Prenom", max_length=100, strip=True)
    nom = forms.CharField(label="Nom", max_length=100, strip=True)
    phone = forms.CharField(label="Telephone", max_length=30)
    email = forms.EmailField(label="E-mail", required=False)
    password = forms.CharField(
        label="Mot de passe", widget=forms.PasswordInput, min_length=8
    )

    def clean_phone(self) -> str:
        return _normalise_telephone(self.cleaned_data["phone"])
