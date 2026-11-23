from decimal import Decimal

import pytest

from sniper.platforms.prices import parse_price


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45 €", (Decimal("45"), False)),
        ("45 € VB", (Decimal("45"), True)),
        ("VB", (None, True)),
        ("1.250 €", (Decimal("1250"), False)),
        ("12,50 €", (Decimal("12.50"), False)),
        ("1.250,99 € VB", (Decimal("1250.99"), True)),
        ("Zu verschenken", (Decimal("0"), False)),
        ("", (None, False)),
        ("  45 €\n VB ", (Decimal("45"), True)),
        ("1.250", (Decimal("1250"), False)),
        ("12.5", (Decimal("12.5"), False)),
        ("45", (Decimal("45"), False)),
        ("Preis auf Anfrage", (None, False)),
        ("€ 1.000.000", (Decimal("1000000"), False)),
    ],
)
def test_parse_price(text, expected):
    assert parse_price(text) == expected
