from datetime import timedelta
from decimal import Decimal

from sniper.db import OutboxEntry, Seen
from sniper.engine.check import next_interval, run_check
from sniper.models import Platform, SearchState
from sniper.platforms.base import Blocked, LayoutChanged, NetworkError
from tests.engine.helpers import NOW, FakeAdapter, listing, make_search, make_target


def half(*_):
    return 0.5


def outbox(session, kind=None):
    q = session.query(OutboxEntry).order_by(OutboxEntry.id)
    return [e for e in q if kind is None or e.kind == kind]


def test_first_check_seeds_and_sends_nothing(session):
    s = make_search(session, targets=[make_target(session)])
    state = run_check(session, s, FakeAdapter([listing(1), listing(2)]), NOW, rng=half)
    assert state is SearchState.OK
    assert {x.status for x in session.query(Seen)} == {"seeded"}
    assert outbox(session) == []
    assert (s.last_ok_at, s.last_check_at, s.state) == (NOW, NOW, "ok")
    assert s.next_check_at == NOW + timedelta(seconds=300)


def test_second_check_notifies_new_listing(session):
    a, b = make_target(session, "a"), make_target(session, "b")
    s = make_search(session, targets=[a, b])
    adapter = FakeAdapter([listing(1)], [listing(2, price=Decimal("45")), listing(1)])
    run_check(session, s, adapter, NOW, rng=half)
    run_check(session, s, adapter, NOW + timedelta(minutes=5), rng=half)
    entries = outbox(session, "listing")
    assert sorted(e.target_id for e in entries) == sorted([a.id, b.id])
    assert entries[0].title == "[Kleinanzeigen] Jacke 2 – 45 €"
    assert s.last_match_at == NOW + timedelta(minutes=5)
    matched = session.query(Seen).filter_by(status="matched").one()
    assert matched.external_id == "2"


def test_rejected_listing_is_recorded_with_reason(session):
    s = make_search(session, targets=[make_target(session)], exclude_words="defekt")
    adapter = FakeAdapter([], [listing(1, title="Jacke defekt")])
    run_check(session, s, adapter, NOW, rng=half)
    run_check(session, s, adapter, NOW, rng=half)
    row = session.query(Seen).one()
    assert (row.status, row.reason) == ("rejected", "Ausschlusswort: defekt")
    assert outbox(session) == []


def test_same_listing_in_two_searches_notifies_both(session):
    t = make_target(session)
    s1 = make_search(session, "eins", targets=[t])
    s2 = make_search(session, "zwei", targets=[t])
    for s in (s1, s2):
        run_check(session, s, FakeAdapter([], [listing(7)]), NOW, rng=half)
        run_check(session, s, FakeAdapter([listing(7)]), NOW, rng=half)
    # erster Check pro Suche seedet leer, zweiter meldet Anzeige 7 – für jede Suche einmal
    assert sorted(e.search_id for e in outbox(session, "listing")) == sorted([s1.id, s2.id])


def test_overflow_enqueues_summary(session):
    s = make_search(session, targets=[make_target(session)])
    adapter = FakeAdapter([], [listing(i) for i in range(12)])
    run_check(session, s, adapter, NOW, rng=half)
    run_check(session, s, adapter, NOW, rng=half)
    assert len(outbox(session, "listing")) == 11
    assert outbox(session, "listing")[-1].title == "[Kleinanzeigen] Jacken: 2 weitere neue Anzeigen"


def test_blocked_notifies_once_and_backs_off(session):
    status = make_target(session, "status", status_notices=True)
    s = make_search(session, targets=[make_target(session)])
    adapter = FakeAdapter(*[Blocked("HTTP 403")] * 4)
    gaps = []
    for _ in range(4):
        assert run_check(session, s, adapter, NOW, rng=half) is SearchState.BLOCKED
        gaps.append((s.next_check_at - NOW).total_seconds())
    assert gaps == [600, 1200, 2400, 3600]
    notices = outbox(session, "status")
    assert [(e.target_id, e.title) for e in notices] == [(status.id, "Sniper: Jacken geblockt")]


def test_backoff_never_exceeds_an_hour_with_jitter(session):
    s = make_search(session, consecutive_failures=5)
    assert next_interval(s, SearchState.BLOCKED, rng=lambda: 1.0) == timedelta(seconds=3600)


def test_jitter_range(session):
    s = make_search(session)
    assert next_interval(s, SearchState.OK, rng=lambda: 0.0) == timedelta(seconds=240)
    assert next_interval(s, SearchState.OK, rng=lambda: 1.0) == timedelta(seconds=360)


def test_layout_changed_notifies_immediately(session):
    make_target(session, "status", status_notices=True)
    s = make_search(session)
    assert run_check(session, s, FakeAdapter(LayoutChanged("x")), NOW, rng=half) is (
        SearchState.LAYOUT_CHANGED
    )
    assert [e.title for e in outbox(session, "status")] == ["Sniper: Jacken – Seite unbekannt"]


def test_error_notifies_after_three(session):
    make_target(session, "status", status_notices=True)
    s = make_search(session)
    adapter = FakeAdapter(*[NetworkError("Timeout")] * 4)
    counts = []
    for _ in range(4):
        run_check(session, s, adapter, NOW, rng=half)
        counts.append(len(outbox(session, "status")))
    assert counts == [0, 0, 1, 1]
    assert outbox(session, "status")[0].body.endswith("Letzter Fehler: Timeout")
    assert (s.state, s.last_error, s.consecutive_failures) == ("error", "Timeout", 4)


def test_unexpected_exception_counts_as_error(session):
    s = make_search(session)
    assert run_check(session, s, FakeAdapter(RuntimeError("kaputt")), NOW, rng=half) is (
        SearchState.ERROR
    )
    assert s.next_check_at == NOW + timedelta(seconds=300)


def test_recovery_after_notice(session):
    make_target(session, "status", status_notices=True)
    s = make_search(session)
    run_check(session, s, FakeAdapter(Blocked("x"), []), NOW, rng=half)
    run_check(session, s, FakeAdapter([]), NOW, rng=half)
    assert [e.title for e in outbox(session, "status")] == [
        "Sniper: Jacken geblockt",
        "Sniper: Jacken läuft wieder",
    ]
    assert (s.notified_state, s.consecutive_failures, s.state) == (None, 0, "ok")


def test_no_recovery_message_without_prior_notice(session):
    make_target(session, "status", status_notices=True)
    s = make_search(session)
    run_check(session, s, FakeAdapter(NetworkError("x")), NOW, rng=half)
    run_check(session, s, FakeAdapter([]), NOW, rng=half)
    assert outbox(session, "status") == []


def test_silence_warning_once(session):
    make_target(session, "status", status_notices=True)
    s = make_search(
        session, created_at=NOW - timedelta(days=8), last_ok_at=NOW - timedelta(minutes=5)
    )
    run_check(session, s, FakeAdapter([]), NOW, rng=half)
    run_check(session, s, FakeAdapter([]), NOW, rng=half)
    assert [e.title for e in outbox(session, "status")] == ["Sniper: Jacken ist still"]
    assert s.silence_notified is True
    run_check(session, s, FakeAdapter([listing(1)]), NOW, rng=half)
    assert s.silence_notified is False


def test_silence_disabled_with_zero_days(session):
    make_target(session, "status", status_notices=True)
    s = make_search(session, created_at=NOW - timedelta(days=30), last_ok_at=NOW, silence_days=0)
    run_check(session, s, FakeAdapter([]), NOW, rng=half)
    assert outbox(session, "status") == []


def test_status_notices_only_to_flagged_targets(session):
    flagged = make_target(session, "flagged", status_notices=True)
    plain = make_target(session, "plain")
    s = make_search(session, targets=[plain])
    run_check(session, s, FakeAdapter(Blocked("x")), NOW, rng=half)
    assert [e.target_id for e in outbox(session)] == [flagged.id]


def test_ebay_check_counts_quota(session):
    from sniper.engine import quota

    s = make_search(session, platform=Platform.EBAY)
    run_check(session, s, FakeAdapter([], platform=Platform.EBAY), NOW, rng=half)
    run_check(session, s, FakeAdapter(NetworkError("x"), platform=Platform.EBAY), NOW, rng=half)
    k = make_search(session, "ka")
    run_check(session, k, FakeAdapter([]), NOW, rng=half)
    assert quota.calls_today(session, NOW) == 2
    assert quota.calls_today(session, NOW + timedelta(days=1)) == 0
