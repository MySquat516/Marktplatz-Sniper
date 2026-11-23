from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from sniper.models import Listing, Platform, SearchState
from sniper.notify.message import (
    Message,
    format_price,
    listing_message,
    overflow_message,
    recovery_message,
    silence_message,
    status_message,
)

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def listing(**kw):
    base = dict(
        platform=Platform.KLEINANZEIGEN,
        external_id="1",
        title="Jacke Gr. L",
        url="https://www.kleinanzeigen.de/s-anzeige/jacke/1",
    )
    return Listing(**{**base, **kw})


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (dict(price=Decimal("45")), "45 €"),
        (dict(price=Decimal("45.50")), "45,50 €"),
        (dict(price=Decimal("1250")), "1.250 €"),
        (dict(price=Decimal("0")), "Zu verschenken"),
        (dict(price=None, negotiable=True), "VB"),
        (dict(price=None), "ohne Preis"),
        (dict(price=Decimal("45"), negotiable=True), "45 € VB"),
        (dict(price=Decimal("12"), listing_type="auction"), "12 € (Auktion)"),
        (dict(price=Decimal("45.00")), "45 €"),
    ],
)
def test_format_price(kw, expected):
    assert format_price(listing(**kw)) == expected


def test_listing_message_title_and_body():
    msg = listing_message(
        listing(
            price=Decimal("45"),
            negotiable=True,
            location="10115 Berlin",
            posted_at=NOW - timedelta(minutes=4),
            photo_urls=("https://img/1.jpg", "https://img/2.jpg"),
        ),
        "Jacken",
        NOW,
    )
    assert msg.title == "[Kleinanzeigen] Jacke Gr. L – 45 € VB"
    assert msg.body.splitlines() == [
        "Jacke Gr. L",
        "45 € VB",
        "10115 Berlin",
        "eingestellt vor 4 min",
        "Suche: Jacken",
        "https://www.kleinanzeigen.de/s-anzeige/jacke/1",
    ]
    assert msg.attach_url == "https://img/1.jpg"


def test_listing_message_hours_and_missing_optionals():
    msg = listing_message(listing(price=Decimal("5"), posted_at=NOW - timedelta(hours=3)), "J", NOW)
    assert "eingestellt vor 3 h" in msg.body.splitlines()
    assert msg.attach_url is None
    plain = listing_message(listing(price=Decimal("5")), "J", NOW).body.splitlines()
    assert plain == [
        "Jacke Gr. L",
        "5 €",
        "Suche: J",
        "https://www.kleinanzeigen.de/s-anzeige/jacke/1",
    ]


def test_listing_message_shipping_lines():
    with_cost = listing_message(
        listing(price=Decimal("45"), shipping_cost=Decimal("4.99")), "J", NOW
    )
    assert with_cost.body.splitlines()[1] == "45 € + 4,99 € Versand"
    pickup = listing_message(listing(price=Decimal("45"), shipping=False), "J", NOW)
    assert pickup.body.splitlines()[1] == "45 €, nur Abholung"


def test_status_texts():
    blocked = status_message("Jacken", Platform.KLEINANZEIGEN, SearchState.BLOCKED, "HTTP 403")
    assert blocked == Message(
        "Sniper: Jacken geblockt",
        "Kleinanzeigen blockt die Abfragen gerade. Der Sniper versucht es seltener weiter "
        "(bis alle 60 min) und meldet sich, wenn es wieder läuft.",
    )
    layout = status_message("Hoodies", Platform.WILLHABEN, SearchState.LAYOUT_CHANGED, None)
    assert layout == Message(
        "Sniper: Hoodies – Seite unbekannt",
        "willhaben hat die Seite geändert, der Sniper erkennt keine Anzeigen mehr. "
        "Probe-Kommando ausführen und Datei weitergeben.",
    )
    error = status_message("Jacken", Platform.EBAY, SearchState.ERROR, "Timeout")
    assert error == Message(
        "Sniper: Jacken – Fehler",
        "Die letzten 3 Abfragen sind fehlgeschlagen. Letzter Fehler: Timeout",
    )
    assert recovery_message("Jacken") == Message(
        "Sniper: Jacken läuft wieder", "Die Suche funktioniert wieder normal."
    )
    assert silence_message("Jacken", Platform.EBAY, 7) == Message(
        "Sniper: Jacken ist still",
        "Seit 7 Tagen keine neue Anzeige. Prüf die Suche oder ob eBay sich verändert hat.",
    )
    assert overflow_message("Jacken", Platform.EBAY, 3, "https://www.ebay.de/sch/x") == Message(
        "[eBay] Jacken: 3 weitere neue Anzeigen",
        "Mehr als 10 Treffer auf einmal. Alle ansehen: https://www.ebay.de/sch/x",
    )
