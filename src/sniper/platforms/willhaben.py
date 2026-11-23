"""willhaben: Die Suchergebnisse stecken als JSON im `__NEXT_DATA__`-Block der Seite.

Pfad und Attributnamen stehen als Konstanten oben, damit sie nach einer Änderung an der
Seite an einer Stelle angepasst werden können.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from sniper.models import Listing, Platform, SearchSpec
from sniper.platforms import normalize_url
from sniper.platforms.base import InvalidUrl, LayoutChanged
from sniper.platforms.http import HttpClient, check_blocked
from sniper.platforms.prices import parse_price

BASE = "https://www.willhaben.at/iad/"
RESULT_PATH = ("props", "pageProps", "searchResult", "advertSummaryList", "advertSummary")
SORT_PARAM, SORT_NEWEST = "sort", "1"
ATTR_PRICE, ATTR_LOCATION, ATTR_POSTCODE = "PRICE", "LOCATION", "POSTCODE"
ATTR_PUBLISHED, ATTR_SEO_URL = "PUBLISHED", "SEO_URL"


class WillhabenAdapter:
    platform = Platform.WILLHABEN

    def __init__(self, http: HttpClient) -> None:
        self._http = http

    def parse_url(self, url: str) -> SearchSpec:
        parts = urlsplit(normalize_url(url))
        if not parts.path.startswith("/iad/"):
            raise InvalidUrl(
                "Das ist keine willhaben-Suche. Bitte die URL einer Suchergebnisseite einfügen."
            )
        query = [
            (k, v)
            for k, v in parse_qsl(parts.query)
            if not k.startswith("utm_") and k != SORT_PARAM
        ]
        query.append((SORT_PARAM, SORT_NEWEST))
        clean = urlunsplit(("https", "www.willhaben.at", parts.path, urlencode(query), ""))
        return SearchSpec(platform=Platform.WILLHABEN, url=clean)

    def fetch(self, spec: SearchSpec) -> list[Listing]:
        resp = self._http.get(spec.url)
        check_blocked(resp)
        script = BeautifulSoup(resp.text, "html.parser").find("script", id="__NEXT_DATA__")
        if script is None:
            raise LayoutChanged("willhaben: kein __NEXT_DATA__ auf der Seite")
        node: Any = json.loads(script.string or "{}")
        for key in RESULT_PATH:
            if not isinstance(node, dict) or key not in node:
                raise LayoutChanged("willhaben: Ergebnisliste nicht gefunden")
            node = node[key]
        return [_to_listing(summary) for summary in node or []]


def attr(summary: dict[str, Any], name: str) -> str | None:
    for a in summary.get("attributes", {}).get("attribute", []):
        if a.get("name") == name and a.get("values"):
            return str(a["values"][0])
    return None


def _published(value: str | None) -> datetime | None:
    if not value:
        return None
    if value.isdigit():
        return datetime.fromtimestamp(int(value) / 1000, tz=UTC)
    try:
        return datetime.fromisoformat(value).astimezone(UTC)
    except ValueError:
        return None


def _to_listing(summary: dict[str, Any]) -> Listing:
    price, negotiable = parse_price(attr(summary, ATTR_PRICE) or "")
    location = " ".join(
        p for p in (attr(summary, ATTR_POSTCODE), attr(summary, ATTR_LOCATION)) if p
    )
    images = summary.get("advertImageList", {}).get("advertImage", [])
    return Listing(
        platform=Platform.WILLHABEN,
        external_id=str(summary["id"]),
        title=summary.get("description", ""),
        url=BASE + (attr(summary, ATTR_SEO_URL) or ""),
        price=price,
        negotiable=negotiable,
        photo_urls=tuple(img["mainImageUrl"] for img in images if img.get("mainImageUrl")),
        location=location or None,
        posted_at=_published(attr(summary, ATTR_PUBLISHED)),
    )
