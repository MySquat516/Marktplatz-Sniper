"""Eine Meldung über Apprise an genau ein Ziel schicken.

Das Bild lädt der Sniper selbst (mit Browser-Kennung) und hängt es als Datei an. Lädt Apprise
es selbst, lehnen manche Bildserver die Anfrage ab, und die Meldung käme ohne Bild an.
"""

from __future__ import annotations

import logging
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

import apprise

from sniper.notify.message import Message

log = logging.getLogger(__name__)
MAX_IMAGE_BYTES = 10 * 1024 * 1024
IMAGE_TIMEOUT_S = 15
# Nur Formate, die alle Dienste als Foto anzeigen. AVIF/WebP lehnt z. B. Telegram ab.
_SUFFIXES = {"image/jpeg": ".jpg", "image/png": ".png"}
# Ausdrücklich JPEG anfragen: Mit der normalen Browser-Kennung liefern Bildserver sonst AVIF.
_ACCEPT = "image/jpeg,image/png;q=0.9,*/*;q=0.5"


class SendError(Exception):
    pass


def download_image(url: str, session: Any = None) -> tuple[bytes, str]:
    """Lädt ein Bild und gibt (Bytes, Content-Type) zurück. Wirft ValueError bei allem anderen."""
    if session is None:
        from curl_cffi import requests

        session = requests.Session(impersonate="chrome")
    resp = session.request("GET", url, headers={"Accept": _ACCEPT}, timeout=IMAGE_TIMEOUT_S)
    headers = {str(k).lower(): str(v) for k, v in dict(resp.headers).items()}
    content_type = headers.get("content-type", "").split(";")[0].strip().lower()
    if resp.status_code != 200:
        raise ValueError(f"Bild: HTTP {resp.status_code}")
    if content_type not in _SUFFIXES:
        raise ValueError(f"Bild: unerwartetes Format {content_type or '?'}")
    if len(resp.content) > MAX_IMAGE_BYTES:
        raise ValueError("Bild: zu groß")
    return resp.content, content_type


def _text(message: Message) -> dict:
    # Titel kommen von Verkäufern. Als Klartext markiert, damit Apprise „<“ und „&“ für
    # Dienste mit HTML-Modus (z. B. Telegram) maskiert, statt sie roh durchzureichen.
    return {
        "title": message.title,
        "body": message.body,
        "body_format": apprise.NotifyFormat.TEXT,
    }


def send(
    apprise_url: str,
    message: Message,
    *,
    fetch_image: Callable[[str], tuple[bytes, str]] = download_image,
) -> None:
    ap = apprise.Apprise()
    if not ap.add(apprise_url):
        raise SendError("Ungültige Apprise-Adresse")
    if message.attach_url:
        try:
            data, content_type = fetch_image(message.attach_url)
        except Exception as exc:
            # Notlösung wie früher: Apprise lädt das Bild selbst.
            log.warning("Bild nicht geladen (%s), Apprise versucht es selbst", exc)
            attach = apprise.AppriseAttachment()
            attach.add(message.attach_url)
            if ap.notify(**_text(message), attach=attach):
                return
        else:
            with tempfile.TemporaryDirectory(prefix="sniper-") as tmp:
                path = Path(tmp) / f"bild{_SUFFIXES[content_type]}"
                path.write_bytes(data)
                attach = apprise.AppriseAttachment()
                attach.add(str(path))
                if ap.notify(**_text(message), attach=attach):
                    return
        log.warning("Senden mit Bild fehlgeschlagen, versuche es ohne Bild")
    if not ap.notify(**_text(message), attach=None):
        raise SendError("Zustellung fehlgeschlagen")
