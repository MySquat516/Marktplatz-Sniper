from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sniper.engine.detect import Filters, detect
from sniper.models import Listing, Platform

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def item(i, title="Jacke", price=None, age_h=None):
    return Listing(
        platform=Platform.EBAY,
        external_id=str(i),
        title=title,
        url=f"https://e/{i}",
        price=None if price is None else Decimal(price),
        posted_at=None if age_h is None else NOW - timedelta(hours=age_h),
    )


def run(listings, seen=(), filters=Filters(), first=False):
    return detect(listings, set(seen), filters, first_check=first, now=NOW)


def test_first_check_seeds_silently():
    d = run([item(1), item(2)], first=True)
    assert [(v.listing.external_id, v.status, v.notify) for v in d.verdicts] == [
        ("1", "seeded", False),
        ("2", "seeded", False),
    ]
    assert d.overflow == 0


def test_seen_ids_are_skipped():
    d = run([item(1), item(2)], seen={"1"})
    assert [v.listing.external_id for v in d.verdicts] == ["2"]
    assert (d.verdicts[0].status, d.verdicts[0].notify) == ("matched", True)


def test_duplicate_ids_in_one_response_count_once():
    assert len(run([item(1), item(1, title="nochmal")]).verdicts) == 1


def test_too_old_rejected():
    v = run([item(1, age_h=25)]).verdicts[0]
    assert (v.status, v.reason, v.notify) == ("rejected", "zu alt", False)


def test_just_inside_freshness_window_passes():
    assert run([item(1, age_h=23.9)]).verdicts[0].status == "matched"


def test_unknown_age_passes():
    assert run([item(1)]).verdicts[0].status == "matched"


def test_max_price():
    f = Filters(max_price=Decimal("60"))
    d = run(
        [item(1, price="61"), item(2, price=None), item(3, price="0"), item(4, price="60")],
        filters=f,
    )
    assert [(v.status, v.reason) for v in d.verdicts] == [
        ("rejected", "über Höchstpreis"),
        ("matched", None),
        ("matched", None),
        ("matched", None),
    ]


def test_exclude_words_casefold():
    f = Filters(exclude_words=("Defekt", "ärmel"))
    d = run([item(1, title="jacke DEFEKT"), item(2, title="Ärmel kaputt"), item(3)], filters=f)
    assert [(v.status, v.reason) for v in d.verdicts] == [
        ("rejected", "Ausschlusswort: Defekt"),
        ("rejected", "Ausschlusswort: ärmel"),
        ("matched", None),
    ]


def test_cap_and_overflow():
    d = run([item(i) for i in range(13)])
    assert [v.notify for v in d.verdicts] == [True] * 10 + [False] * 3
    assert [v.listing.external_id for v in d.verdicts if v.notify] == [str(i) for i in range(10)]
    assert all(v.status == "matched" for v in d.verdicts)
    assert d.overflow == 3


def test_rejected_do_not_count_towards_cap():
    d = run([item(i, age_h=30) for i in range(5)] + [item(i) for i in range(5, 15)])
    assert sum(v.notify for v in d.verdicts) == 10
    assert d.overflow == 0


def test_filters_from_text():
    f = Filters.from_text(Decimal("60"), "defekt\n\n  fake \r\n")
    assert f == Filters(max_price=Decimal("60"), exclude_words=("defekt", "fake"))
    assert Filters.from_text(None, "") == Filters()
