"""Kommandozeile: `sniper serve` startet alles, `sniper probe <url>` speichert eine Antwort."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sniper.config import Settings
from sniper.platforms import normalize_url, platform_for_url
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sniper", description="Marktplatz-Sniper")
    sub = parser.add_subparsers(dest="command", required=True)
    probe = sub.add_parser("probe", help="eine Such-URL einmal abrufen und die Antwort speichern")
    probe.add_argument("url")
    probe.add_argument("--out", type=Path, help="Zielordner (Standard: DATA_DIR/probes)")
    args = parser.parse_args(argv)

    settings = Settings.from_env()
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
