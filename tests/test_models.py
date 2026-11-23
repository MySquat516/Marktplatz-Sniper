import json
from datetime import UTC, datetime
from decimal import Decimal

from sniper.models import Listing, Platform, SearchSpec, SearchState


def full_listing() -> Listing:
    return Listing(
        platform=Platform.KLEINANZEIGEN,
        external_id="2934",
        title="Jacke Gr. L",
        url="https://www.kleinanzeigen.de/s-anzeige/jacke/2934",
        price=Decimal("12.50"),
        currency="EUR",
        negotiable=True,
        listing_type="fixed",
        shipping=True,
        shipping_cost=Decimal("4.99"),
        photo_urls=("https://img/1.jpg", "https://img/2.jpg"),
        location="10115 Berlin",
        posted_at=datetime(2026, 11, 23, 6, 12, tzinfo=UTC),
    )


def test_listing_roundtrip():
    listing = full_listing()
    restored = Listing.from_dict(json.loads(json.dumps(listing.to_dict())))
    assert restored == listing


def test_listing_roundtrip_with_empty_optionals():
    listing = Listing(platform=Platform.EBAY, external_id="1", title="x", url="https://e/1")
    assert Listing.from_dict(json.loads(json.dumps(listing.to_dict()))) == listing


def test_listing_dict_has_no_seller_fields():
    assert not [k for k in full_listing().to_dict() if "seller" in k]


def test_search_spec_roundtrip():
    spec = SearchSpec(
        platform=Platform.EBAY,
        url="https://www.ebay.de/sch/i.html?_nkw=x",
        params={"q": "x"},
        ignored=("LH_Sold",),
    )
    assert SearchSpec.from_dict(json.loads(json.dumps(spec.to_dict()))) == spec


def test_labels():
    assert Platform.EBAY.label == "eBay"
    assert Platform.KLEINANZEIGEN.label == "Kleinanzeigen"
    assert Platform.WILLHABEN.label == "willhaben"
    assert SearchState.LAYOUT_CHANGED.label == "Seite unbekannt"
    assert SearchState.PENDING.label == "Neu"
    assert SearchState.BLOCKED.label == "Geblockt"
