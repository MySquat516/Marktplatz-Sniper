"""Eine Meldung über Apprise an genau ein Ziel schicken."""

from __future__ import annotations

import apprise

from sniper.notify.message import Message


class SendError(Exception):
    pass


def send(apprise_url: str, message: Message) -> None:
    ap = apprise.Apprise()
    if not ap.add(apprise_url):
        raise SendError("Ungültige Apprise-Adresse")
    if message.attach_url:
        attach = apprise.AppriseAttachment()
        attach.add(message.attach_url)
        if ap.notify(title=message.title, body=message.body, attach=attach):
            return
    # Ohne Anhang (nochmal) versuchen: Manche Dienste können keine Bilder,
    # die Meldung soll trotzdem ankommen.
    if not ap.notify(title=message.title, body=message.body, attach=None):
        raise SendError("Zustellung fehlgeschlagen")
