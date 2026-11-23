"""Deutsche Preisangaben in Zahlen umwandeln, ohne je abzustürzen."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_NUMBER = re.compile(r"\d[\d.,]*")
_THOUSANDS_DOTS = re.compile(r"\d{1,3}(\.\d{3})+")


def parse_price(text: str) -> tuple[Decimal | None, bool]:
    """Gibt (Preis, Verhandlungsbasis) zurück. „Zu verschenken“ ist 0, Unbekanntes ist None."""
    text = " ".join(text.split())
    negotiable = re.search(r"\bVB\b", text) is not None
    if "verschenken" in text.lower():
        return Decimal("0"), negotiable
    match = _NUMBER.search(text)
    if not match:
        return None, negotiable
    token = match.group().rstrip(".,")
    if "," in token:
        token = token.replace(".", "").replace(",", ".")
    elif _THOUSANDS_DOTS.fullmatch(token):
        token = token.replace(".", "")
    try:
        return Decimal(token), negotiable
    except InvalidOperation:
        return None, negotiable
