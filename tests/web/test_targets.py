from datetime import UTC, datetime

from sniper.db import OutboxEntry, Target
from sniper.notify.message import Button
from tests.web.conftest import Sent, logged_in, post


def test_add_target_and_mask_url(client, session):
    post(
        client,
        "/benachrichtigungen",
        name="Handy",
        apprise_url="tgram://123456:ABCDEF/987654",
        status_notices="on",
    )
    t = session.query(Target).one()
    assert (t.name, t.status_notices) == ("Handy", True)
    page = client.get("/benachrichtigungen").get_data(as_text=True)
    assert "tgram://…7654" in page
    assert "ABCDEF" not in page


def test_invalid_apprise_url_rejected(client, session):
    page = post(client, "/benachrichtigungen", name="x", apprise_url="kaputt://")
    assert "Ungültige Apprise-Adresse" in page.get_data(as_text=True)
    assert session.query(Target).count() == 0


def test_target_test_send(make_app, session):
    sent = Sent()
    client = logged_in(make_app(send=sent))
    session.add(Target(name="Handy", apprise_url="ntfy://topic"))
    session.commit()
    t = session.query(Target).one()
    page = post(client, f"/benachrichtigungen/{t.id}/test").get_data(as_text=True)
    assert sent.messages[0][0] == "ntfy://topic"
    assert sent.messages[0][1].title == "Sniper: Test"
    assert "Test gesendet" in page


def test_target_test_send_failure_is_shown(make_app, session):
    client = logged_in(make_app(send=Sent(fail=True)))
    session.add(Target(name="Handy", apprise_url="ntfy://topic"))
    session.commit()
    t = session.query(Target).one()
    page = post(client, f"/benachrichtigungen/{t.id}/test").get_data(as_text=True)
    assert "Zustellung fehlgeschlagen" in page


def test_delete_target(client, session):
    session.add(Target(name="Handy", apprise_url="ntfy://topic"))
    session.commit()
    post(client, f"/benachrichtigungen/{session.query(Target).one().id}/loeschen")
    session.expire_all()
    assert session.query(Target).count() == 0


def test_failed_deliveries_listed_on_hits_page(client, session):
    session.add(Target(name="Handy", apprise_url="ntfy://topic"))
    session.flush()
    now = datetime(2026, 11, 23, 7, 0, tzinfo=UTC)
    session.add(
        OutboxEntry(
            target_id=session.query(Target).one().id,
            kind="listing",
            title="[eBay] Weste – 5 €",
            body="b",
            next_attempt_at=now,
            created_at=now,
            failed_at=now,
            last_error="Zustellung fehlgeschlagen",
        )
    )
    session.commit()
    page = client.get("/treffer").get_data(as_text=True)
    assert "nicht zugestellt" in page and "[eBay] Weste – 5 €" in page


def _send_test(make_app, session, base_url="http://localhost"):
    sent = Sent()
    client = make_app(send=sent).test_client()
    with client.session_transaction(base_url=base_url) as s:
        s["csrf"] = "tok"
    session.add(Target(name="Handy", apprise_url="tgram://123456:ABCDEF/987654"))
    session.commit()
    t = session.query(Target).one()
    client.post(f"/benachrichtigungen/{t.id}/test", data={"csrf": "tok"}, base_url=base_url)
    return sent.messages[0][1]


def test_test_message_has_a_button_back_to_the_sniper(make_app, session):
    message = _send_test(make_app, session, "http://192.168.178.51:8092")
    assert message.buttons == (
        (Button("Sniper öffnen", "http://192.168.178.51:8092/", "primary"),),
    )


def test_test_message_has_no_button_when_opened_on_the_server_itself(make_app, session):
    assert _send_test(make_app, session).buttons == ()
