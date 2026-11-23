import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from sniper.models import Platform, SearchSpec
from sniper.platforms.base import InvalidUrl, MissingCredentials, RateLimited
from sniper.platforms.ebay import EbayAdapter
from sniper.platforms.http import HttpResponse

FIX = Path(__file__).parent.parent / "fixtures" / "ebay"
TOKEN = (FIX / "token.json").read_text()
SEARCH = (FIX / "search.json").read_text()


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, *, params=None, headers=None):
        self.calls.append(("GET", url, params, headers))
        return self.responses.pop(0)

    def post(self, url, *, data=None, headers=None, auth=None):
        self.calls.append(("POST", url, data, auth))
        return self.responses.pop(0)


def ok(text):
    return HttpResponse(200, text, {})


class Clock:
    t = 1_000_000.0

    def __call__(self):
        return self.t


def adapter(responses, creds=("id", "secret"), clock=None):
    http = FakeHttp(responses)
    return EbayAdapter(http, lambda: creds, clock=clock or Clock()), http


def parse(url):
    return EbayAdapter(FakeHttp([]), lambda: ("", "")).parse_url(url)


def test_parse_url_translates_filters():
    spec = parse(
        "https://www.ebay.de/sch/i.html?_nkw=carhartt+jacke&_sacat=57988&_udlo=10&_udhi=60"
        "&LH_ItemCondition=3000&LH_BIN=1&LH_PrefLoc=1&_sop=10"
    )
    assert spec.platform is Platform.EBAY
    assert spec.params == {
        "q": "carhartt jacke",
        "category_ids": "57988",
        "filter": "price:[10..60],priceCurrency:EUR,conditionIds:{3000},"
        "buyingOptions:{FIXED_PRICE},itemLocationCountry:DE",
    }
    assert spec.ignored == ()


def test_parse_url_multiple_conditions_and_both_buying_options():
    spec = parse("ebay.de/sch/i.html?_nkw=x&LH_ItemCondition=1000|3000&LH_BIN=1&LH_Auction=1")
    assert spec.params["filter"] == "conditionIds:{1000|3000},buyingOptions:{FIXED_PRICE|AUCTION}"


def test_parse_url_reports_unknown_params():
    spec = parse("https://www.ebay.de/sch/i.html?_nkw=x&LH_Sold=1&_from=R40&_trksid=p1")
    assert spec.ignored == ("LH_Sold",)


def test_parse_url_open_price():
    assert parse("https://www.ebay.de/sch/i.html?_nkw=x&_udlo=10").params["filter"] == (
        "price:[10..],priceCurrency:EUR"
    )


def test_parse_url_category_zero_is_ignored():
    assert "category_ids" not in parse("https://www.ebay.de/sch/i.html?_nkw=x&_sacat=0").params


def test_parse_url_requires_keyword_or_category():
    with pytest.raises(InvalidUrl, match="keinen Suchbegriff"):
        parse("https://www.ebay.de/sch/i.html?_sacat=0")


def test_parse_url_requires_search_path():
    with pytest.raises(InvalidUrl):
        parse("https://www.ebay.de/itm/123")


def test_fetch_maps_listings():
    a, _ = adapter([ok(TOKEN), ok(SEARCH)])
    items = a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=carhartt"))
    first, auction, bare = items
    assert first.external_id == "256001112233"
    assert first.title == "Carhartt Detroit Jacket Gr. L"
    assert first.url == "https://www.ebay.de/itm/256001112233"
    assert first.price == Decimal("45.00")
    assert (first.shipping, first.shipping_cost) == (True, Decimal("4.99"))
    assert first.photo_urls == (
        "https://i.ebayimg.com/images/g/a/s-l225.jpg",
        "https://i.ebayimg.com/images/g/b/s-l225.jpg",
    )
    assert first.location == "10115 Berlin"
    assert first.posted_at == datetime(2026, 11, 23, 6, 52, 11, tzinfo=UTC)
    assert first.listing_type == "fixed"
    assert (auction.listing_type, auction.price) == ("auction", Decimal("12.50"))
    assert auction.location is None
    assert (bare.external_id, bare.photo_urls, bare.posted_at) == ("v1|256001112255|0", (), None)
    assert (bare.location, bare.shipping) == ("Hamburg", None)


def test_fetch_stores_no_seller_data():
    a, _ = adapter([ok(TOKEN), ok(SEARCH)])
    for item in a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=carhartt")):
        dumped = json.dumps(item.to_dict())
        assert "jacken_jens" not in dumped and "seller" not in dumped


def test_fetch_sends_marketplace_header_and_sort():
    a, http = adapter([ok(TOKEN), ok(SEARCH)])
    a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=carhartt"))
    method, url, params, headers = http.calls[1]
    assert url == "https://api.ebay.com/buy/browse/v1/item_summary/search"
    assert headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_DE"
    assert headers["Authorization"] == "Bearer v^1.1#TOKEN-A"
    assert (params["q"], params["sort"], params["limit"]) == ("carhartt", "newlyListed", "50")


def test_token_request():
    a, http = adapter([ok(TOKEN), ok(SEARCH)])
    a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=x"))
    method, url, data, auth = http.calls[0]
    assert (method, url) == ("POST", "https://api.ebay.com/identity/v1/oauth2/token")
    assert auth == ("id", "secret")
    assert data == {
        "grant_type": "client_credentials",
        "scope": "https://api.ebay.com/oauth/api_scope",
    }


def test_token_is_cached_until_shortly_before_expiry():
    clock = Clock()
    a, http = adapter([ok(TOKEN), ok(SEARCH), ok(SEARCH), ok(TOKEN), ok(SEARCH)], clock=clock)
    spec = parse("https://www.ebay.de/sch/i.html?_nkw=x")
    a.fetch(spec)
    clock.t += 7200 - 61
    a.fetch(spec)
    clock.t += 2
    a.fetch(spec)
    assert [c[0] for c in http.calls] == ["POST", "GET", "GET", "POST", "GET"]


def test_401_refreshes_token_once():
    a, http = adapter([ok(TOKEN), HttpResponse(401, "{}", {}), ok(TOKEN), ok(SEARCH)])
    assert len(a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=x"))) == 3
    assert [c[0] for c in http.calls] == ["POST", "GET", "POST", "GET"]


def test_missing_credentials():
    a, _ = adapter([], creds=("", ""))
    with pytest.raises(MissingCredentials, match="eBay-Zugangsdaten fehlen"):
        a.fetch(SearchSpec(Platform.EBAY, "https://www.ebay.de/sch/i.html?_nkw=x", {"q": "x"}))


def test_429_raises_rate_limited():
    a, _ = adapter([ok(TOKEN), HttpResponse(429, "", {})])
    with pytest.raises(RateLimited):
        a.fetch(parse("https://www.ebay.de/sch/i.html?_nkw=x"))


def test_build_adapters_registers_ebay():
    from sniper.platforms import build_adapters

    adapters = build_adapters(FakeHttp([]), lambda: ("", ""))
    assert isinstance(adapters[Platform.EBAY], EbayAdapter)
