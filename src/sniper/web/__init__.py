"""Weboberfläche: Suchen einrichten, Treffer ansehen, Benachrichtigungen und Einstellungen."""

from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from flask import Flask

from sniper.notify import sender
from sniper.web import auth, views

BERLIN = ZoneInfo("Europe/Berlin")


@dataclass
class Runtime:
    settings: Any
    session_factory: Any
    adapters: Any
    scheduler: Any
    send: Any
    now: Any


def load_secret(data_dir: Path) -> str:
    """Bleibt über Neustarts gleich, damit man angemeldet bleibt."""
    path = data_dir / "session-secret"
    if path.exists():
        value = path.read_text().strip()
        if len(value) >= 32:
            return value
    data_dir.mkdir(parents=True, exist_ok=True)
    value = secrets.token_hex(32)
    path.write_text(value)
    path.chmod(0o600)
    return value


def local_time(value: datetime | None) -> str:
    return value.astimezone(BERLIN).strftime("%d.%m. %H:%M") if value else "–"


def create_app(
    settings,
    session_factory,
    adapters,
    scheduler,
    *,
    send=sender.send,
    now=lambda: datetime.now(UTC),
) -> Flask:
    app = Flask(__name__)
    app.config.update(
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
    )
    # Der Schlüssel hängt am Passwort: Ein neues Passwort meldet überall ab.
    secret = load_secret(settings.data_dir)
    key = f"{secret}\0{settings.app_user}\0{settings.app_password}"
    app.secret_key = hashlib.sha256(key.encode()).hexdigest()
    app.extensions["sniper"] = Runtime(settings, session_factory, adapters, scheduler, send, now)
    app.add_template_filter(local_time, "local")
    auth.init(app, settings)
    app.register_blueprint(views.bp)

    @app.get("/healthz")
    def healthz():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    return app
