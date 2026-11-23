"""Optionaler Login (nur mit APP_PASSWORD) und CSRF-Schutz für alle Formulare.

Wie im Reseller-Dashboard: Ohne APP_PASSWORD ist die Oberfläche offen (Heimnetz/VPN).
Nach 5 Fehlversuchen je IP in 5 Minuten wird gesperrt, bis das Fenster abgelaufen ist.
"""

from __future__ import annotations

import hmac
import secrets
from collections import defaultdict
from datetime import timedelta

from flask import (
    Flask,
    abort,
    current_app,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

MAX_FAILS = 5
FAIL_WINDOW = timedelta(minutes=5)
OPEN_ENDPOINTS = {"healthz", "static", "login"}


def csrf_token() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(16)
    return session["csrf"]


def init(app: Flask, settings) -> None:
    failures: dict[str, list] = defaultdict(list)
    app.jinja_env.globals["csrf_token"] = csrf_token
    app.jinja_env.globals["auth_enabled"] = bool(settings.app_password)

    @app.before_request
    def check_csrf():
        if request.method == "POST":
            expected = session.get("csrf", "")
            if not expected or not hmac.compare_digest(expected, request.form.get("csrf", "")):
                abort(400, "Formular abgelaufen, bitte Seite neu laden.")

    @app.before_request
    def require_login():
        if not settings.app_password or request.endpoint in OPEN_ENDPOINTS:
            return None
        if session.get("user") != settings.app_user:
            return redirect(url_for("login", next=request.path))
        return None

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if not settings.app_password:
            return redirect(url_for("views.searches"))
        if request.method == "GET":
            return render_template("login.html")
        now = current_app.extensions["sniper"].now()
        ip = request.remote_addr or "?"
        failures[ip] = [t for t in failures[ip] if now - t < FAIL_WINDOW]
        if len(failures[ip]) >= MAX_FAILS:
            return render_template("login.html", error="Zu viele Fehlversuche. Bitte warten."), 429
        user_ok = hmac.compare_digest(request.form.get("username", ""), settings.app_user)
        pass_ok = hmac.compare_digest(request.form.get("password", ""), settings.app_password)
        if not (user_ok and pass_ok):
            failures[ip].append(now)
            return render_template("login.html", error="Benutzer oder Passwort falsch.")
        failures.pop(ip, None)
        csrf = session.get("csrf")
        session.clear()
        session["csrf"] = csrf or secrets.token_urlsafe(16)
        session["user"] = settings.app_user
        session.permanent = True
        target = request.args.get("next", "")
        safe = target.startswith("/") and not target.startswith("//")
        return redirect(target if safe else url_for("views.searches"))

    @app.post("/logout")
    def logout():
        session.pop("user", None)
        return redirect(url_for("login"))
