import json
from types import SimpleNamespace

import pytest

from sniper.notify.message import Button, Message
from sniper.notify.telegram import TelegramError, TelegramTarget, send_telegram, telegram_target

TOKEN = "123456789:AAbbCCdd_eeFF-gg"
JPEG = b"\xff\xd8\xff\xe0" + b"0" * 50
OK = (200, {"ok": True, "result": {}})


def bad(description, status=400):
    return status, {"ok": False, "description": description}


class FakeTelegram:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, url, *, json=None, data=None, files=None):
        self.calls.append(
            SimpleNamespace(
                url=url, method=url.rsplit("/", 1)[1], json=json, data=data, files=files
            )
        )
        response = self.responses.pop(0) if self.responses else OK
        if isinstance(response, Exception):
            raise response
        return response


def message(**kw):
    base = dict(
        title="Jacke & Co <neu>",
        body="45 € · Kleinanzeigen\n🔎 Jacken",
        attach_url="https://img.example/1.JPG",
        link_url="https://www.kleinanzeigen.de/s-anzeige/1",
        buttons=(
            (
                Button("Anzeige öffnen", "https://www.kleinanzeigen.de/s-anzeige/1", "primary"),
                Button("eBay verkauft", "https://www.ebay.de/sch/i.html?_nkw=Jacke"),
            ),
            (Button("Bildersuche", "https://lens.google.com/uploadbyurl?url=x"),),
        ),
    )
    return Message(**{**base, **kw})


TARGET = TelegramTarget(TOKEN, ((123, None),))
KEYBOARD = {
    "inline_keyboard": [
        [
            {
                "text": "Anzeige öffnen",
                "url": "https://www.kleinanzeigen.de/s-anzeige/1",
                "style": "primary",
            },
            {"text": "eBay verkauft", "url": "https://www.ebay.de/sch/i.html?_nkw=Jacke"},
        ],
        [{"text": "Bildersuche", "url": "https://lens.google.com/uploadbyurl?url=x"}],
    ]
}
CAPTION = "<b>Jacke &amp; Co &lt;neu&gt;</b>\n45 € · Kleinanzeigen\n🔎 Jacken"


def test_telegram_target_reads_token_chats_topic_and_silent():
    target = telegram_target(f"tgram://{TOKEN}/-100123:7/@kanal?silent=yes")
    assert target == TelegramTarget(TOKEN, ((-100123, 7), ("@kanal", None)), silent=True)


@pytest.mark.parametrize("url", ["ntfy://thema", f"tgram://{TOKEN}/", "kaputt://"])
def test_telegram_target_is_none_for_other_services_and_missing_chat(url):
    assert telegram_target(url) is None


def test_photo_is_uploaded_with_caption_and_buttons():
    tg = FakeTelegram()
    send_telegram(TARGET, message(), (JPEG, "image/jpeg"), post=tg)
    (call,) = tg.calls
    assert call.url == f"https://api.telegram.org/bot{TOKEN}/sendPhoto"
    assert call.data["chat_id"] == "123"
    assert call.data["parse_mode"] == "HTML"
    assert call.data["caption"] == CAPTION
    assert json.loads(call.data["reply_markup"]) == KEYBOARD
    assert call.files == {"photo": ("bild.jpg", JPEG, "image/jpeg")}


def test_without_downloaded_image_telegram_fetches_the_photo_url():
    tg = FakeTelegram()
    send_telegram(TARGET, message(), None, post=tg)
    (call,) = tg.calls
    assert call.method == "sendPhoto"
    assert call.json["photo"] == "https://img.example/1.JPG"
    assert call.json["caption"] == CAPTION
    assert call.json["reply_markup"] == KEYBOARD


def test_rejected_photo_falls_back_to_text_with_buttons():
    tg = FakeTelegram(bad("Bad Request: wrong file identifier/HTTP URL specified"))
    send_telegram(TARGET, message(), None, post=tg)
    assert [c.method for c in tg.calls] == ["sendPhoto", "sendMessage"]
    text = tg.calls[1].json
    assert text["text"] == CAPTION
    assert text["reply_markup"] == KEYBOARD
    assert text["link_preview_options"] == {"is_disabled": True}


def test_message_without_photo_is_sent_as_text():
    tg = FakeTelegram()
    send_telegram(TARGET, message(attach_url=None), None, post=tg)
    assert [c.method for c in tg.calls] == ["sendMessage"]


def test_rejected_buttons_fall_back_to_plain_text_with_link():
    tg = FakeTelegram(bad("photo"), bad("Bad Request: BUTTON_URL_INVALID"))
    send_telegram(TARGET, message(), None, post=tg)
    last = tg.calls[-1].json
    assert [c.method for c in tg.calls] == ["sendPhoto", "sendMessage", "sendMessage"]
    assert "reply_markup" not in last
    assert last["text"] == (
        CAPTION + '\n➜ <a href="https://www.kleinanzeigen.de/s-anzeige/1">Anzeige öffnen</a>'
    )


def test_total_failure_raises_telegrams_reason_without_the_token():
    tg = FakeTelegram(bad("x"), bad("x"), bad("Bad Request: chat not found"))
    with pytest.raises(TelegramError) as err:
        send_telegram(TARGET, message(), None, post=tg)
    assert str(err.value) == "Telegram: Bad Request: chat not found"


def test_network_error_never_leaks_the_token():
    boom = ConnectionError(f"HTTPSConnectionPool: https://api.telegram.org/bot{TOKEN}/sendPhoto")
    tg = FakeTelegram(boom, boom, boom)
    with pytest.raises(TelegramError) as err:
        send_telegram(TARGET, message(), None, post=tg)
    assert TOKEN not in str(err.value)
    assert str(err.value) == "Telegram nicht erreichbar (ConnectionError)"


def test_topic_and_silent_are_passed_on():
    tg = FakeTelegram()
    target = TelegramTarget(TOKEN, (("-100123", 7),), silent=True)
    send_telegram(target, message(attach_url=None), None, post=tg)
    sent = tg.calls[0].json
    assert (sent["chat_id"], sent["message_thread_id"], sent["disable_notification"]) == (
        "-100123",
        7,
        True,
    )


def test_every_chat_is_tried_and_a_failure_is_reported():
    tg = FakeTelegram(bad("Forbidden: bot was blocked by the user", 403), OK)
    target = TelegramTarget(TOKEN, ((1, None), (2, None)))
    with pytest.raises(TelegramError, match="bot was blocked"):
        send_telegram(target, message(attach_url=None, buttons=()), None, post=tg)
    assert [c.json["chat_id"] for c in tg.calls] == [1, 2]


def test_long_title_keeps_the_caption_within_telegrams_limit():
    tg = FakeTelegram()
    send_telegram(TARGET, message(title="a" * 3000), (JPEG, "image/jpeg"), post=tg)
    assert len(tg.calls[0].data["caption"]) <= 1024


def test_post_returns_status_and_json(monkeypatch):
    import requests

    from sniper.notify import telegram

    seen = {}

    def fake_post(url, **kw):
        seen.update(kw, url=url)
        return SimpleNamespace(status_code=200, json=lambda: {"ok": True})

    monkeypatch.setattr(requests, "post", fake_post)
    assert telegram.post("https://api/x", json={"a": 1}) == (200, {"ok": True})
    assert seen["timeout"] == telegram.TIMEOUT_S


def test_post_survives_a_non_json_answer(monkeypatch):
    import requests

    from sniper.notify import telegram

    def not_json():
        raise ValueError("kein JSON")

    monkeypatch.setattr(
        requests, "post", lambda url, **kw: SimpleNamespace(status_code=502, json=not_json)
    )
    assert telegram.post("https://api/x") == (502, {})
