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
    assert msg.title == "Jacke Gr. L"
    assert msg.body.splitlines() == ["45 € VB · Kleinanzeigen", "📍 10115 Berlin", "🔎 Jacken"]
    assert (msg.link_url, msg.link_label) == (
        "https://www.kleinanzeigen.de/s-anzeige/jacke/1",
        "Anzeige öffnen",
    )
    assert msg.attach_url == "https://img/1.jpg"


def test_listing_message_has_no_time_and_skips_missing_location():
    msg = listing_message(listing(price=Decimal("5"), posted_at=NOW - timedelta(hours=3)), "J", NOW)
    assert msg.body.splitlines() == ["5 € · Kleinanzeigen", "🔎 J"]
    assert "eingestellt" not in msg.body
    assert msg.attach_url is None


def test_listing_message_shipping_lines():
    with_cost = listing_message(
        listing(platform=Platform.EBAY, price=Decimal("45"), shipping_cost=Decimal("4.99")),
        "J",
        NOW,
    )
    assert with_cost.body.splitlines()[0] == "45 € + 4,99 € Versand · eBay"
    pickup = listing_message(listing(price=Decimal("45"), shipping=False), "J", NOW)
    assert pickup.body.splitlines()[0] == "45 €, nur Abholung · Kleinanzeigen"


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
        "Jacken: 3 weitere neue Anzeigen",
        "Mehr als 10 Treffer auf einmal · eBay",
        link_url="https://www.ebay.de/sch/x",
        link_label="Alle ansehen",
    )
