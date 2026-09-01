import logging

from django.conf import settings


logger = logging.getLogger(__name__)


def send_sms(phone: str, message: str) -> None:
    """Send an SMS message.

    Args:
        phone: Recipient phone number.
        message: Message body.
    """
    if settings.DEBUG or settings.SMS_PROVIDER == "console":
        print(f"SMS console provider to {phone}: {message}")
        logger.info("SMS console provider to %s: %s", phone, message)
        return

    logger.warning("SMS provider %s is not implemented yet.", settings.SMS_PROVIDER)
