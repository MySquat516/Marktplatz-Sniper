import pytest

from sniper.notify.message import Button, Message
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
    send("json://localhost:1/", Message("T", "B", "https://img/1.jpg"), fetch_image=jpeg)
    assert len(calls) == 2 and calls[0] is not None and calls[1] is None


JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


def jpeg(url):
    return JPEG, "image/jpeg"


def test_image_is_downloaded_and_attached_as_local_file(monkeypatch):
    import apprise

    seen = []

    def fake_notify(self, **kw):
        attach = kw.get("attach")
        if attach is not None:
            path = attach[0].path
            with open(path, "rb") as f:
                seen.append((path, f.read()))
        return True

    monkeypatch.setattr(apprise.Apprise, "notify", fake_notify)
    fetched = []
    send(
        "json://localhost:1/",
        Message("T", "B", "https://img/1"),
        fetch_image=lambda url: fetched.append(url) or jpeg(url),
    )
    assert fetched == ["https://img/1"]
    ((path, data),) = seen
    assert path.endswith(".jpg") and data == JPEG


def test_png_keeps_png_extension(monkeypatch):
    import apprise

    paths = []
    monkeypatch.setattr(
        apprise.Apprise, "notify", lambda self, **kw: paths.append(kw["attach"][0].path) or True
    )
    send(
        "json://localhost:1/",
        Message("T", "B", "https://img/1"),
        fetch_image=lambda u: (b"png", "image/png"),
    )
    assert paths[0].endswith(".png")


def test_image_download_failure_falls_back_to_url_then_text(monkeypatch):
    import apprise

    calls = []

    def fake_notify(self, **kw):
        attach = kw.get("attach")
        calls.append(None if attach is None else attach[0].url(privacy=False))
        return attach is None

    monkeypatch.setattr(apprise.Apprise, "notify", fake_notify)

    def broken(url):
        raise ValueError("Bild: unerwarteter Inhalt image/avif")

    send("json://localhost:1/", Message("T", "B", "https://img.example/1.jpg"), fetch_image=broken)
    assert len(calls) == 2
    assert calls[0].startswith("https://img.example/1.jpg")
    assert calls[1] is None


def test_image_download_failure_url_attachment_succeeds(monkeypatch):
    import apprise

    calls = []
    monkeypatch.setattr(
        apprise.Apprise, "notify", lambda self, **kw: calls.append(kw.get("attach")) or True
    )

    def broken(url):
        raise OSError("timeout")

    send("json://localhost:1/", Message("T", "B", "https://img.example/1.jpg"), fetch_image=broken)
    assert len(calls) == 1 and calls[0] is not None


def test_download_image_uses_browser_session():
    from sniper.notify.sender import download_image
    from tests.fakes import FakeResponse, FakeSession

    session = FakeSession([FakeResponse(200, headers={"Content-Type": "image/jpeg"}, content=JPEG)])
    assert download_image("https://img/1", session=session) == (JPEG, "image/jpeg")
    method, url, kwargs = session.calls[0]
    assert (method, url) == ("GET", "https://img/1")
    accept = kwargs["headers"]["Accept"]
    assert accept.startswith("image/jpeg") and "avif" not in accept


@pytest.mark.parametrize(
    "response",
    [
        dict(status_code=404, headers={"Content-Type": "image/jpeg"}, content=JPEG),
        dict(status_code=200, headers={"Content-Type": "text/html"}, content=b"<html>"),
        dict(status_code=200, headers={"Content-Type": "image/avif"}, content=b"avif"),
        dict(status_code=200, headers={"Content-Type": "image/webp"}, content=b"webp"),
        dict(
            status_code=200,
            headers={"Content-Type": "image/jpeg"},
            content=b"0" * (10 * 1024 * 1024 + 1),
        ),
    ],
)
def test_download_image_rejects_bad_responses(response):
    from sniper.notify.sender import download_image
    from tests.fakes import FakeResponse, FakeSession

    with pytest.raises(ValueError):
        download_image("https://img/1", session=FakeSession([FakeResponse(**response)]))


LINKED = Message(
    "Nike <3 H&M Jacke",
    "45 € · Kleinanzeigen\n🔎 Jacken",
    link_url="https://www.kleinanzeigen.de/s-anzeige/x/1?a=1&b=2",
    link_label="Anzeige öffnen",
)


def capture(monkeypatch):
    import apprise

    seen = []
    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, **kw: seen.append(kw) or True)
    return seen


def test_telegram_gets_clickable_link_and_escaped_text(monkeypatch):
    import apprise

    seen = capture(monkeypatch)
    send("tgram://123456789:abcdefghijklmnop/12345", LINKED)
    (kw,) = seen
    assert kw["body_format"] == apprise.NotifyFormat.HTML
    assert kw["title"] == "Nike &lt;3 H&amp;M Jacke"
    assert kw["body"].splitlines() == [
        "45 € · Kleinanzeigen",
        "🔎 Jacken",
        '➜ <a href="https://www.kleinanzeigen.de/s-anzeige/x/1?a=1&amp;b=2">Anzeige öffnen</a>',
    ]


def test_text_services_get_the_plain_url(monkeypatch):
    import apprise

    seen = capture(monkeypatch)
    send("ntfy://thema", LINKED)
    (kw,) = seen
    assert kw["body_format"] == apprise.NotifyFormat.TEXT
    assert kw["title"] == "Nike <3 H&M Jacke"
    assert kw["body"].splitlines()[-1] == "➜ https://www.kleinanzeigen.de/s-anzeige/x/1?a=1&b=2"


def test_message_without_link_has_no_link_line(monkeypatch):
    seen = capture(monkeypatch)
    send("tgram://123456789:abcdefghijklmnop/12345", Message("Sniper: Test", "Hallo & so"))
    assert seen[0]["body"] == "Hallo &amp; so"


TG_URL = "tgram://123456789:AAbbCCdd_eeFF-gg/123"
BUTTONS = ((Button("Anzeige öffnen", "https://x/1", "primary"),),)


class TelegramRecorder:
    def __init__(self, response=(200, {"ok": True})):
        self.response = response
        self.calls = []

    def __call__(self, url, **kw):
        self.calls.append((url.rsplit("/", 1)[1], kw))
        return self.response


def no_apprise(monkeypatch):
    import apprise

    def fail(self, **kw):
        raise AssertionError("Apprise darf hier nicht senden")

    monkeypatch.setattr(apprise.Apprise, "notify", fail)


def test_telegram_message_with_buttons_goes_straight_to_telegram(monkeypatch):
    no_apprise(monkeypatch)
    tg = TelegramRecorder()
    msg = Message("T", "B", "https://img/1", link_url="https://x/1", buttons=BUTTONS)
    send(TG_URL, msg, fetch_image=jpeg, telegram_post=tg)
    ((method, kw),) = tg.calls
    assert method == "sendPhoto"
    assert kw["files"]["photo"][1] == JPEG


def test_telegram_image_download_failure_lets_telegram_fetch_the_url(monkeypatch):
    no_apprise(monkeypatch)
    tg = TelegramRecorder()

    def broken(url):
        raise ValueError("Bild: HTTP 403")

    msg = Message("T", "B", "https://img/1", link_url="https://x/1", buttons=BUTTONS)
    send(TG_URL, msg, fetch_image=broken, telegram_post=tg)
    ((method, kw),) = tg.calls
    assert method == "sendPhoto" and kw["json"]["photo"] == "https://img/1"


def test_telegram_failure_becomes_send_error(monkeypatch):
    no_apprise(monkeypatch)
    tg = TelegramRecorder((403, {"ok": False, "description": "Forbidden: bot was blocked"}))
    msg = Message("T", "B", link_url="https://x/1", buttons=BUTTONS)
    with pytest.raises(SendError, match="Telegram: Forbidden: bot was blocked"):
        send(TG_URL, msg, fetch_image=jpeg, telegram_post=tg)


def test_telegram_message_without_buttons_still_uses_apprise(monkeypatch):
    import apprise

    sent = []
    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, **kw: sent.append(kw) or True)
    tg = TelegramRecorder()
    send(TG_URL, Message("Sniper: Test", "Hallo"), telegram_post=tg)
    assert tg.calls == [] and len(sent) == 1


def test_other_services_ignore_buttons_and_keep_the_link_line(monkeypatch):
    import apprise

    sent = []
    monkeypatch.setattr(apprise.Apprise, "notify", lambda self, **kw: sent.append(kw) or True)
    tg = TelegramRecorder()
    send(
        "json://localhost:1/",
        Message("T", "B", link_url="https://x/1", buttons=BUTTONS),
        telegram_post=tg,
    )
    assert tg.calls == [] and sent[0]["body"].endswith("➜ https://x/1")
