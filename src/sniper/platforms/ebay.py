"""eBay über die offizielle Browse API.

Die eingefügte ebay.de-Such-URL wird in API-Parameter übersetzt. Verkäuferdaten werden
nicht gelesen: Der kostenlose Zugang setzt voraus, dass keine eBay-Nutzerdaten gespeichert
werden (Befreiung von den „Marketplace Account Deletion“-Benachrichtigungen).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from sniper.models import Listing, Platform, SearchSpec
from sniper.platforms import normalize_url
from sniper.platforms.base import AdapterError, InvalidUrl, MissingCredentials
from sniper.platforms.http import HttpClient, HttpResponse, check_blocked

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
SCOPE = "https://api.ebay.com/oauth/api_scope"
MARKETPLACE = "EBAY_DE"
_SILENT = {"_from", "_trksid", "rt", "_sop", "_osacat", "_odkw", "_ipg", "_pgn"}
_HANDLED = {
    "_nkw",
    "_sacat",
    "_udlo",
    "_udhi",
    "LH_ItemCondition",
    "LH_BIN",
    "LH_Auction",
    "LH_PrefLoc",
}


class EbayAdapter:
    platform = Platform.EBAY

    def __init__(
        self,
        http: HttpClient,
        credentials: Callable[[], tuple[str, str]],
        clock: Callable[[], float] = time.time,
    ) -> None:
        self._http = http
        self._credentials = credentials
        self._clock = clock
        self._token: str | None = None
        self._token_valid_until = 0.0

    def parse_url(self, url: str) -> SearchSpec:
        url = normalize_url(url)
        parts = urlsplit(url)
        if not parts.path.startswith("/sch/"):
            raise InvalidUrl(
                "Das ist keine eBay-Suche. Bitte die URL einer Suchergebnisseite einfügen."
            )
        query = dict(parse_qsl(parts.query))
        params: dict[str, str] = {}
        if query.get("_nkw", "").strip():
            params["q"] = query["_nkw"].strip()
        if query.get("_sacat", "0") not in ("", "0"):
            params["category_ids"] = query["_sacat"]
        if not params:
            raise InvalidUrl("Die eBay-URL enthält keinen Suchbegriff.")

        filters: list[str] = []
        lo, hi = query.get("_udlo", ""), query.get("_udhi", "")
        if lo or hi:
            filters += [f"price:[{lo}..{hi}]", "priceCurrency:EUR"]
        if query.get("LH_ItemCondition"):
            filters.append(f"conditionIds:{{{query['LH_ItemCondition']}}}")
        options = [
            o
            for k, o in (("LH_BIN", "FIXED_PRICE"), ("LH_Auction", "AUCTION"))
            if query.get(k) == "1"
        ]
        if options:
            filters.append(f"buyingOptions:{{{'|'.join(options)}}}")
        if query.get("LH_PrefLoc") == "1":
            filters.append("itemLocationCountry:DE")
        if filters:
            params["filter"] = ",".join(filters)

        ignored = tuple(k for k in query if k not in _HANDLED and k not in _SILENT)
        return SearchSpec(platform=Platform.EBAY, url=url, params=params, ignored=ignored)

    def fetch(self, spec: SearchSpec) -> list[Listing]:
        resp = self._search(spec)
        if resp.status == 401:
            self._token = None
            resp = self._search(spec)
        check_blocked(resp)
        if resp.status != 200:
            raise AdapterError(f"eBay antwortet mit HTTP {resp.status}")
        data = json.loads(resp.text)
        return [_to_listing(item) for item in data.get("itemSummaries", [])]

    def _search(self, spec: SearchSpec) -> HttpResponse:
        params = {**spec.params, "sort": "newlyListed", "limit": "50"}
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "X-EBAY-C-MARKETPLACE-ID": MARKETPLACE,
        }
        return self._http.get(SEARCH_URL, params=params, headers=headers)

    def _get_token(self) -> str:
        if self._token and self._clock() < self._token_valid_until:
            return self._token
        client_id, secret = self._credentials()
        if not client_id or not secret:
            raise MissingCredentials("eBay-Zugangsdaten fehlen (Einstellungen).")
        resp = self._http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials", "scope": SCOPE},
            auth=(client_id, secret),
        )
        check_blocked(resp)
        if resp.status != 200:
            raise AdapterError(f"eBay-Anmeldung fehlgeschlagen (HTTP {resp.status})")
        data = json.loads(resp.text)
        self._token = data["access_token"]
        self._token_valid_until = self._clock() + int(data.get("expires_in", 7200)) - 60
        return self._token


def _money(obj: dict[str, Any] | None) -> Decimal | None:
    if not obj or obj.get("value") is None:
        return None
    return Decimal(str(obj["value"]))


def _to_listing(item: dict[str, Any]) -> Listing:
    options = item.get("buyingOptions", [])
    auction = "AUCTION" in options and "FIXED_PRICE" not in options
    price = _money(item.get("currentBidPrice")) if auction else None
    price = price if price is not None else _money(item.get("price"))
    shipping_options = item.get("shippingOptions") or []
    photos = [item.get("image", {}).get("imageUrl")]
    photos += [img.get("imageUrl") for img in item.get("additionalImages", [])]
    loc = item.get("itemLocation", {})
    location = " ".join(p for p in (loc.get("postalCode"), loc.get("city")) if p) or None
    created = item.get("itemCreationDate")
    return Listing(
        platform=Platform.EBAY,
        external_id=str(item.get("legacyItemId") or item["itemId"]),
        title=item.get("title", ""),
        url=item.get("itemWebUrl", ""),
        price=price,
        currency=(item.get("price") or {}).get("currency", "EUR"),
        listing_type="auction" if auction else "fixed",
        shipping=True if shipping_options else None,
        shipping_cost=_money(shipping_options[0].get("shippingCost")) if shipping_options else None,
        photo_urls=tuple(p for p in photos if p),
        location=location,
        posted_at=datetime.fromisoformat(created) if created else None,
    )
