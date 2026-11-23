from datetime import UTC, datetime, timedelta

from sniper.db import OutboxEntry, Target
from sniper.notify.message import Message
from sniper.notify.outbox import deliver_due, enqueue
from sniper.notify.sender import SendError

NOW = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)


def targets(session, *names):
    ts = [Target(name=n, apprise_url=f"ntfy://{n}") for n in names]
    session.add_all(ts)
    session.flush()
    return ts


class Recorder:
    def __init__(self, fail_for=()):
        self.fail_for = set(fail_for)
        self.sent = []

    def __call__(self, url, message):
        if url in self.fail_for:
            raise SendError("Zustellung fehlgeschlagen")
        self.sent.append((url, message))


def test_enqueue_creates_one_entry_per_target(session):
    a, b = targets(session, "a", "b")
    enqueue(
        session, [a, b], Message("T", "B", "https://img"), kind="listing", search_id=None, now=NOW
    )
    session.commit()
    rows = session.query(OutboxEntry).order_by(OutboxEntry.id).all()
    assert [(r.target_id, r.title, r.body, r.attach_url, r.kind) for r in rows] == [
        (a.id, "T", "B", "https://img", "listing"),
        (b.id, "T", "B", "https://img", "listing"),
    ]
    assert all(r.next_attempt_at == NOW and r.attempts == 0 for r in rows)


def test_deliver_due_marks_sent(session):
    (a,) = targets(session, "a")
    enqueue(session, [a], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    send = Recorder()
    assert deliver_due(session, NOW, send=send) == 1
    assert send.sent == [("ntfy://a", Message("T", "B"))]
    assert session.query(OutboxEntry).one().sent_at == NOW
    assert deliver_due(session, NOW, send=send) == 0


def test_not_yet_due_is_skipped(session):
    (a,) = targets(session, "a")
    enqueue(session, [a], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    assert deliver_due(session, NOW - timedelta(seconds=1), send=Recorder()) == 0


def test_failed_target_does_not_block_others(session):
    a, b = targets(session, "a", "b")
    enqueue(session, [a, b], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    assert deliver_due(session, NOW, send=Recorder(fail_for={"ntfy://a"})) == 1
    ea, eb = session.query(OutboxEntry).order_by(OutboxEntry.id).all()
    assert eb.sent_at == NOW
    assert (ea.sent_at, ea.attempts, ea.next_attempt_at) == (None, 1, NOW + timedelta(minutes=1))
    assert ea.last_error == "Zustellung fehlgeschlagen"


def test_unexpected_exception_is_treated_as_failure(session):
    (a,) = targets(session, "a")
    enqueue(session, [a], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()

    def boom(url, message):
        raise RuntimeError("kaputt")

    assert deliver_due(session, NOW, send=boom) == 0
    assert session.query(OutboxEntry).one().attempts == 1


def test_backoff_sequence(session):
    (a,) = targets(session, "a")
    enqueue(session, [a], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    send = Recorder(fail_for={"ntfy://a"})
    gaps = []
    t = NOW
    for _ in range(5):
        deliver_due(session, t, send=send)
        entry = session.query(OutboxEntry).one()
        gaps.append(entry.next_attempt_at - t)
        t = entry.next_attempt_at
    assert gaps == [timedelta(minutes=m) for m in (1, 5, 15, 60, 60)]


def test_gives_up_after_24h(session):
    (a,) = targets(session, "a")
    enqueue(session, [a], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    later = NOW + timedelta(hours=24)
    deliver_due(session, later, send=Recorder(fail_for={"ntfy://a"}))
    entry = session.query(OutboxEntry).one()
    assert entry.failed_at == later
    assert deliver_due(session, later + timedelta(hours=1), send=Recorder()) == 0
