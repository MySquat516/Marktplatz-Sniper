"""Welche Anzeigen sind neu, und welche davon werden gemeldet? Reine Funktion, ohne Datenbank.

Regeln: Was diese Suche schon kennt, wird übersprungen. Beim ersten Check wird alles still
gemerkt. Danach fliegen zu alte Anzeigen, zu teure und solche mit Ausschlusswort raus; von
den übrigen werden höchstens zehn gemeldet, der Rest zählt als Überlauf.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Literal

from sniper.models import Listing

FRESHNESS = timedelta(hours=24)
MAX_NOTIFICATIONS_PER_CHECK = 10


@dataclass(frozen=True)
class Filters:
    max_price: Decimal | None = None
    exclude_words: tuple[str, ...] = ()

    @classmethod
    def from_text(cls, max_price: Decimal | None, exclude_text: str) -> Filters:
        words = tuple(w.strip() for w in exclude_text.splitlines() if w.strip())
        return cls(max_price=max_price, exclude_words=words)


@dataclass(frozen=True)
class Verdict:
    listing: Listing
    status: Literal["seeded", "matched", "rejected"]
    reason: str | None
    notify: bool


@dataclass(frozen=True)
class Detection:
    verdicts: list[Verdict]
    overflow: int


def _rejection(listing: Listing, filters: Filters, now: datetime) -> str | None:
    if listing.posted_at is not None and now - listing.posted_at > FRESHNESS:
        return "zu alt"
    if (
        listing.price is not None
        and filters.max_price is not None
        and listing.price > filters.max_price
    ):
        return "über Höchstpreis"
    title = listing.title.casefold()
    for word in filters.exclude_words:
        if word.casefold() in title:
            return f"Ausschlusswort: {word}"
    return None


def detect(
    listings: Sequence[Listing],
    seen_ids: set[str],
    filters: Filters,
    *,
    first_check: bool,
    now: datetime,
) -> Detection:
    verdicts: list[Verdict] = []
    handled: set[str] = set()
    notified = overflow = 0
    for listing in listings:
        if listing.external_id in seen_ids or listing.external_id in handled:
            continue
        handled.add(listing.external_id)
        if first_check:
            verdicts.append(Verdict(listing, "seeded", None, notify=False))
            continue
        reason = _rejection(listing, filters, now)
        if reason:
            verdicts.append(Verdict(listing, "rejected", reason, notify=False))
            continue
        notify = notified < MAX_NOTIFICATIONS_PER_CHECK
        notified += notify
        overflow += not notify
        verdicts.append(Verdict(listing, "matched", None, notify=notify))
    return Detection(verdicts=verdicts, overflow=overflow)
