"""Weboberfläche."""

from __future__ import annotations

from flask import Flask


def create_app(settings, session_factory, adapters, scheduler) -> Flask:
    app = Flask(__name__)

    @app.get("/healthz")
    def healthz():
        return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}

    return app
