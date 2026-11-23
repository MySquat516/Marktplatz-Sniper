"""Der Planer: ein Hintergrund-Thread, der fällige Suchen prüft und die Outbox leert.

Jede fällige Suche wird pro Durchlauf genau einmal geprüft, auch nach einer langen Pause;
danach liegt ihr nächster Termin wieder in der Zukunft. Ein Fehler in einer Suche hält die
anderen nicht auf.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Mapping
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from sniper.db import Search
from sniper.engine.check import run_check
from sniper.models import Platform
from sniper.notify import sender
from sniper.notify.outbox import deliver_due
from sniper.platforms.base import Adapter

log = logging.getLogger(__name__)


class Scheduler:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        adapters: Mapping[Platform, Adapter],
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        tick_s: float = 5.0,
        send=sender.send,
    ) -> None:
        self.session_factory = session_factory
        self.adapters = adapters
        self.now = now
        self.tick_s = tick_s
        self._send = send
        self._stop = threading.Event()

    def tick(self) -> None:
        with self.session_factory() as session:
            due_ids = session.scalars(
                select(Search.id)
                .where(
                    Search.active.is_(True),
                    (Search.next_check_at.is_(None)) | (Search.next_check_at <= self.now()),
                )
                .order_by(Search.next_check_at.is_not(None), Search.next_check_at)
            ).all()
            for search_id in due_ids:
                try:
                    search = session.get(Search, search_id)
                    adapter = self.adapters[Platform(search.platform)]
                    run_check(session, search, adapter, self.now())
                except Exception:
                    log.exception("Suche %s konnte nicht geprüft werden", search_id)
                    session.rollback()
            deliver_due(session, self.now(), send=self._send)

    def check_now(self, search_id: int) -> None:
        with self.session_factory() as session:
            search = session.get(Search, search_id)
            if search is not None:
                search.next_check_at = self.now()
                session.commit()

    def start(self) -> threading.Thread:
        self._stop.clear()
        thread = threading.Thread(target=self._loop, name="sniper-planer", daemon=True)
        thread.start()
        return thread

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                log.exception("Planer-Durchlauf fehlgeschlagen")
            self._stop.wait(self.tick_s)
