import base64
from io import BytesIO

import qrcode


def generate_qr(data: str) -> str:
    """Generate a base64-encoded PNG QR code.

    Args:
        data: Data encoded in the QR code.

    Returns:
        Base64-encoded PNG image string.
    """
    image = qrcode.make(data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
