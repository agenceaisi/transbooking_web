from rest_framework import status
from rest_framework.exceptions import APIException


class PaymentAlreadyConfirmed(APIException):
    """Le paiement est deja confirme (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Ce paiement est deja confirme."
    default_code = "payment_already_confirmed"


class TransactionRefRequired(APIException):
    """Reference de transaction manquante pour un paiement non especes (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Reference de transaction requise hors especes."
    default_code = "transaction_ref_required"


class BookingAlreadyPaid(APIException):
    """La reservation est deja reglee (HTTP 409)."""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "Cette reservation est deja reglee."
    default_code = "booking_already_paid"


class OtpNotRequired(APIException):
    """Le paiement n'attend pas de code OTP (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Ce paiement n'attend pas de code de confirmation."
    default_code = "otp_not_required"


class OtpExpired(APIException):
    """Le code de confirmation a expire (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Le code de confirmation a expire. Relancez un paiement."
    default_code = "otp_expired"


class OtpMaxAttemptsReached(APIException):
    """Nombre maximal de tentatives OTP atteint (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = (
        "Nombre maximal de tentatives atteint. Le paiement a echoue, "
        "relancez un paiement."
    )
    default_code = "otp_max_attempts"


class OtpInvalid(APIException):
    """Code de confirmation errone (HTTP 400).

    Expose le nombre de tentatives restantes via ``extra_detail`` : DRF
    convertirait un entier place dans ``detail`` en chaine de caracteres
    (cf. utils.exceptions.custom_exception_handler).
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "otp_invalid"

    def __init__(self, attempts_remaining: int):
        self.attempts_remaining = attempts_remaining
        self.extra_detail = {"attempts_remaining": attempts_remaining}
        super().__init__(
            {
                "otp": [
                    f"Code incorrect. Il vous reste {attempts_remaining} tentative(s)."
                ]
            }
        )


class OtpResendTooSoon(APIException):
    """Renvoi d'OTP demande trop tot (HTTP 429)."""

    status_code = status.HTTP_429_TOO_MANY_REQUESTS
    default_detail = "Patientez avant de demander un nouveau code."
    default_code = "otp_resend_too_soon"


class PaymentProviderError(APIException):
    """L'operateur Mobile Money a refuse ou n'a pas repondu (HTTP 400)."""

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Paiement refuse par l'operateur Mobile Money."
    default_code = "payment_provider_error"


class PaymentProviderNotConfigured(APIException):
    """Aucun fournisseur Mobile Money exploitable (HTTP 503)."""

    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = "Le paiement Mobile Money est momentanement indisponible."
    default_code = "payment_provider_not_configured"


class PaymentFlowNotSupported(PaymentProviderError):
    """Le fournisseur n'implemente pas ce parcours de paiement (HTTP 400).

    Levee lorsqu'un paiement par redirection est demande a un fournisseur OTP,
    ou l'inverse. C'est une erreur de configuration, pas une erreur du payeur.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Ce moyen de paiement n'accepte pas ce parcours."
    default_code = "payment_flow_not_supported"


class PaymentWebhookSignatureInvalid(APIException):
    """Notification d'operateur a signature invalide (HTTP 400).

    Soit une erreur de configuration apres rotation de cle, soit une tentative
    d'injection. Dans les deux cas la notification est journalisee avant d'etre
    rejetee.
    """

    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Signature de notification invalide."
    default_code = "webhook_signature_invalid"
