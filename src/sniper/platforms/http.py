"""Wie Anfragen rausgehen: mit Browser-Fingerabdruck, Abstand pro Host und klaren Fehlern."""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from sniper.platforms.base import Blocked, NetworkError, RateLimited

TIMEOUT_S = 20
_CHALLENGE_MARKERS = ("Just a moment", "cf-chl", "cf_chl", "challenge-platform")


@dataclass
class HttpResponse:
    status: int
    text: str
    headers: dict[str, str]


def _default_session() -> Any:
    from curl_cffi import requests

    return requests.Session(impersonate="chrome")


class HttpClient:
    def __init__(
        self,
        min_spacing_s: float = 10.0,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        session: Any = None,
    ) -> None:
        self.min_spacing_s = min_spacing_s
        self._clock = clock
        self._sleep = sleep
        self._session = session if session is not None else _default_session()
        self._last: dict[str, float] = {}

    def get(self, url: str, *, params=None, headers=None) -> HttpResponse:
        return self._request("GET", url, params=params, headers=headers)

    def post(self, url: str, *, data=None, headers=None, auth=None) -> HttpResponse:
        return self._request("POST", url, data=data, headers=headers, auth=auth)

    def _request(self, method: str, url: str, **kwargs: Any) -> HttpResponse:
        host = urlsplit(url).hostname or ""
        last = self._last.get(host)
        if last is not None:
            wait = last + self.min_spacing_s - self._clock()
            if wait > 0:
                self._sleep(wait)
        try:
            r = self._session.request(method, url, timeout=TIMEOUT_S, **kwargs)
        except Exception as exc:
            raise NetworkError(str(exc) or type(exc).__name__) from exc
        finally:
            self._last[host] = self._clock()
        headers = {str(k).lower(): str(v) for k, v in dict(r.headers).items()}
        return HttpResponse(status=r.status_code, text=r.text, headers=headers)


def check_blocked(resp: HttpResponse) -> None:
    if resp.status == 429:
        retry = resp.headers.get("retry-after", "")
        raise RateLimited(retry_after=float(retry) if retry.isdigit() else None)
    if resp.status in (403, 503):
        raise Blocked(f"HTTP {resp.status}")
    if resp.status == 200 and any(m in resp.text for m in _CHALLENGE_MARKERS):
        raise Blocked("Cloudflare-Challenge")
