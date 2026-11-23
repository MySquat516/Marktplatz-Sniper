from datetime import timedelta

from sniper.db import OutboxEntry, Search, make_session_factory
from sniper.engine.scheduler import Scheduler
from sniper.models import Platform
from sniper.notify.message import Message
from sniper.notify.outbox import enqueue
from tests.engine.helpers import NOW, FakeAdapter, make_search, make_target


def scheduler(engine, adapter, now=NOW, send=None):
    kw = {"send": send} if send else {}
    return Scheduler(
        make_session_factory(engine), {Platform.KLEINANZEIGEN: adapter}, now=lambda: now, **kw
    )


def test_tick_runs_due_searches_once(engine, session):
    for name in ("a", "b", "c"):
        make_search(session, name, next_check_at=NOW - timedelta(days=3))
    session.commit()
    adapter = FakeAdapter()
    sched = scheduler(engine, adapter)
    sched.tick()
    assert adapter.calls == 3
    session.expire_all()
    assert all(s.next_check_at > NOW for s in session.query(Search))
    sched.tick()
    assert adapter.calls == 3


def test_never_checked_search_is_due(engine, session):
    make_search(session)
    session.commit()
    adapter = FakeAdapter()
    scheduler(engine, adapter).tick()
    assert adapter.calls == 1


def test_paused_searches_are_skipped(engine, session):
    make_search(session, active=False)
    session.commit()
    adapter = FakeAdapter()
    scheduler(engine, adapter).tick()
    assert adapter.calls == 0


def test_one_failing_search_does_not_stop_others(engine, session):
    make_search(session, "a", next_check_at=NOW - timedelta(minutes=2))
    make_search(session, "b", next_check_at=NOW - timedelta(minutes=1))
    session.commit()

    class Exploding(FakeAdapter):
        def fetch(self, spec):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("kaputt")
            return []

    adapter = Exploding()
    scheduler(engine, adapter).tick()
    assert adapter.calls == 2


def test_broken_search_row_does_not_stop_others(engine, session):
    make_search(session, "kaputt", next_check_at=NOW - timedelta(minutes=2)).spec_json = "{"
    make_search(session, "gut", next_check_at=NOW - timedelta(minutes=1))
    session.commit()
    adapter = FakeAdapter()
    scheduler(engine, adapter).tick()
    assert adapter.calls == 1


def test_tick_delivers_outbox(engine, session):
    t = make_target(session)
    enqueue(session, [t], Message("T", "B"), kind="status", search_id=None, now=NOW)
    session.commit()
    sent = []
    scheduler(engine, FakeAdapter(), send=lambda url, msg: sent.append(url)).tick()
    assert sent == ["ntfy://Handy"]
    session.expire_all()
    assert session.query(OutboxEntry).one().sent_at == NOW


def test_check_now(engine, session):
    s = make_search(session, next_check_at=NOW + timedelta(hours=1))
    session.commit()
    scheduler(engine, FakeAdapter()).check_now(s.id)
    session.expire_all()
    assert session.get(Search, s.id).next_check_at == NOW


def test_start_and_stop_thread(engine):
    sched = Scheduler(make_session_factory(engine), {}, tick_s=0.01)
    thread = sched.start()
    assert thread.is_alive()
    sched.stop()
    thread.join(timeout=2)
    assert not thread.is_alive()
