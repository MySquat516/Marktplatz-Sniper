"""Tests zu den Befunden aus dem Abschluss-Review. Jeder ist vor dem Fix rot gewesen."""

import json
from datetime import timedelta
from pathlib import Path

import pytest

from sniper.db import OutboxEntry, Search, Seen, Target, make_session_factory
from sniper.engine.check import next_interval, run_check
from sniper.engine.scheduler import Scheduler
from sniper.models import Platform, SearchSpec, SearchState
from sniper.notify.message import Message
from sniper.notify.outbox import deliver_due, enqueue
from sniper.notify.sender import send
from sniper.platforms.base import LayoutChanged
from sniper.platforms.http import HttpResponse
from sniper.platforms.kleinanzeigen import KleinanzeigenAdapter
from tests.engine.helpers import NOW, FakeAdapter, listing, make_search, make_target
from tests.web.conftest import KA_URL, logged_in, post

FIX = Path(__file__).parent.parent / "fixtures" / "kleinanzeigen"


# Important 1: eine Suche darf nicht in einer Schleife hängen bleiben


def test_backoff_exponent_cannot_overflow(session):
    s = make_search(session, consecutive_failures=2000)
    assert next_interval(s, SearchState.BLOCKED, rng=lambda: 0.5) == timedelta(seconds=3600)


def test_failure_after_fetch_still_moves_next_check(engine, session, monkeypatch):
    make_search(session, next_check_at=NOW - timedelta(minutes=1))
    session.commit()
    calls = []

    def exploding(*args, **kwargs):
        calls.append(1)
        raise RuntimeError("Platte voll")

    monkeypatch.setattr("sniper.engine.scheduler.run_check", exploding)
    sched = Scheduler(
        make_session_factory(engine), {Platform.KLEINANZEIGEN: FakeAdapter()}, now=lambda: NOW
    )
    sched.tick()
    sched.tick()
    assert len(calls) == 1
    session.expire_all()
    assert session.query(Search).one().next_check_at > NOW


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("interval_min", "99999999999", "höchstens 1440 Minuten"),
        ("silence_days", "99999999999", "höchstens 365 Tage"),
    ],
)
def test_absurd_form_values_are_rejected(make_app, session, field, value, message):
    client = logged_in(make_app())
    data = {"url": KA_URL, "name": "x", "interval_min": "5", "silence_days": "7", field: value}
    page = post(client, "/suchen", **data).get_data(as_text=True)
    assert message in page
    assert session.query(Search).count() == 0


# Important 2: eine Meldung darf nicht bei jedem Durchlauf erneut rausgehen


def test_failed_commit_after_send_does_not_resend(session, monkeypatch):
    t = make_target(session)
    enqueue(session, [t], Message("T", "B"), kind="listing", search_id=None, now=NOW)
    session.commit()
    sent = []
    commits = []
    real_commit = session.commit

    def flaky_commit():
        commits.append(1)
        if len(commits) == 2:
            raise RuntimeError("database is locked")
        real_commit()

    monkeypatch.setattr(session, "commit", flaky_commit)
    with pytest.raises(RuntimeError):
        deliver_due(session, NOW, send=lambda url, msg: sent.append(url))
    session.rollback()
    monkeypatch.undo()
    deliver_due(session, NOW, send=lambda url, msg: sent.append(url))
    assert len(sent) == 1


# Important 3: Titel mit < und & müssen bei Telegram ankommen


def test_telegram_receives_escaped_plain_text(monkeypatch):
    import requests

    payloads = []

    class Ok:
        status_code = 200
        content = b'{"ok": true}'
        text = '{"ok": true}'

    def fake_post(url, *args, **kwargs):
        payloads.append(kwargs.get("data") or kwargs.get("json"))
        return Ok()

    monkeypatch.setattr(requests, "post", fake_post)
    send("tgram://123456789:abcdefghijklmnop/12345", Message("Nike <3 H&M Jacke", "Preis <b>"))
    text = json.dumps(payloads)
    assert "&lt;3 H&amp;M" in text
    assert "<3" not in text


# Important 4: URL-Änderung während eines laufenden Checks


def test_url_edit_during_fetch_discards_results(engine, session):
    t = make_target(session)
    s = make_search(session, targets=[t], last_ok_at=NOW - timedelta(minutes=5))
    session.commit()
    factory = make_session_factory(engine)

    class EditingAdapter(FakeAdapter):
        def fetch(self, spec):
            with factory() as other:
                row = other.get(Search, s.id)
                new_spec = SearchSpec(Platform.KLEINANZEIGEN, "https://example/neu")
                row.url = new_spec.url
                row.spec_json = json.dumps(new_spec.to_dict())
                row.last_ok_at = None
                other.commit()
            return [listing(i) for i in range(20)]

    run_check(session, s, EditingAdapter(), NOW, rng=lambda: 0.5)
    session.expire_all()
    row = session.get(Search, s.id)
    assert row.last_ok_at is None
    assert session.query(Seen).count() == 0
    assert session.query(OutboxEntry).count() == 0


def test_pause_during_fetch_keeps_pause(engine, session):
    s = make_search(session, last_ok_at=NOW - timedelta(minutes=5))
    session.commit()
    factory = make_session_factory(engine)

    class PausingAdapter(FakeAdapter):
        def fetch(self, spec):
            with factory() as other:
                row = other.get(Search, s.id)
                row.active, row.state = False, "paused"
                other.commit()
            return [listing(1)]

    run_check(session, s, PausingAdapter(), NOW, rng=lambda: 0.5)
    session.expire_all()
    assert session.get(Search, s.id).state == "paused"


# Important 5: kaputte Selektoren dürfen nicht als „OK, nichts Neues“ durchgehen


class Http:
    def __init__(self, text):
        self.text = text

    def get(self, url, **kw):
        return HttpResponse(200, self.text, {})


def ka_fetch(text):
    a = KleinanzeigenAdapter(Http(text))
    return a.fetch(a.parse_url(KA_URL))


def test_cards_without_parseable_title_are_layout_changed():
    page = (
        (FIX / "real-results.html")
        .read_text(encoding="utf-8")
        .replace("<h3", "<h2")
        .replace("</h3>", "</h2>")
    )
    with pytest.raises(LayoutChanged):
        ka_fetch(page)


def test_cards_without_ad_ids_are_layout_changed():
    page = (FIX / "real-results.html").read_text(encoding="utf-8").replace("data-adid=", "data-id=")
    with pytest.raises(LayoutChanged):
        ka_fetch(page)


def test_list_with_only_ad_slots_is_empty_not_broken():
    page = (
        '<ul id="srchrslt-adtable">'
        '<li class="mb-small"><div data-liberty-position-name="x"></div></li></ul>'
    )
    assert ka_fetch(page) == []


# Important 6: Suchen ohne Ziel und Statusmeldungen umschalten


def test_search_without_target_shows_warning(make_app, session):
    make_search(session, "Ohne Ziel")
    session.commit()
    page = logged_in(make_app()).get("/suchen").get_data(as_text=True)
    assert "Kein Benachrichtigungsziel" in page


def test_new_target_can_be_added_to_existing_searches(make_app, session):
    s = make_search(session)
    session.commit()
    post(
        logged_in(make_app()),
        "/benachrichtigungen",
        name="Handy",
        apprise_url="ntfy://thema",
        add_to_all="on",
    )
    session.expire_all()
    assert [t.name for t in session.get(Search, s.id).targets] == ["Handy"]


def test_status_notices_can_be_toggled(make_app, session):
    session.add(Target(name="Handy", apprise_url="ntfy://thema"))
    session.commit()
    t_id = session.query(Target).one().id
    client = logged_in(make_app())
    post(client, f"/benachrichtigungen/{t_id}/status")
    session.expire_all()
    assert session.get(Target, t_id).status_notices is True
    post(client, f"/benachrichtigungen/{t_id}/status")
    session.expire_all()
    assert session.get(Target, t_id).status_notices is False


# Important 7: Umlaute im Passwort


def test_login_with_umlaut_password(make_app):
    c = logged_in(make_app(password="Schlüssel123"))
    post(c, "/login", username="admin", password="Schlüssel123")
    assert c.get("/suchen").status_code == 200
    page = post(c, "/login", username="admin", password="Schlussel123")
    assert page.status_code == 200
