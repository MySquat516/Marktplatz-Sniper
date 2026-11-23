"""eBay-Tageskontingent: mitzählen und Einstellungen verhindern, die es sprengen würden."""

from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy.orm import Session

from sniper.db import get_setting, set_setting

EBAY_DAILY_LIMIT = 5000
EBAY_DAILY_BUDGET = 4500


def _key(now: datetime) -> str:
    return f"ebay_calls:{now.date().isoformat()}"


def record_call(session: Session, now: datetime) -> None:
    set_setting(session, _key(now), str(calls_today(session, now) + 1))


def calls_today(session: Session, now: datetime) -> int:
    return int(get_setting(session, _key(now), "0"))


def projected_daily_calls(intervals_s: Iterable[int]) -> int:
    return sum(math.ceil(86400 / i) for i in intervals_s)
