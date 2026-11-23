"""Ein Check einer Suche: abrufen, entscheiden, merken, melden – in einer Transaktion.

Zustände: OK, Fehler, Geblockt, Seite unbekannt. Statusmeldungen gehen an alle Ziele mit
„bekommt Statusmeldungen“: bei Block und geänderter Seite sofort, bei Fehlern ab dem dritten
in Folge, jeweils einmal, und einmal „läuft wieder“, sobald es wieder klappt.
"""

from __future__ import annotations

import json
import logging
import random
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from sniper.db import Search, Seen, Target
from sniper.engine import quota
from sniper.engine.detect import Filters, detect
from sniper.models import Platform, SearchSpec, SearchState
from sniper.notify.message import (
    listing_message,
    overflow_message,
    recovery_message,
    silence_message,
    status_message,
)
from sniper.notify.outbox import enqueue
from sniper.platforms.base import Adapter, Blocked, LayoutChanged, RateLimited

log = logging.getLogger(__name__)
MAX_INTERVAL_S = 3600
ERROR_NOTICE_AFTER = 3


def next_interval(
    search: Search, state: SearchState, rng: Callable[[], float] = random.random
) -> timedelta:
    base = float(search.interval_s)
    if state is SearchState.BLOCKED:
        base = search.interval_s * 2**search.consecutive_failures
    seconds = base * (0.8 + 0.4 * rng())
    if state is SearchState.BLOCKED:
        seconds = min(seconds, MAX_INTERVAL_S)
    return timedelta(seconds=seconds)


def _status_targets(session: Session) -> list[Target]:
    return list(session.scalars(select(Target).where(Target.status_notices.is_(True))))


def run_check(
    session: Session,
    search: Search,
    adapter: Adapter,
    now: datetime,
    rng: Callable[[], float] = random.random,
) -> SearchState:
    platform = Platform(search.platform)
    spec = SearchSpec.from_dict(json.loads(search.spec_json))
    try:
        listings = adapter.fetch(spec)
    except (Blocked, RateLimited) as exc:
        state = _failed(session, search, SearchState.BLOCKED, exc, now)
    except LayoutChanged as exc:
        state = _failed(session, search, SearchState.LAYOUT_CHANGED, exc, now)
    except Exception as exc:
        log.warning("Check von %r fehlgeschlagen", search.name, exc_info=True)
        state = _failed(session, search, SearchState.ERROR, exc, now)
    else:
        state = _succeeded(session, search, platform, listings, now)

    search.last_check_at = now
    search.next_check_at = now + next_interval(search, state, rng)
    if platform is Platform.EBAY:
        quota.record_call(session, now)
    session.commit()
    return state


def _succeeded(session, search: Search, platform: Platform, listings, now) -> SearchState:
    seen_ids = set(session.scalars(select(Seen.external_id).where(Seen.search_id == search.id)))
    detection = detect(
        listings,
        seen_ids,
        Filters.from_text(search.max_price, search.exclude_words),
        first_check=search.last_ok_at is None,
        now=now,
    )
    for verdict in detection.verdicts:
        session.add(
            Seen(
                search_id=search.id,
                platform=platform.value,
                external_id=verdict.listing.external_id,
                status=verdict.status,
                reason=verdict.reason,
                listing_json=json.dumps(verdict.listing.to_dict()),
                first_seen_at=now,
            )
        )
        if verdict.notify:
            msg = listing_message(verdict.listing, search.name, now)
            enqueue(session, search.targets, msg, kind="listing", search_id=search.id, now=now)
    if detection.overflow:
        msg = overflow_message(search.name, platform, detection.overflow, search.url)
        enqueue(session, search.targets, msg, kind="listing", search_id=search.id, now=now)
    if any(v.notify for v in detection.verdicts):
        search.last_match_at = now
        search.silence_notified = False

    if search.notified_state is not None:
        _notify_status(session, search, recovery_message(search.name), now)
        search.notified_state = None
    reference = search.last_match_at or search.created_at
    if (
        search.silence_days > 0
        and not search.silence_notified
        and now - reference >= timedelta(days=search.silence_days)
    ):
        _notify_status(
            session, search, silence_message(search.name, platform, search.silence_days), now
        )
        search.silence_notified = True

    search.state = SearchState.OK.value
    search.consecutive_failures = 0
    search.last_ok_at = now
    search.last_error = None
    return SearchState.OK


def _failed(session, search: Search, state: SearchState, exc: Exception, now) -> SearchState:
    search.state = state.value
    search.consecutive_failures += 1
    search.last_error = str(exc) or type(exc).__name__
    loud = state is not SearchState.ERROR or search.consecutive_failures >= ERROR_NOTICE_AFTER
    if loud and search.notified_state != state.value:
        msg = status_message(search.name, Platform(search.platform), state, search.last_error)
        _notify_status(session, search, msg, now)
        search.notified_state = state.value
    return state


def _notify_status(session: Session, search: Search, message, now: datetime) -> None:
    enqueue(session, _status_targets(session), message, kind="status", search_id=search.id, now=now)
