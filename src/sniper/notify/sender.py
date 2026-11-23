"""Eine Meldung über Apprise an genau ein Ziel schicken."""

from __future__ import annotations

import apprise

from sniper.notify.message import Message


class SendError(Exception):
    pass


def _text(message: Message) -> dict:
    # Titel kommen von Verkäufern. Als Klartext markiert, damit Apprise „<“ und „&“ für
    # Dienste mit HTML-Modus (z. B. Telegram) maskiert, statt sie roh durchzureichen.
    return {
        "title": message.title,
        "body": message.body,
        "body_format": apprise.NotifyFormat.TEXT,
    }


def send(apprise_url: str, message: Message) -> None:
    ap = apprise.Apprise()
    if not ap.add(apprise_url):
        raise SendError("Ungültige Apprise-Adresse")
    if message.attach_url:
        attach = apprise.AppriseAttachment()
        attach.add(message.attach_url)
        if ap.notify(**_text(message), attach=attach):
            return
    # Ohne Anhang (nochmal) versuchen: Manche Dienste können keine Bilder,
    # die Meldung soll trotzdem ankommen.
    if not ap.notify(**_text(message), attach=None):
        raise SendError("Zustellung fehlgeschlagen")
