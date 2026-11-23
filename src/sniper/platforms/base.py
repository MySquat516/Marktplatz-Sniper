"""Was jeder Plattform-Adapter kann, und wie er Fehler meldet.

Die Fehlerklassen sind getrennt, weil der Sniper sie unterschiedlich behandelt: Ein Block
macht ihn vorsichtiger, eine geänderte Seite ist ein Fall für das Probe-Kommando, ein
Netzwerkfehler ist meist nach dem nächsten Versuch vorbei.
"""

from __future__ import annotations

from typing import Protocol

from sniper.models import Listing, Platform, SearchSpec


class AdapterError(Exception):
    """Der Abruf hat nicht geklappt."""


class Blocked(AdapterError):
    """Die Seite verweigert die Abfrage (403/503 oder Cloudflare-Challenge)."""


class RateLimited(AdapterError):
    """Zu viele Abfragen (429)."""

    def __init__(self, message: str = "Zu viele Abfragen", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class LayoutChanged(AdapterError):
    """Die Seite kam an, aber der Sniper erkennt darin keine Anzeigenliste."""


class NetworkError(AdapterError):
    """Keine Antwort: DNS, TLS, Timeout, Verbindung abgebrochen."""


class MissingCredentials(AdapterError):
    """Für diese Plattform fehlen Zugangsdaten."""


class InvalidUrl(ValueError):
    """Die eingefügte URL passt nicht. Der Text wird so in der Oberfläche angezeigt."""


class Adapter(Protocol):
    platform: Platform

    def parse_url(self, url: str) -> SearchSpec: ...

    def fetch(self, spec: SearchSpec) -> list[Listing]: ...
