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
