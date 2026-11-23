from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sniper.models import Platform
from sniper.platforms import build_adapters
from sniper.platforms.base import Blocked, InvalidUrl, LayoutChanged
from sniper.platforms.http import HttpResponse
from sniper.platforms.kleinanzeigen import KleinanzeigenAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "kleinanzeigen"
# 23.11.2026, 07:30 in Berlin (Winterzeit, UTC+1)
NOW = datetime(2026, 11, 23, 6, 30, tzinfo=UTC)


class FakeHttp:
    def __init__(self, text, status=200):
        self.resp = HttpResponse(status, text, {})
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.resp


def adapter(text="", status=200):
    http = FakeHttp(text, status)
    return KleinanzeigenAdapter(http, now=lambda: NOW), http


def fetch(name):
    a, _ = adapter((FIX / name).read_text(encoding="utf-8"))
    return a.fetch(a.parse_url("https://www.kleinanzeigen.de/s-jacke/k0"))


def test_parse_url_forces_newest_and_strips_tracking():
    a, _ = adapter()
    spec = a.parse_url("https://kleinanzeigen.de/s-jacke/k0?utm_source=app&utm_medium=share")
    assert spec.platform is Platform.KLEINANZEIGEN
    assert spec.url == "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"
    assert spec.ignored == ()


def test_parse_url_replaces_other_sorting():
    a, _ = adapter()
    spec = a.parse_url("https://www.kleinanzeigen.de/s-sortierung:preis/jacke/k0")
    assert spec.url == "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"


def test_parse_url_keeps_other_query_params():
    a, _ = adapter()
    spec = a.parse_url("https://www.kleinanzeigen.de/s-jacke/k0?keywords=x&utm_source=app")
    assert spec.url == "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0?keywords=x"


def test_parse_url_rejects_non_search_pages():
    a, _ = adapter()
    with pytest.raises(InvalidUrl):
        a.parse_url("https://www.kleinanzeigen.de/s-anzeige/jacke/2934567890-160-3331")


def test_fetch_requests_normalized_url():
    a, http = adapter((FIX / "results.html").read_text(encoding="utf-8"))
    a.fetch(a.parse_url("kleinanzeigen.de/s-jacke/k0"))
    assert http.urls == ["https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"]


def test_fetch_parses_listings():
    jacke, kinder, leder, regen = fetch("results.html")
    assert jacke.external_id == "2934567890"
    assert jacke.title == "Carhartt Jacke Gr. L"
    assert (
        jacke.url
        == "https://www.kleinanzeigen.de/s-anzeige/carhartt-jacke-gr-l/2934567890-160-3331"
    )
    assert (jacke.price, jacke.negotiable, jacke.shipping) == (Decimal("45"), True, True)
    assert jacke.location == "10115 Berlin Mitte (3 km)"
    assert jacke.photo_urls == (
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/2934567890?rule=$_2.AUTO",
    )
    assert (kinder.price, kinder.shipping, kinder.photo_urls) == (Decimal("0"), False, ())
    assert (leder.price, leder.shipping) == (Decimal("1250"), None)
    assert (regen.price, regen.negotiable) == (None, True)
    assert {item.platform for item in (jacke, kinder, leder, regen)} == {Platform.KLEINANZEIGEN}


def test_relative_times():
    jacke, kinder, leder, regen = fetch("results.html")
    assert jacke.posted_at == datetime(2026, 11, 23, 6, 12, tzinfo=UTC)
    assert kinder.posted_at == datetime(2026, 11, 22, 17, 30, tzinfo=UTC)
    assert leder.posted_at == datetime(2026, 11, 20, 23, 0, tzinfo=UTC)
    assert regen.posted_at == datetime(2026, 11, 23, 5, 1, tzinfo=UTC)


def test_empty_results_returns_empty_list():
    assert fetch("empty.html") == []


def test_challenge_page_is_blocked():
    with pytest.raises(Blocked):
        fetch("challenge.html")


def test_unknown_page_is_layout_changed():
    a, _ = adapter("<html><body>neu</body></html>")
    with pytest.raises(LayoutChanged):
        a.fetch(a.parse_url("https://www.kleinanzeigen.de/s-jacke/k0"))


def test_build_adapters_registers_kleinanzeigen():
    adapters = build_adapters(FakeHttp(""), lambda: ("", ""))
    assert isinstance(adapters[Platform.KLEINANZEIGEN], KleinanzeigenAdapter)
