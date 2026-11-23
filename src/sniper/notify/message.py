"""Die Texte, die aufs Handy kommen. Kurz, deutsch, mit Link."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sniper.models import Listing, Platform, SearchState


@dataclass(frozen=True)
class Message:
    title: str
    body: str
    attach_url: str | None = None


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


def _age(posted_at: datetime, now: datetime) -> str:
    minutes = max(0, int((now - posted_at).total_seconds() // 60))
    if minutes < 60:
        return f"eingestellt vor {minutes} min"
    return f"eingestellt vor {minutes // 60} h"


def listing_message(listing: Listing, search_name: str, now: datetime) -> Message:
    price_line = format_price(listing)
    if listing.shipping_cost is not None:
        price_line += f" + {euro(listing.shipping_cost)} Versand"
    elif listing.shipping is False:
        price_line += ", nur Abholung"
    lines = [listing.title, price_line]
    if listing.location:
        lines.append(listing.location)
    if listing.posted_at is not None:
        lines.append(_age(listing.posted_at, now))
    lines += [f"Suche: {search_name}", listing.url]
    return Message(
        title=f"[{listing.platform.label}] {listing.title} – {format_price(listing)}",
        body="\n".join(lines),
        attach_url=listing.photo_urls[0] if listing.photo_urls else None,
    )


def overflow_message(search_name: str, platform: Platform, count: int, search_url: str) -> Message:
    return Message(
        f"[{platform.label}] {search_name}: {count} weitere neue Anzeigen",
        f"Mehr als 10 Treffer auf einmal. Alle ansehen: {search_url}",
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
