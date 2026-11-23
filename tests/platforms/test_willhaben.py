from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sniper.models import Platform
from sniper.platforms import build_adapters
from sniper.platforms.base import Blocked, InvalidUrl, LayoutChanged
from sniper.platforms.http import HttpResponse
from sniper.platforms.willhaben import WillhabenAdapter

FIX = Path(__file__).parent.parent / "fixtures" / "willhaben"
SEARCH = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=hoodie"


class FakeHttp:
    def __init__(self, text="", status=200):
        self.resp = HttpResponse(status, text, {})
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.resp


def adapter(text="", status=200):
    http = FakeHttp(text, status)
    return WillhabenAdapter(http), http


def test_parse_url_forces_newest_and_strips_tracking():
    a, _ = adapter()
    spec = a.parse_url(
        "willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=hoodie&sort=3&utm_source=app"
    )
    assert spec.platform is Platform.WILLHABEN
    assert spec.url == (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=hoodie&sort=1"
    )


def test_parse_url_rejects_other_pages():
    a, _ = adapter()
    with pytest.raises(InvalidUrl):
        a.parse_url("https://www.willhaben.at/")


def test_fetch_parses_listings():
    a, http = adapter((FIX / "results.html").read_text(encoding="utf-8"))
    hoodie, couch, bare = a.fetch(a.parse_url(SEARCH))
    assert http.urls == [SEARCH + "&sort=1"]
    assert hoodie.external_id == "1234567890"
    assert hoodie.title == "Nike Tech Hoodie Gr. M"
    assert hoodie.url == (
        "https://www.willhaben.at/iad/d/kaufen-und-verkaufen/wien/nike-tech-hoodie-1234567890/"
    )
    assert hoodie.price == Decimal("45")
    assert hoodie.location == "1070 Wien, 07. Bezirk, Neubau"
    assert hoodie.photo_urls == (
        "https://cache.willhaben.at/mmo/0/123/4567890_1.jpg",
        "https://cache.willhaben.at/mmo/0/123/4567890_2.jpg",
    )
    assert hoodie.posted_at == datetime(2026, 11, 23, 6, 1, tzinfo=UTC)
    assert couch.price == Decimal("1250")
    assert couch.location == "Graz"
    assert couch.posted_at == datetime(2026, 11, 23, 5, 0, tzinfo=UTC)
    assert (bare.price, bare.posted_at, bare.location, bare.photo_urls) == (None, None, None, ())


def test_missing_next_data_is_layout_changed():
    a, _ = adapter((FIX / "no_next_data.html").read_text(encoding="utf-8"))
    with pytest.raises(LayoutChanged):
        a.fetch(a.parse_url(SEARCH))


def test_missing_result_path_is_layout_changed():
    page = '<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>'
    a, _ = adapter(page)
    with pytest.raises(LayoutChanged):
        a.fetch(a.parse_url(SEARCH))


def test_empty_result_list():
    page = (
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"pageProps": {"searchResult": {"advertSummaryList": {"advertSummary": []}}}}}'
        "</script>"
    )
    a, _ = adapter(page)
    assert a.fetch(a.parse_url(SEARCH)) == []


def test_challenge_page_is_blocked():
    a, _ = adapter("<title>Just a moment...</title>")
    with pytest.raises(Blocked):
        a.fetch(a.parse_url(SEARCH))


def test_build_adapters_registers_willhaben():
    adapters = build_adapters(FakeHttp(), lambda: ("", ""))
    assert isinstance(adapters[Platform.WILLHABEN], WillhabenAdapter)


def test_real_page():
    a, _ = adapter((FIX / "real-results.html").read_text(encoding="utf-8"))
    (item,) = a.fetch(a.parse_url(SEARCH))
    assert item.external_id == "1096547607"
    assert item.title == "Kindermotorsportjacke Gr. 140q"
    assert item.url == (
        "https://www.willhaben.at/iad/kaufen-und-verkaufen/d/kindermotorsportjacke-gr-140q-1096547607/"
    )
    assert item.price == Decimal("40")
    assert item.location == "1220 Wien, 22. Bezirk, Donaustadt"
    # PUBLISHED (Epoch-ms) ist richtig; PUBLISHED_String zeigt Wiener Zeit mit falschem „Z“.
    assert item.posted_at == datetime(2026, 11, 23, 7, 24, 49, 418000, tzinfo=UTC)
    assert item.photo_urls == (
        "https://cache.willhaben.at/mmo/7/109/654/7607_-316619769_hoved.jpg",
    )
    assert item.shipping is True


def test_shipping_unknown_without_p2p_flag():
    a, _ = adapter((FIX / "results.html").read_text(encoding="utf-8"))
    assert {item.shipping for item in a.fetch(a.parse_url(SEARCH))} == {None}
