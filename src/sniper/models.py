"""Plattformneutrale Datentypen: eine Anzeige, eine Suche, Zustände.

`Listing` ist bewusst ohne Verkäuferdaten: Die eBay-API darf nur ohne gespeicherte
Nutzerdaten genutzt werden, und für eine Meldung braucht es sie nicht. Das Format ist
auch die Grundlage für die spätere Anbindung ans Reseller-Dashboard.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal


class Platform(StrEnum):
    EBAY = "ebay"
    KLEINANZEIGEN = "kleinanzeigen"
    WILLHABEN = "willhaben"

    @property
    def label(self) -> str:
        return _PLATFORM_LABELS[self]


_PLATFORM_LABELS = {
    Platform.EBAY: "eBay",
    Platform.KLEINANZEIGEN: "Kleinanzeigen",
    Platform.WILLHABEN: "willhaben",
}


class SearchState(StrEnum):
    PENDING = "pending"
    OK = "ok"
    ERROR = "error"
    BLOCKED = "blocked"
    LAYOUT_CHANGED = "layout_changed"
    PAUSED = "paused"

    @property
    def label(self) -> str:
        return _STATE_LABELS[self]


_STATE_LABELS = {
    SearchState.PENDING: "Neu",
    SearchState.OK: "OK",
    SearchState.ERROR: "Fehler",
    SearchState.BLOCKED: "Geblockt",
    SearchState.LAYOUT_CHANGED: "Seite unbekannt",
    SearchState.PAUSED: "Pausiert",
}


def _dec(value: Any) -> Decimal | None:
    return None if value is None else Decimal(value)


@dataclass(frozen=True)
class Listing:
    platform: Platform
    external_id: str
    title: str
    url: str
    price: Decimal | None = None
    currency: str = "EUR"
    negotiable: bool = False
    listing_type: Literal["fixed", "auction"] = "fixed"
    shipping: bool | None = None
    shipping_cost: Decimal | None = None
    photo_urls: tuple[str, ...] = ()
    location: str | None = None
    posted_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "external_id": self.external_id,
            "title": self.title,
            "url": self.url,
            "price": None if self.price is None else str(self.price),
            "currency": self.currency,
            "negotiable": self.negotiable,
            "listing_type": self.listing_type,
            "shipping": self.shipping,
            "shipping_cost": None if self.shipping_cost is None else str(self.shipping_cost),
            "photo_urls": list(self.photo_urls),
            "location": self.location,
            "posted_at": None if self.posted_at is None else self.posted_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Listing:
        posted = d.get("posted_at")
        return cls(
            platform=Platform(d["platform"]),
            external_id=d["external_id"],
            title=d["title"],
            url=d["url"],
            price=_dec(d.get("price")),
            currency=d.get("currency", "EUR"),
            negotiable=d.get("negotiable", False),
            listing_type=d.get("listing_type", "fixed"),
            shipping=d.get("shipping"),
            shipping_cost=_dec(d.get("shipping_cost")),
            photo_urls=tuple(d.get("photo_urls", ())),
            location=d.get("location"),
            posted_at=None if posted is None else datetime.fromisoformat(posted),
        )


@dataclass(frozen=True)
class SearchSpec:
    """Eine eingefügte Such-URL, geprüft und für den Abruf übersetzt."""

    platform: Platform
    url: str
    params: dict[str, str] = field(default_factory=dict)
    ignored: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform.value,
            "url": self.url,
            "params": dict(self.params),
            "ignored": list(self.ignored),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SearchSpec:
        return cls(
            platform=Platform(d["platform"]),
            url=d["url"],
            params=dict(d.get("params", {})),
            ignored=tuple(d.get("ignored", ())),
        )
