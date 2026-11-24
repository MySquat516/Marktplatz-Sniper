"""Meldungen mit Link-Knöpfen direkt an die Telegram-API schicken.

Apprise kann keine Knöpfe. Für Telegram-Ziele liest der Sniper deshalb Token und Chat aus
der Apprise-Adresse und spricht die Bot-API selbst an. Alles andere bleibt bei Apprise.

Reihenfolge: Foto mit Knöpfen, sonst Text mit Knöpfen, sonst (falls Telegram die Knöpfe
ablehnt) Text mit Link. Fehlertexte enthalten nie den Token: Er steckt in der API-Adresse,
und die Fehler landen in der Datenbank und im Log.
"""

from __future__ import annotations

import html
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import apprise

from sniper.notify.message import Button, Message

log = logging.getLogger(__name__)
API_ROOT = "https://api.telegram.org"
TIMEOUT_S = 20
MAX_TITLE_CHARS = 200
_SUFFIXES = {"image/jpeg": ".jpg", "image/png": ".png"}

Post = Callable[..., tuple[int, dict]]


class TelegramError(Exception):
    pass


@dataclass(frozen=True)
class TelegramTarget:
    token: str
    chats: tuple[tuple[int | str, int | None], ...]
    silent: bool = False


def telegram_target(apprise_url: str) -> TelegramTarget | None:
    """Token und Chats aus einer tgram://-Adresse. None, wenn es kein Telegram-Ziel mit
    festem Chat ist; dann übernimmt Apprise wie bisher."""
    from apprise.plugins.telegram import NotifyTelegram

    ap = apprise.Apprise()
    if not ap.add(apprise_url):
        return None
    plugin = ap[0]
    if not isinstance(plugin, NotifyTelegram) or getattr(plugin, "template", None):
        return None
    chats = tuple(
        t if isinstance(t, tuple) else (t, getattr(plugin, "topic", None)) for t in plugin.targets
    )
    if not chats:
        return None
    return TelegramTarget(plugin.bot_token, chats, silent=bool(plugin.silent))


def post(url: str, *, json: Any = None, data: Any = None, files: Any = None) -> tuple[int, dict]:
    import requests

    resp = requests.post(url, json=json, data=data, files=files, timeout=TIMEOUT_S)
    try:
        body = resp.json()
    except ValueError:
        body = {}
    return resp.status_code, body if isinstance(body, dict) else {}


def render(message: Message, *, with_link: bool) -> str:
    # Titel und Ort kommen von Verkäufern: maskieren, damit „<“ und „&“ ankommen und
    # niemand eigene Formatierung einschleusen kann.
    title = message.title
    if len(title) > MAX_TITLE_CHARS:
        title = title[: MAX_TITLE_CHARS - 1] + "…"
    text = f"<b>{html.escape(title, quote=False)}</b>\n{html.escape(message.body, quote=False)}"
    if with_link and message.link_url:
        href = html.escape(message.link_url, quote=True)
        text += f'\n➜ <a href="{href}">{html.escape(message.link_label, quote=False)}</a>'
    return text


def keyboard(buttons: tuple[tuple[Button, ...], ...]) -> dict:
    return {
        "inline_keyboard": [
            [
                {"text": b.label, "url": b.url, **({"style": b.style} if b.style else {})}
                for b in row
            ]
            for row in buttons
        ]
    }


def _call(post: Post, url: str, **kwargs: Any) -> tuple[bool, int | None, str]:
    try:
        status, body = post(url, **kwargs)
    except Exception as exc:
        # Absichtlich ohne str(exc): Darin steht oft die Adresse samt Token.
        return False, None, f"Telegram nicht erreichbar ({type(exc).__name__})"
    if status == 200 and body.get("ok"):
        return True, status, ""
    return False, status, f"Telegram: {body.get('description') or f'HTTP {status}'}"


def _send_to_chat(
    target: TelegramTarget,
    chat: int | str,
    topic: int | None,
    message: Message,
    image: tuple[bytes, str] | None,
    post: Post,
) -> str | None:
    """Schickt die Meldung an einen Chat. Gibt den Fehler zurück oder None."""
    api = f"{API_ROOT}/bot{target.token}/"
    base: dict[str, Any] = {
        "chat_id": chat,
        "parse_mode": "HTML",
        "disable_notification": target.silent,
    }
    if topic:
        base["message_thread_id"] = topic
    text = render(message, with_link=not message.buttons)
    markup = {"reply_markup": keyboard(message.buttons)} if message.buttons else {}

    if image is not None:
        data, content_type = image
        fields = base | {"caption": text}
        if markup:
            fields["reply_markup"] = json.dumps(markup["reply_markup"], ensure_ascii=False)
        form = {k: str(v).lower() if isinstance(v, bool) else str(v) for k, v in fields.items()}
        photo = (f"bild{_SUFFIXES.get(content_type, '.jpg')}", data, content_type)
        ok, _, error = _call(post, api + "sendPhoto", data=form, files={"photo": photo})
        if ok:
            return None
        log.warning("Foto nicht angenommen (%s), sende ohne Bild", error)
    elif message.attach_url:
        payload = base | {"photo": message.attach_url, "caption": text} | markup
        ok, _, error = _call(post, api + "sendPhoto", json=payload)
        if ok:
            return None
        log.warning("Foto nicht angenommen (%s), sende ohne Bild", error)

    no_preview = {"link_preview_options": {"is_disabled": True}}
    ok, status, error = _call(
        post, api + "sendMessage", json=base | {"text": text} | markup | no_preview
    )
    if ok:
        return None
    if markup and status == 400:
        log.warning("Knöpfe nicht angenommen (%s), sende Link im Text", error)
        plain = render(message, with_link=True)
        ok, _, error = _call(post, api + "sendMessage", json=base | {"text": plain} | no_preview)
        if ok:
            return None
    return error


def send_telegram(
    target: TelegramTarget,
    message: Message,
    image: tuple[bytes, str] | None,
    *,
    post: Post = post,
) -> None:
    errors = [
        error
        for chat, topic in target.chats
        if (error := _send_to_chat(target, chat, topic, message, image, post))
    ]
    if errors:
        raise TelegramError("; ".join(dict.fromkeys(errors)))
