"""Erst speichern, dann senden: So geht nach einem Absturz keine Meldung verloren.
Zugestellt wird „mindestens einmal“: Nur ein Absturz genau zwischen Senden und
Speichern kann eine Meldung doppelt schicken.

Jede Meldung wird einzeln gesendet und sofort als gesendet festgehalten; ein Ziel, das
nicht erreichbar ist, hält die anderen nicht auf.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from sniper.db import OutboxEntry, Target
from sniper.notify import sender
from sniper.notify.message import Message

log = logging.getLogger(__name__)
BACKOFF = tuple(timedelta(minutes=m) for m in (1, 5, 15, 60))
GIVE_UP_AFTER = timedelta(hours=24)


def enqueue(
    session: Session,
    targets: Iterable[Target],
    message: Message,
    *,
    kind: Literal["listing", "status"],
    search_id: int | None,
    now: datetime,
) -> None:
    for target in targets:
        session.add(
            OutboxEntry(
                target_id=target.id,
                search_id=search_id,
                kind=kind,
                title=message.title,
                body=message.body,
                attach_url=message.attach_url,
                link_url=message.link_url,
                link_label=message.link_label,
                attempts=0,
                next_attempt_at=now,
                created_at=now,
            )
        )


def deliver_due(
    session: Session,
    now: datetime,
    send: Callable[[str, Message], None] = sender.send,
) -> int:
    due = session.scalars(
        select(OutboxEntry)
        .where(
            OutboxEntry.sent_at.is_(None),
            OutboxEntry.failed_at.is_(None),
            OutboxEntry.next_attempt_at <= now,
        )
        .order_by(OutboxEntry.created_at, OutboxEntry.id)
    ).all()
    delivered = 0
    for entry in due:
        target = session.get(Target, entry.target_id)
        # Erst beanspruchen, dann senden: Scheitert danach das Speichern von „gesendet“,
        # wird die Meldung erst nach dem Wartefenster wiederholt statt bei jedem Durchlauf.
        entry.attempts += 1
        entry.next_attempt_at = now + BACKOFF[min(entry.attempts - 1, len(BACKOFF) - 1)]
        session.commit()
        try:
            message = Message(
                entry.title,
                entry.body,
                entry.attach_url,
                link_url=entry.link_url,
                link_label=entry.link_label or "Anzeige öffnen",
            )
            send(target.apprise_url, message)
        except Exception as exc:
            entry.last_error = str(exc) or type(exc).__name__
            if now - entry.created_at >= GIVE_UP_AFTER:
                entry.failed_at = now
            log.warning("Meldung an %s nicht zugestellt: %s", target.name, entry.last_error)
        else:
            entry.sent_at = now
            delivered += 1
        session.commit()
    return delivered
