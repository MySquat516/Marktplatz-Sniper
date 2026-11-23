"""Kleinanzeigen: Suchergebnisseite abrufen und die Anzeigenliste auslesen.

Es gibt keine API. Alle Selektoren stehen in `SELECTORS`, damit eine Änderung an der Seite
an einer Stelle nachgezogen werden kann (Probe-Kommando ausführen, Fixture tauschen).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

from sniper.models import Listing, Platform, SearchSpec
from sniper.platforms import normalize_url
from sniper.platforms.base import InvalidUrl, LayoutChanged
from sniper.platforms.http import HttpClient, check_blocked
from sniper.platforms.prices import parse_price

BASE = "https://www.kleinanzeigen.de"
BERLIN = ZoneInfo("Europe/Berlin")
SORT_NEWEST = "sortierung:neueste"
SELECTORS = {
    "list": "#srchrslt-adtable",
    "item": "article[data-adid]",
    "title": "h3 a",
    "location": 'svg[data-title="locationOutline"] + span',
    "time": 'svg[data-title="calendarOutline"] + span',
    "image": "img",
}
# Preiszeile: „45 €“, „45 € VB“, „1.250 €“, „VB“, „Zu verschenken“. Die erste passende <p>
# ist der aktuelle Preis, eine zweite (durchgestrichen) wäre der alte.
_PRICE_LINE = re.compile(r"^(\d[\d.]*(,\d{1,2})?\s*€)?\s*(VB)?$|^Zu verschenken$")
NO_RESULTS_MARKER = "keine Ergebnisse"
# Bildgröße: $_2 ist das Listen-Vorschaubild (150 × 200), $_59 die Größe der Anzeigenseite
# (720 × 960). „.JPG“ statt „.AUTO“: AUTO liefert Browsern AVIF, und das nimmt Telegram nicht
# als Foto an. Am 23.11.2026 im Browser nachgemessen.
IMAGE_RULE = "$_59.JPG"
_TIME = re.compile(r"(Heute|Gestern),\s*(\d{1,2}):(\d{2})")
_DATE = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")


class KleinanzeigenAdapter:
    platform = Platform.KLEINANZEIGEN

    def __init__(
        self, http: HttpClient, now: Callable[[], datetime] = lambda: datetime.now(UTC)
    ) -> None:
        self._http = http
        self._now = now

    def parse_url(self, url: str) -> SearchSpec:
        parts = urlsplit(normalize_url(url))
        if not parts.path.startswith("/s-") or parts.path.startswith("/s-anzeige/"):
            raise InvalidUrl(
                "Das ist keine Kleinanzeigen-Suche. Bitte die URL einer Suchergebnisseite einfügen."
            )
        segments = parts.path[len("/s-") :].split("/")
        segments = [s for s in segments if not s.startswith("sortierung:")]
        path = "/s-" + "/".join([SORT_NEWEST, *segments])
        query = urlencode([(k, v) for k, v in parse_qsl(parts.query) if not k.startswith("utm_")])
        clean = urlunsplit(("https", "www.kleinanzeigen.de", path, query, ""))
        return SearchSpec(platform=Platform.KLEINANZEIGEN, url=clean)

    def fetch(self, spec: SearchSpec) -> list[Listing]:
        resp = self._http.get(spec.url)
        check_blocked(resp)
        soup = BeautifulSoup(resp.text, "html.parser")
        result_list = soup.select_one(SELECTORS["list"])
        if result_list is None:
            if NO_RESULTS_MARKER in soup.get_text(" "):
                return []
            raise LayoutChanged("Kleinanzeigen: keine Anzeigenliste auf der Seite gefunden")
        articles = result_list.select(SELECTORS["item"])
        if not articles and result_list.select("li article"):
            raise LayoutChanged("Kleinanzeigen: Anzeigen ohne Kennung (data-adid) gefunden")
        now = self._now()
        listings = [
            listing
            for article in articles
            if (listing := self._to_listing(article, now)) is not None
        ]
        # Eine Liste voller Anzeigen, aus der nichts lesbar ist, heißt: Die Seite hat sich
        # geändert. Das soll „Seite unbekannt“ melden, nicht „OK, nichts Neues“.
        regular = [a for a in articles if not _is_top_ad(a)]
        if regular and not listings:
            raise LayoutChanged("Kleinanzeigen: Anzeigen gefunden, aber nicht lesbar")
        if len(articles) >= 3 and not regular:
            raise LayoutChanged("Kleinanzeigen: nur TOP-Anzeigen erkannt")
        return listings

    def _to_listing(self, article: Tag, now: datetime) -> Listing | None:
        adid = article.get("data-adid")
        title_el = article.select_one(SELECTORS["title"])
        if not adid or title_el is None or _is_top_ad(article):
            return None
        href = article.get("data-href") or title_el.get("href") or ""
        price, negotiable = parse_price(_price_text(article))
        img = article.select_one(SELECTORS["image"])
        photo = (img.get("src") or img.get("data-imgsrc")) if img else None
        full_text = article.get_text(" ")
        shipping = (
            True
            if "Versand möglich" in full_text
            else False
            if "Nur Abholung" in full_text
            else None
        )
        return Listing(
            platform=Platform.KLEINANZEIGEN,
            external_id=str(adid),
            title=_text(title_el),
            url=urljoin(BASE, str(href)),
            price=price,
            negotiable=negotiable,
            shipping=shipping,
            photo_urls=(large_image(str(photo)),) if photo else (),
            location=_text(article.select_one(SELECTORS["location"])) or None,
            posted_at=parse_time(_text(article.select_one(SELECTORS["time"])), now),
        )


def _is_top_ad(article: Tag) -> bool:
    """TOP-Anzeigen sind bezahlte, oft alte Anzeigen; ihr Abzeichen ist ein SVG direkt im <li>."""
    item = article.parent
    return item is not None and item.find("svg", recursive=False) is not None


def _price_text(article: Tag) -> str:
    for p in article.find_all("p"):
        text = _text(p)
        if text and _PRICE_LINE.match(text):
            return text
    return ""


def large_image(url: str) -> str:
    """Tauscht die Bildgröße in der URL gegen die große Fassung aus."""
    if "rule=" in url:
        return re.sub(r"rule=[^&]*", f"rule={IMAGE_RULE}", url)
    return f"{url}{'&' if '?' in url else '?'}rule={IMAGE_RULE}"


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ").split()) if el is not None else ""


def parse_time(text: str, now: datetime) -> datetime | None:
    """„Heute, 07:12“, „Gestern, 18:30“ oder „21.11.2026“ (Berliner Zeit) → UTC."""
    today = now.astimezone(BERLIN).date()
    if m := _TIME.search(text):
        day = today if m.group(1) == "Heute" else today - timedelta(days=1)
        local = datetime(
            day.year, day.month, day.day, int(m.group(2)), int(m.group(3)), tzinfo=BERLIN
        )
        return local.astimezone(UTC)
    if m := _DATE.search(text):
        local = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), tzinfo=BERLIN)
        return local.astimezone(UTC)
    return None
