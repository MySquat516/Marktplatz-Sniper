import json
from datetime import UTC, datetime

from sniper.cli import run_probe
from sniper.platforms.http import HttpResponse


class FakeHttp:
    def __init__(self, response):
        self.response = response
        self.urls = []

    def get(self, url, **kwargs):
        self.urls.append(url)
        return self.response


def test_probe_writes_body_and_headers(tmp_path):
    http = FakeHttp(HttpResponse(200, "<html>x</html>", {"content-type": "text/html"}))
    now = datetime(2026, 11, 23, 7, 5, 9, tzinfo=UTC)
    body, headers = run_probe(
        "kleinanzeigen.de/s-jacke/k0", tmp_path / "probes", http=http, now=now
    )
    assert body.name == "kleinanzeigen-20261123-070509.html"
    assert body.read_text() == "<html>x</html>"
    meta = json.loads(headers.read_text())
    assert meta["status"] == 200
    assert meta["url"] == "https://kleinanzeigen.de/s-jacke/k0"
    assert meta["headers"]["content-type"] == "text/html"
    assert http.urls == ["https://kleinanzeigen.de/s-jacke/k0"]


def test_probe_keeps_challenge_pages(tmp_path):
    http = FakeHttp(HttpResponse(403, "<title>Just a moment...</title>", {}))
    body, _ = run_probe(
        "https://www.willhaben.at/iad/x", tmp_path, http=http, now=datetime.now(UTC)
    )
    assert "Just a moment" in body.read_text()
