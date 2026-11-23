import pytest

from sniper.notify.message import Message
from sniper.notify.sender import SendError, send


def test_sender_invalid_url_raises():
    with pytest.raises(SendError, match="Ungültige Apprise-Adresse"):
        send("kaputt://", Message("T", "B"))


def test_sender_reports_failed_delivery(monkeypatch):
    import apprise

    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, **kw: False)
    with pytest.raises(SendError, match="Zustellung fehlgeschlagen"):
        send("json://localhost:1/", Message("T", "B"))


def test_sender_retries_without_attachment(monkeypatch):
    import apprise

    calls = []

    def fake_notify(self, **kw):
        calls.append(kw.get("attach"))
        return kw.get("attach") is None

    monkeypatch.setattr(apprise.Apprise, "notify", fake_notify)
    send("json://localhost:1/", Message("T", "B", "https://img/1.jpg"))
    assert len(calls) == 2 and calls[0] is not None and calls[1] is None
