from datetime import UTC, datetime

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from sniper.db import OutboxEntry, Search, Seen, Target, get_setting, set_setting

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def make_search(session, name="Jacken") -> Search:
    s = Search(
        name=name,
        platform="kleinanzeigen",
        url="https://www.kleinanzeigen.de/s-jacke/k0",
        spec_json="{}",
        created_at=NOW,
    )
    session.add(s)
    session.flush()
    return s


def seen(search, external_id="1") -> Seen:
    return Seen(
        search_id=search.id,
        platform="kleinanzeigen",
        external_id=external_id,
        status="matched",
        listing_json="{}",
        first_seen_at=NOW,
    )


def test_migrate_creates_tables(engine):
    tables = set(inspect(engine).get_table_names())
    assert {"searches", "seen", "targets", "search_targets", "outbox", "settings"} <= tables


def test_search_defaults(session):
    s = make_search(session)
    session.commit()
    assert (s.interval_s, s.silence_days, s.active, s.state) == (300, 7, True, "pending")
    assert (s.consecutive_failures, s.silence_notified, s.exclude_words) == (0, False, "")


def test_seen_unique_per_search(session):
    a, b = make_search(session, "a"), make_search(session, "b")
    session.add_all([seen(a), seen(b)])
    session.commit()
    session.add(seen(a))
    with pytest.raises(IntegrityError):
        session.commit()


def test_delete_search_cascades_seen_and_keeps_outbox(session):
    s = make_search(session)
    t = Target(name="Handy", apprise_url="ntfy://x")
    session.add(t)
    session.flush()
    session.add(seen(s))
    session.add(
        OutboxEntry(
            target_id=t.id,
            search_id=s.id,
            kind="listing",
            title="t",
            body="b",
            next_attempt_at=NOW,
            created_at=NOW,
        )
    )
    session.commit()
    session.delete(s)
    session.commit()
    assert session.query(Seen).count() == 0
    entry = session.query(OutboxEntry).one()
    session.refresh(entry)
    assert entry.search_id is None


def test_search_targets_relationship(session):
    s = make_search(session)
    t = Target(name="Handy", apprise_url="ntfy://x", status_notices=True)
    s.targets.append(t)
    session.commit()
    assert [x.name for x in session.get(Search, s.id).targets] == ["Handy"]


def test_settings_roundtrip(session):
    assert get_setting(session, "ebay_client_id") == ""
    assert get_setting(session, "ebay_client_id", "x") == "x"
    set_setting(session, "ebay_client_id", "abc")
    set_setting(session, "ebay_client_id", "def")
    session.commit()
    assert get_setting(session, "ebay_client_id") == "def"


def test_datetimes_come_back_timezone_aware(session):
    s = make_search(session)
    session.commit()
    session.expire_all()
    assert session.get(Search, s.id).created_at == NOW
