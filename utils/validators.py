import re

from django.core.exceptions import ValidationError

# Format burkinabè : +226 suivi de 8 chiffres, ou 0 suivi de 8 chiffres.
PHONE_BF_PATTERN = re.compile(r"^(\+226|0)[0-9]{8}$")


def validate_phone_bf(value: str) -> None:
    """Validate a Burkina Faso phone number.

    Accepts the international form (+226XXXXXXXX) or the local form (0XXXXXXXX).

    Args:
        value: The phone number to validate.

    Raises:
        ValidationError: If the number does not match the expected format.
    """
    if not PHONE_BF_PATTERN.match(value or ""):
        raise ValidationError(
            "Numero de telephone invalide. Format attendu : +22670000000 ou 070000000"
        )
