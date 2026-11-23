"""Welche Plattform zu einer URL gehört, und die Adapter dazu."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from urllib.parse import urlsplit

from sniper.models import Platform
from sniper.platforms.base import Adapter, InvalidUrl
from sniper.platforms.http import HttpClient

_HOSTS = {
    "ebay.de": Platform.EBAY,
    "kleinanzeigen.de": Platform.KLEINANZEIGEN,
    "willhaben.at": Platform.WILLHABEN,
}
UNKNOWN_SITE = "Unbekannte Seite – unterstützt werden eBay, Kleinanzeigen und willhaben."


def normalize_url(url: str) -> str:
    url = url.strip()
    if url and "://" not in url:
        url = "https://" + url
    return url


def platform_for_url(url: str) -> Platform:
    host = (urlsplit(normalize_url(url)).hostname or "").lower()
    for prefix in ("www.", "m."):
        host = host.removeprefix(prefix)
    if host not in _HOSTS:
        raise InvalidUrl(UNKNOWN_SITE)
    return _HOSTS[host]


def adapter_for_url(url: str, adapters: Mapping[Platform, Adapter]) -> Adapter:
    return adapters[platform_for_url(url)]


def build_adapters(
    http: HttpClient, credentials: Callable[[], tuple[str, str]]
) -> dict[Platform, Adapter]:
    from sniper.platforms.ebay import EbayAdapter

    return {Platform.EBAY: EbayAdapter(http, credentials)}
