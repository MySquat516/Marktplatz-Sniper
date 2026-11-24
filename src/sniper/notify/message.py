"""Die Texte, die aufs Handy kommen. Kurz, deutsch, mit Link."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from urllib.parse import quote, quote_plus

from sniper.models import Listing, Platform, SearchState


@dataclass(frozen=True)
class Button:
    """Ein Link-Knopf unter der Meldung. Nur Telegram zeigt Knöpfe; `style` färbt ihn dort."""

    label: str
    url: str
    style: str | None = None


@dataclass(frozen=True)
class Message:
    """Eine Meldung. Der Link steht extra, damit der Versand ihn je nach Dienst als
    anklickbaren Text oder als ausgeschriebene URL setzt. `buttons` sind Zeilen von Knöpfen;
    gibt es welche, ersetzen sie bei Telegram die Linkzeile."""

    title: str
    body: str
    attach_url: str | None = None
    link_url: str | None = None
    link_label: str = "Anzeige öffnen"
    buttons: tuple[tuple[Button, ...], ...] = ()


def ebay_sold_url(title: str) -> str:
    """Verkaufte Angebote mit diesem Titel auf eBay.de: zeigt, was so etwas wirklich bringt."""
    return f"https://www.ebay.de/sch/i.html?_nkw={quote_plus(title)}&LH_Sold=1&LH_Complete=1"


def lens_url(photo_url: str) -> str:
    """Google Lens mit dem Anzeigenfoto: findet das Modell und geklaute Fotos."""
    return f"https://lens.google.com/uploadbyurl?url={quote(photo_url, safe='')}"


def euro(amount: Decimal) -> str:
    q = amount.quantize(Decimal("0.01"))
    if q == q.to_integral_value():
        text = f"{int(q):,}".replace(",", ".")
    else:
        text = f"{q:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")
    return f"{text} €"


def format_price(listing: Listing) -> str:
    if listing.price is None:
        return "VB" if listing.negotiable else "ohne Preis"
    if listing.price == 0:
        return "Zu verschenken"
    text = euro(listing.price)
    if listing.negotiable:
        text += " VB"
    if listing.listing_type == "auction":
        text += " (Auktion)"
    return text


def listing_message(listing: Listing, search_name: str, now: datetime) -> Message:
    price_line = format_price(listing)
    if listing.shipping_cost is not None:
        price_line += f" + {euro(listing.shipping_cost)} Versand"
    elif listing.shipping is False:
        price_line += ", nur Abholung"
    lines = [f"{price_line} · {listing.platform.label}"]
    if listing.location:
        lines.append(f"📍 {listing.location}")
    lines.append(f"🔎 {search_name}")
    photo = listing.photo_urls[0] if listing.photo_urls else None
    buttons: list[tuple[Button, ...]] = [
        (
            Button("Anzeige öffnen", listing.url, "primary"),
            Button("eBay verkauft", ebay_sold_url(listing.title)),
        )
    ]
    if photo:
        buttons.append((Button("Bildersuche", lens_url(photo)),))
    return Message(
        title=listing.title,
        body="\n".join(lines),
        attach_url=photo,
        link_url=listing.url,
        buttons=tuple(buttons),
    )


def overflow_message(search_name: str, platform: Platform, count: int, search_url: str) -> Message:
    return Message(
        f"{search_name}: {count} weitere neue Anzeigen",
        f"Mehr als 10 Treffer auf einmal · {platform.label}",
        link_url=search_url,
        link_label="Alle ansehen",
        buttons=((Button("Alle ansehen", search_url, "primary"),),),
    )


def status_message(
    search_name: str, platform: Platform, state: SearchState, detail: str | None
) -> Message:
    if state is SearchState.BLOCKED:
        return Message(
            f"Sniper: {search_name} geblockt",
            f"{platform.label} blockt die Abfragen gerade. Der Sniper versucht es seltener "
            "weiter (bis alle 60 min) und meldet sich, wenn es wieder läuft.",
        )
    if state is SearchState.LAYOUT_CHANGED:
        return Message(
            f"Sniper: {search_name} – Seite unbekannt",
            f"{platform.label} hat die Seite geändert, der Sniper erkennt keine Anzeigen mehr. "
            "Probe-Kommando ausführen und Datei weitergeben.",
        )
    return Message(
        f"Sniper: {search_name} – Fehler",
        f"Die letzten 3 Abfragen sind fehlgeschlagen. Letzter Fehler: {detail}",
    )


def recovery_message(search_name: str) -> Message:
    return Message(f"Sniper: {search_name} läuft wieder", "Die Suche funktioniert wieder normal.")


def silence_message(search_name: str, platform: Platform, days: int) -> Message:
    return Message(
        f"Sniper: {search_name} ist still",
        f"Seit {days} Tagen keine neue Anzeige. Prüf die Suche oder ob {platform.label} "
        "sich verändert hat.",
    )
