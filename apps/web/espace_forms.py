"""Formulaires de l'espace voyageur connecte."""
from django import forms
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError

from apps.claims.models import ClaimType
from apps.speed_reports.models import SpeedReportSeverity


class PassagerConnecteForm(forms.Form):
    """Identite du passager, siege et bagage — etape « Reservation » (ecran 2).

    Pre-rempli depuis le profil du voyageur connecte ; contrairement au tunnel
    anonyme (`web.forms.PassagerForm`), porte aussi le choix de l'escale de
    descente et la declaration de bagage.
    """

    first_name = forms.CharField(label="Prenom", max_length=100, strip=True)
    last_name = forms.CharField(label="Nom", max_length=100, strip=True)
    phone = forms.CharField(label="Telephone", max_length=30)
    seat_number = forms.CharField(label="Siege", max_length=10, required=False)
    # Vide = destination finale du trajet ; sinon identifiant d'une escale
    # (`routes.RouteStop.pk`) — la vue calcule le tarif partiel correspondant.
    destination_stop = forms.CharField(required=False)
    has_luggage = forms.BooleanField(label="J'ai un bagage en soute", required=False)
    luggage_qty = forms.IntegerField(
        label="Nombre de bagages", required=False, min_value=1
    )

    def clean_phone(self) -> str:
        brut = "".join(c for c in self.cleaned_data["phone"] if c.isdigit())
        if brut.startswith("226"):
            brut = brut[3:]
        brut = brut.lstrip("0")
        if len(brut) != 8:
            raise forms.ValidationError(
                "Un numero burkinabe compte huit chiffres, par exemple 70 12 34 56."
            )
        return f"+226{brut}"


class PaiementMethodeForm(forms.Form):
    """Choix du moyen de paiement — etape 1 de l'ecran « Paiement »."""

    method = forms.ChoiceField(label="Moyen de paiement", choices=())
    payer_phone = forms.CharField(
        label="Numero a debiter", max_length=30, required=False
    )

    def __init__(self, *args, moyens=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["method"].choices = moyens or []


class OtpForm(forms.Form):
    """Code de confirmation a six chiffres — etape 3 de l'ecran « Paiement »."""

    code = forms.CharField(label="Code recu", max_length=10, min_length=4)


class BagageDeclarationForm(forms.Form):
    """Declaration de bagage du voyageur (ecran « Bagages »).

    Met seulement a jour `Booking.has_luggage`/`luggage_qty` : le pesage et
    l'etiquetage restent une operation d'agent au guichet (`register_baggage`).
    """

    has_luggage = forms.BooleanField(required=False)
    luggage_qty = forms.IntegerField(required=False, min_value=1)


class ReclamationForm(forms.Form):
    """Depot d'une reclamation (ecran « Nouvelle reclamation »)."""

    booking = forms.CharField(required=False)  # ticket_number, valide en vue
    claim_type = forms.ChoiceField(label="Motif", choices=ClaimType.choices)
    subject = forms.CharField(label="Objet", max_length=200)
    description = forms.CharField(
        label="Description", widget=forms.Textarea, max_length=1000
    )
    attachment = forms.FileField(label="Piece jointe", required=False)


class AvisForm(forms.Form):
    """Depot d'un avis (ecran « Avis »)."""

    RATING_CHOICES = [(i, str(i)) for i in range(1, 6)]

    rating = forms.ChoiceField(label="Note globale", choices=RATING_CHOICES)
    comment = forms.CharField(
        label="Commentaire", widget=forms.Textarea, max_length=600, required=False
    )


class SignalementForm(forms.Form):
    """Signalement d'exces de vitesse (ecran « Signalement »)."""

    trip = forms.CharField(required=False)  # pk du voyage en cours, optionnel
    severity = forms.ChoiceField(
        label="Gravite", choices=SpeedReportSeverity.choices, required=False
    )
    description = forms.CharField(
        label="Observation", widget=forms.Textarea, max_length=1000, required=False
    )


class ProfilForm(forms.Form):
    """Edition de l'identite et des preferences de notification (ecran « Profil »)."""

    prenom = forms.CharField(label="Prenom", max_length=100, strip=True)
    nom = forms.CharField(label="Nom", max_length=100, strip=True)
    email = forms.EmailField(label="E-mail", required=False)
    notify_departure_reminder = forms.BooleanField(required=False)
    notify_parcel_arrival = forms.BooleanField(required=False)
    notify_marketing = forms.BooleanField(required=False)


class MotDePasseForm(forms.Form):
    """Changement de mot de passe (ecran « Profil »)."""

    old_password = forms.CharField(label="Mot de passe actuel", widget=forms.PasswordInput)
    new_password = forms.CharField(label="Nouveau mot de passe", widget=forms.PasswordInput)

    def __init__(self, *args, user=None, **kwargs):
        self._user = user
        super().__init__(*args, **kwargs)

    def clean_old_password(self) -> str:
        valeur = self.cleaned_data["old_password"]
        if self._user is not None and not self._user.check_password(valeur):
            raise forms.ValidationError("Mot de passe actuel incorrect.")
        return valeur

    def clean_new_password(self) -> str:
        valeur = self.cleaned_data["new_password"]
        try:
            validate_password(valeur, user=self._user)
        except DjangoValidationError as exc:
            raise forms.ValidationError(list(exc.messages)) from exc
        return valeur
