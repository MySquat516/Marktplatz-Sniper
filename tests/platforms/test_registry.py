import pytest

from sniper.models import Platform
from sniper.platforms import adapter_for_url
from sniper.platforms.base import InvalidUrl


class Dummy:
    def __init__(self, platform):
        self.platform = platform


ADAPTERS = {p: Dummy(p) for p in Platform}


@pytest.mark.parametrize(
    ("url", "platform"),
    [
        ("https://www.ebay.de/sch/i.html?_nkw=x", Platform.EBAY),
        ("ebay.de/sch/i.html?_nkw=x", Platform.EBAY),
        ("https://m.ebay.de/sch/i.html?_nkw=x", Platform.EBAY),
        ("https://www.kleinanzeigen.de/s-jacke/k0", Platform.KLEINANZEIGEN),
        ("kleinanzeigen.de/s-jacke/k0?utm_source=app", Platform.KLEINANZEIGEN),
        ("  https://www.kleinanzeigen.de/s-jacke/k0  ", Platform.KLEINANZEIGEN),
        (
            "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=x",
            Platform.WILLHABEN,
        ),
    ],
)
def test_adapter_for_url(url, platform):
    assert adapter_for_url(url, ADAPTERS).platform is platform


@pytest.mark.parametrize("url", ["https://example.com", "", "https://www.ebay.com/sch/i.html"])
def test_unknown_site(url):
    with pytest.raises(InvalidUrl, match="Unbekannte Seite"):
        adapter_for_url(url, ADAPTERS)
