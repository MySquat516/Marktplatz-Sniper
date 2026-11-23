"""Kommandozeile: `sniper serve` startet alles, `sniper probe <url>` speichert eine Antwort."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from sniper.config import Settings
from sniper.db import get_setting, make_engine, make_session_factory, migrate
from sniper.engine.scheduler import Scheduler
from sniper.platforms import build_adapters, normalize_url, platform_for_url
from sniper.platforms.base import InvalidUrl
from sniper.platforms.http import HttpClient


def run_probe(url: str, out_dir: Path, *, http, now: datetime) -> tuple[Path, Path]:
    url = normalize_url(url)
    platform = platform_for_url(url)
    resp = http.get(url)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{platform.value}-{now.strftime('%Y%m%d-%H%M%S')}"
    body = out_dir / f"{stem}.html"
    meta = out_dir / f"{stem}.headers.json"
    body.write_text(resp.text, encoding="utf-8")
    meta.write_text(
        json.dumps({"url": url, "status": resp.status, "headers": resp.headers}, indent=2),
        encoding="utf-8",
    )
    return body, meta


def ebay_credentials(settings: Settings, session_factory) -> Callable[[], tuple[str, str]]:
    """Zugangsdaten aus Umgebungsvariablen haben Vorrang vor denen aus der Oberfläche."""

    def read() -> tuple[str, str]:
        if settings.ebay_client_id and settings.ebay_client_secret:
            return settings.ebay_client_id, settings.ebay_client_secret
        with session_factory() as session:
            return (
                get_setting(session, "ebay_client_id"),
                get_setting(session, "ebay_client_secret"),
            )

    return read


def create_runtime(settings: Settings):
    from sniper.web import create_app

    engine = make_engine(settings.data_dir)
    migrate(engine)
    session_factory = make_session_factory(engine)
    adapters = build_adapters(HttpClient(), ebay_credentials(settings, session_factory))
    scheduler = Scheduler(session_factory, adapters)
    app = create_app(settings, session_factory, adapters, scheduler)
    return app, scheduler


def serve(settings: Settings) -> None:
    import waitress

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    log = logging.getLogger("sniper")
    if settings.app_password:
        log.info("Passwortschutz aktiv (Benutzer: %s).", settings.app_user)
    else:
        log.info(
            "Kein APP_PASSWORD gesetzt: Die Oberfläche ist ohne Anmeldung erreichbar "
            "(nur im Heimnetz/VPN betreiben)."
        )
    app, scheduler = create_runtime(settings)
    scheduler.start()
    log.info("Sniper läuft auf Port %s.", settings.port)
    waitress.serve(app, host="0.0.0.0", port=settings.port, threads=4)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sniper", description="Marktplatz-Sniper")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="Weboberfläche und Planer starten")
    probe = sub.add_parser("probe", help="eine Such-URL einmal abrufen und die Antwort speichern")
    probe.add_argument("url")
    probe.add_argument("--out", type=Path, help="Zielordner (Standard: DATA_DIR/probes)")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    if args.command == "serve":
        serve(settings)
        return 0
    if args.command == "probe":
        out = args.out or settings.data_dir / "probes"
        try:
            body, meta = run_probe(args.url, out, http=HttpClient(), now=datetime.now(UTC))
        except InvalidUrl as exc:
            print(exc, file=sys.stderr)
            return 2
        print(f"Gespeichert: {body}\n             {meta}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
