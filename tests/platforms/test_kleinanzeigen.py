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
        == "https://www.kleinanzeigen.de/s-anzeige/carhartt-jacke-gr-l/2934567890-160-9189"
    )
    assert (jacke.price, jacke.negotiable, jacke.shipping) == (Decimal("45"), True, True)
    assert jacke.location == "10115 Berlin"
    assert jacke.photo_urls == (
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/2934567890?rule=$_59.JPG",
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


def test_top_ads_and_ad_slots_are_skipped():
    ids = [item.external_id for item in fetch("results.html")]
    assert ids == ["2934567890", "2934567891", "2934567892", "2934567893"]


def test_old_strikethrough_price_is_ignored():
    jacke = fetch("results.html")[0]
    assert jacke.price == Decimal("45")


def test_real_page():
    soft, fleece = fetch("real-results.html")
    assert (soft.external_id, fleece.external_id) == ("3580144532", "3580144505")
    assert soft.title == "Softshelljacke Color Kids Gr.152"
    assert soft.url == (
        "https://www.kleinanzeigen.de/s-anzeige/softshelljacke-color-kids-gr-152/3580144532-22-7496"
    )
    assert (soft.price, soft.negotiable, soft.shipping) == (Decimal("12"), False, True)
    assert soft.location == "95445 Bayreuth"
    assert soft.posted_at == datetime(2026, 11, 23, 7, 25, tzinfo=UTC)
    assert soft.photo_urls == (
        "https://img.kleinanzeigen.de/api/v1/prod-ads/images/a1/"
        "a15e46ee-5fcb-4e96-8907-55d79ac82e46?rule=$_59.JPG",
    )
    assert (fleece.price, fleece.location) == (Decimal("15"), "27639 Dorum")


def test_real_page_is_newest_first():
    times = [item.posted_at for item in fetch("real-results.html") if item.posted_at]
    assert times == sorted(times, reverse=True)


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        (
            "https://img.kleinanzeigen.de/x?rule=$_2.AUTO",
            "https://img.kleinanzeigen.de/x?rule=$_59.JPG",
        ),
        (
            "https://img.kleinanzeigen.de/x?cache=yes&rule=%24_2.AUTO",
            "https://img.kleinanzeigen.de/x?cache=yes&rule=$_59.JPG",
        ),
        ("https://img.kleinanzeigen.de/x", "https://img.kleinanzeigen.de/x?rule=$_59.JPG"),
    ],
)
def test_large_image_url(src, expected):
    from sniper.platforms.kleinanzeigen import large_image

    assert large_image(src) == expected
