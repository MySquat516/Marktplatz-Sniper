import json
import re
from datetime import timedelta
from decimal import Decimal

import pytest

from sniper.db import Seen
from sniper.models import Platform
from tests.engine.helpers import NOW, listing, make_search


@pytest.fixture
def data(session):
    jacken = make_search(session, "Jacken")
    sneaker = make_search(session, "Sneaker", platform=Platform.EBAY)
    rows = [
        (jacken, 1, "Jacke billig", "10", "matched", None, 1),
        (jacken, 2, "Jacke teuer", "90", "matched", None, 2),
        (jacken, 3, "Jacke ohne Preis", None, "matched", None, 3),
        (jacken, 4, "Jacke zu alt", "50", "rejected", "zu alt", 4),
        (sneaker, 5, "Sneaker mittel", "40", "matched", None, 5),
        (jacken, 6, "Jacke gemerkt", "5", "seeded", None, 6),
    ]
    for search, i, title, price, status, reason, minutes_ago in rows:
        item = listing(
            i,
            platform=Platform(search.platform),
            title=title,
            price=None if price is None else Decimal(price),
        )
        session.add(
            Seen(
                search_id=search.id,
                platform=search.platform,
                external_id=str(i),
                status=status,
                reason=reason,
                listing_json=json.dumps(item.to_dict()),
                first_seen_at=NOW - timedelta(minutes=minutes_ago),
            )
        )
    session.commit()
    return {"jacken": jacken.id, "sneaker": sneaker.id}


def titles(client, query=""):
    page = client.get("/treffer" + query).get_data(as_text=True)
    return re.findall(r'rel="noopener">([^<]+)</a>', page)


def test_default_is_newest_first_without_seeded(client, data):
    assert titles(client) == [
        "Jacke billig",
        "Jacke teuer",
        "Jacke ohne Preis",
        "Jacke zu alt",
        "Sneaker mittel",
    ]


def test_sort_by_price_ascending_puts_missing_prices_last(client, data):
    assert titles(client, "?sort=preis_auf") == [
        "Jacke billig",
        "Sneaker mittel",
        "Jacke zu alt",
        "Jacke teuer",
        "Jacke ohne Preis",
    ]


def test_sort_by_price_descending_puts_missing_prices_last(client, data):
    assert titles(client, "?sort=preis_ab") == [
        "Jacke teuer",
        "Jacke zu alt",
        "Sneaker mittel",
        "Jacke billig",
        "Jacke ohne Preis",
    ]


def test_filter_by_search(client, data):
    assert titles(client, f"?suche={data['sneaker']}") == ["Sneaker mittel"]


def test_filter_by_platform(client, data):
    assert titles(client, "?plattform=kleinanzeigen") == [
        "Jacke billig",
        "Jacke teuer",
        "Jacke ohne Preis",
        "Jacke zu alt",
    ]


def test_filter_by_status(client, data):
    assert titles(client, "?status=verworfen") == ["Jacke zu alt"]
    assert "Jacke zu alt" not in titles(client, "?status=gemeldet")


def test_filters_combine(client, data):
    query = f"?suche={data['jacken']}&status=gemeldet&sort=preis_ab"
    assert titles(client, query) == ["Jacke teuer", "Jacke billig", "Jacke ohne Preis"]


def test_unknown_values_are_ignored(client, data):
    resp = client.get("/treffer?sort=quatsch&suche=abc&plattform=xyz&status=egal")
    assert resp.status_code == 200
    assert len(re.findall(r'rel="noopener">', resp.get_data(as_text=True))) == 5


def test_current_choices_are_preselected(client, data):
    page = client.get(f"/treffer?sort=preis_auf&suche={data['jacken']}&status=verworfen").get_data(
        as_text=True
    )
    assert '<option value="preis_auf" selected>' in page
    assert f'<option value="{data["jacken"]}" selected>' in page
    assert '<option value="verworfen" selected>' in page


def test_empty_filter_result_says_so(client, data):
    page = client.get(f"/treffer?suche={data['sneaker']}&status=verworfen").get_data(as_text=True)
    assert "Keine Treffer für diese Auswahl." in page
