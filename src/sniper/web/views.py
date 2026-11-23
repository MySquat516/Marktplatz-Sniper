"""Alle Seiten der Oberfläche."""

from __future__ import annotations

import json
import re
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import parse_qsl, urlsplit

import apprise
from flask import Blueprint, current_app, flash, redirect, render_template, request, url_for
from sqlalchemy import Float, cast, delete, func, select

from sniper.db import OutboxEntry, Search, Seen, Target, get_setting, set_setting
from sniper.engine import quota
from sniper.models import Listing, Platform, SearchSpec, SearchState
from sniper.notify.message import Message, format_price
from sniper.platforms import adapter_for_url
from sniper.platforms.base import InvalidUrl

bp = Blueprint("views", __name__)
MIN_INTERVAL_MIN = 2
MAX_INTERVAL_MIN = 1440
MAX_SILENCE_DAYS = 365
MAX_PRICE = Decimal("99999999")


def rt():
    return current_app.extensions["sniper"]


def ebay_from_env() -> bool:
    s = rt().settings
    return bool(s.ebay_client_id and s.ebay_client_secret)


def ebay_configured(db) -> bool:
    return ebay_from_env() or bool(
        get_setting(db, "ebay_client_id") and get_setting(db, "ebay_client_secret")
    )


def suggest_name(spec: SearchSpec) -> str:
    if spec.params.get("q"):
        return spec.params["q"]
    query = dict(parse_qsl(urlsplit(spec.url).query))
    if query.get("keyword"):
        return query["keyword"]
    segments = urlsplit(spec.url).path.removeprefix("/s-").split("/")
    words = [s for s in segments if s and ":" not in s and not re.match(r"^[kc]\d", s)]
    return words[-1] if words else "Suche"


def mask(url: str) -> str:
    scheme = url.split("://", 1)[0] if "://" in url else "?"
    return f"{scheme}://…{url[-4:]}"


# --- Suchen -------------------------------------------------------------------------------


@bp.get("/")
def index():
    return redirect(url_for("views.searches"))


@bp.get("/suchen")
def searches(url_error: str | None = None, url_value: str = ""):
    with rt().session_factory() as db:
        rows = db.scalars(select(Search).order_by(Search.platform, Search.name)).all()
        return render_template(
            "searches.html",
            searches=rows,
            Platform=Platform,
            SearchState=SearchState,
            url_error=url_error,
            url_value=url_value,
        )


def _targets(db) -> list[Target]:
    return list(db.scalars(select(Target).order_by(Target.name)))


def _render_form(
    db,
    *,
    values: dict[str, Any],
    spec: SearchSpec | None,
    errors=(),
    search=None,
    preview=None,
    preview_error=None,
):
    return render_template(
        "search_form.html",
        values=values,
        spec=spec,
        errors=list(errors),
        search=search,
        targets=_targets(db),
        preview=preview,
        preview_error=preview_error,
        Platform=Platform,
        format_price=format_price,
    )


def _defaults(spec: SearchSpec) -> dict[str, Any]:
    return {
        "url": spec.url,
        "name": suggest_name(spec),
        "interval_min": "5",
        "max_price": "",
        "exclude_words": "",
        "silence_days": "7",
        "target_ids": [],
    }


@bp.post("/suchen/neu")
def new_search():
    url = request.form.get("url", "")
    try:
        adapter = adapter_for_url(url, rt().adapters)
        spec = adapter.parse_url(url)
    except InvalidUrl as exc:
        return searches(url_error=str(exc), url_value=url)
    preview, preview_error = None, None
    try:
        preview = adapter.fetch(spec)[:10]
    except Exception as exc:
        preview_error = f"Vorschau nicht möglich: {exc}"
    with rt().session_factory() as db:
        values = _defaults(spec)
        values["target_ids"] = [t.id for t in _targets(db)]
        return _render_form(
            db, values=values, spec=spec, preview=preview, preview_error=preview_error
        )


def _read_form() -> tuple[dict[str, Any], list[str], dict[str, Any]]:
    """Gibt (Rohwerte fürs Formular, Fehler, geprüfte Werte) zurück."""
    f = request.form
    values = {
        "url": f.get("url", ""),
        "name": f.get("name", "").strip(),
        "interval_min": f.get("interval_min", "5").strip(),
        "max_price": f.get("max_price", "").strip(),
        "exclude_words": f.get("exclude_words", ""),
        "silence_days": f.get("silence_days", "7").strip(),
        "target_ids": [int(t) for t in f.getlist("target_ids") if t.isdigit()],
    }
    errors: list[str] = []
    clean: dict[str, Any] = {}
    try:
        interval = int(values["interval_min"])
        if interval < MIN_INTERVAL_MIN:
            errors.append(f"Der Takt muss mindestens {MIN_INTERVAL_MIN} Minuten sein.")
        if interval > MAX_INTERVAL_MIN:
            errors.append(f"Der Takt darf höchstens {MAX_INTERVAL_MIN} Minuten (1 Tag) sein.")
            interval = MAX_INTERVAL_MIN
        clean["interval_s"] = interval * 60
    except ValueError:
        errors.append("Der Takt muss eine ganze Zahl (Minuten) sein.")
    try:
        price = values["max_price"].replace(",", ".")
        clean["max_price"] = Decimal(price) if price else None
        if clean["max_price"] is not None and clean["max_price"] < 0:
            errors.append("Der Höchstpreis darf nicht negativ sein.")
        if clean["max_price"] is not None and clean["max_price"] > MAX_PRICE:
            errors.append("Der Höchstpreis ist zu groß.")
    except InvalidOperation:
        errors.append("Der Höchstpreis ist keine Zahl.")
    try:
        clean["silence_days"] = int(values["silence_days"] or 0)
        if clean["silence_days"] < 0:
            errors.append("Die Stille-Frist darf nicht negativ sein.")
        if clean["silence_days"] > MAX_SILENCE_DAYS:
            errors.append(f"Die Stille-Frist darf höchstens {MAX_SILENCE_DAYS} Tage sein.")
    except ValueError:
        errors.append("Die Stille-Frist muss eine ganze Zahl (Tage) sein.")
    clean["exclude_words"] = "\n".join(
        w.strip() for w in values["exclude_words"].splitlines() if w.strip()
    )
    return values, errors, clean


def _save(db, search: Search | None):
    values, errors, clean = _read_form()
    spec = None
    try:
        adapter = adapter_for_url(values["url"], rt().adapters)
        spec = adapter.parse_url(values["url"])
    except InvalidUrl as exc:
        errors.append(str(exc))
    if spec and spec.platform is Platform.EBAY and not errors:
        if not ebay_configured(db):
            errors.append("Erst eBay-Zugangsdaten in den Einstellungen eintragen.")
        else:
            others = db.scalars(
                select(Search.interval_s).where(
                    Search.platform == Platform.EBAY.value,
                    Search.active.is_(True),
                    Search.id != (search.id if search else -1),
                )
            ).all()
            projected = quota.projected_daily_calls([*others, clean["interval_s"]])
            if projected > quota.EBAY_DAILY_BUDGET:
                errors.append(
                    f"Zu viele eBay-Abfragen: hochgerechnet {projected} pro Tag, "
                    f"erlaubt sind {quota.EBAY_DAILY_BUDGET}. Takt erhöhen."
                )
    if errors:
        return _render_form(db, values=values, spec=spec, errors=errors, search=search)

    now = rt().now()
    if search is None:
        search = Search(created_at=now, state=SearchState.PENDING.value, next_check_at=now)
        db.add(search)
    elif spec.url != search.url:
        db.execute(delete(Seen).where(Seen.search_id == search.id))
        search.last_ok_at = None
        search.state = SearchState.PENDING.value if search.active else SearchState.PAUSED.value
        search.next_check_at = now
    search.name = values["name"] or suggest_name(spec)
    search.platform = spec.platform.value
    search.url = spec.url
    search.spec_json = json.dumps(spec.to_dict())
    search.interval_s = clean["interval_s"]
    search.max_price = clean["max_price"]
    search.exclude_words = clean["exclude_words"]
    search.silence_days = clean["silence_days"]
    search.targets = [t for t in _targets(db) if t.id in values["target_ids"]]
    db.commit()
    flash(f"Suche „{search.name}“ gespeichert.")
    return redirect(url_for("views.searches"))


@bp.post("/suchen")
def create_search():
    with rt().session_factory() as db:
        return _save(db, None)


@bp.route("/suchen/<int:search_id>", methods=["GET", "POST"])
def edit_search(search_id: int):
    with rt().session_factory() as db:
        search = db.get(Search, search_id)
        if search is None:
            return redirect(url_for("views.searches"))
        if request.method == "POST":
            return _save(db, search)
        values = {
            "url": search.url,
            "name": search.name,
            "interval_min": str(search.interval_s // 60),
            "max_price": "" if search.max_price is None else f"{search.max_price.normalize():f}",
            "exclude_words": search.exclude_words,
            "silence_days": str(search.silence_days),
            "target_ids": [t.id for t in search.targets],
        }
        spec = SearchSpec.from_dict(json.loads(search.spec_json))
        return _render_form(db, values=values, spec=spec, search=search)


def _update(search_id: int, change, message: str):
    with rt().session_factory() as db:
        search = db.get(Search, search_id)
        if search is not None:
            change(db, search)
            db.commit()
            flash(message.format(name=search.name))
    return redirect(url_for("views.searches"))


@bp.post("/suchen/<int:search_id>/pausieren")
def pause_search(search_id: int):
    def change(db, s):
        s.active = False
        s.state = SearchState.PAUSED.value

    return _update(search_id, change, "„{name}“ pausiert.")


@bp.post("/suchen/<int:search_id>/fortsetzen")
def resume_search(search_id: int):
    def change(db, s):
        s.active = True
        s.state = SearchState.PENDING.value
        s.next_check_at = rt().now()

    return _update(search_id, change, "„{name}“ läuft wieder.")


@bp.post("/suchen/<int:search_id>/loeschen")
def delete_search(search_id: int):
    return _update(search_id, lambda db, s: db.delete(s), "„{name}“ gelöscht.")


@bp.post("/suchen/<int:search_id>/pruefen")
def check_search(search_id: int):
    rt().scheduler.check_now(search_id)
    flash("Wird gleich geprüft.")
    return redirect(url_for("views.searches"))


# --- Treffer ------------------------------------------------------------------------------


SORTS = {"neu": "Neueste", "preis_auf": "Preis ↑", "preis_ab": "Preis ↓"}
STATUSES = {"gemeldet": "Gemeldet", "verworfen": "Verworfen"}
_STATUS_VALUES = {"gemeldet": "matched", "verworfen": "rejected"}


def _hit_filters(db) -> dict[str, Any]:
    """Liest die Auswahl aus der URL; Unbekanntes wird still ignoriert."""
    args = request.args
    search_ids = set(db.scalars(select(Search.id)))
    suche = args.get("suche", "")
    return {
        "sort": args.get("sort") if args.get("sort") in SORTS else "neu",
        "suche": int(suche) if suche.isdigit() and int(suche) in search_ids else None,
        "plattform": args.get("plattform")
        if args.get("plattform") in Platform._value2member_map_
        else "",
        "status": args.get("status") if args.get("status") in STATUSES else "",
    }


@bp.get("/treffer")
def hits():
    with rt().session_factory() as db:
        f = _hit_filters(db)
        query = (
            select(Seen, Search.name)
            .join(Search, Search.id == Seen.search_id)
            .where(Seen.status != "seeded")
        )
        if f["suche"] is not None:
            query = query.where(Seen.search_id == f["suche"])
        if f["plattform"]:
            query = query.where(Seen.platform == f["plattform"])
        if f["status"]:
            query = query.where(Seen.status == _STATUS_VALUES[f["status"]])
        # Preis steckt im gespeicherten JSON; Anzeigen ohne Preis kommen ans Ende.
        price = cast(func.json_extract(Seen.listing_json, "$.price"), Float)
        newest = (Seen.first_seen_at.desc(), Seen.id.desc())
        if f["sort"] == "preis_auf":
            query = query.order_by(price.is_(None), price.asc(), *newest)
        elif f["sort"] == "preis_ab":
            query = query.order_by(price.is_(None), price.desc(), *newest)
        else:
            query = query.order_by(*newest)
        items = []
        for seen, search_name in db.execute(query.limit(100)).all():
            try:
                listing = Listing.from_dict(json.loads(seen.listing_json))
            except (KeyError, ValueError, TypeError):
                continue
            items.append({"seen": seen, "listing": listing, "search": search_name})
        failed = db.scalars(
            select(OutboxEntry)
            .where(OutboxEntry.failed_at.is_not(None))
            .order_by(OutboxEntry.failed_at.desc())
            .limit(20)
        ).all()
        return render_template(
            "hits.html",
            items=items,
            failed=failed,
            format_price=format_price,
            filters=f,
            filtered=any([f["suche"] is not None, f["plattform"], f["status"]]),
            searches=db.scalars(select(Search).order_by(Search.name)).all(),
            sorts=SORTS,
            statuses=STATUSES,
            Platform=Platform,
        )


# --- Benachrichtigungen -------------------------------------------------------------------


@bp.route("/benachrichtigungen", methods=["GET", "POST"])
def targets():
    with rt().session_factory() as db:
        error = None
        form = {"name": "", "apprise_url": "", "status_notices": False, "add_to_all": True}
        if request.method == "POST":
            form = {
                "name": request.form.get("name", "").strip(),
                "apprise_url": request.form.get("apprise_url", "").strip(),
                "status_notices": request.form.get("status_notices") == "on",
                "add_to_all": request.form.get("add_to_all") == "on",
            }
            if not form["name"] or not form["apprise_url"]:
                error = "Name und Apprise-Adresse ausfüllen."
            elif not apprise.Apprise().add(form["apprise_url"]):
                error = "Ungültige Apprise-Adresse."
            else:
                target = Target(
                    name=form["name"],
                    apprise_url=form["apprise_url"],
                    status_notices=form["status_notices"],
                )
                db.add(target)
                if form["add_to_all"]:
                    for search in db.scalars(select(Search)):
                        search.targets.append(target)
                db.commit()
                flash(f"Ziel „{form['name']}“ angelegt.")
                return redirect(url_for("views.targets"))
        return render_template(
            "targets.html", targets=_targets(db), mask=mask, error=error, form=form
        )


@bp.post("/benachrichtigungen/<int:target_id>/test")
def test_target(target_id: int):
    with rt().session_factory() as db:
        target = db.get(Target, target_id)
        if target is not None:
            message = Message("Sniper: Test", "Wenn du das liest, klappt die Benachrichtigung.")
            try:
                rt().send(target.apprise_url, message)
                flash(f"Test gesendet an „{target.name}“.")
            except Exception as exc:
                flash(f"Test an „{target.name}“ fehlgeschlagen: {exc}", "error")
    return redirect(url_for("views.targets"))


@bp.post("/benachrichtigungen/<int:target_id>/status")
def toggle_status_notices(target_id: int):
    with rt().session_factory() as db:
        target = db.get(Target, target_id)
        if target is not None:
            target.status_notices = not target.status_notices
            db.commit()
            state = "an" if target.status_notices else "aus"
            flash(f"Statusmeldungen für „{target.name}“ {state}.")
    return redirect(url_for("views.targets"))


@bp.post("/benachrichtigungen/<int:target_id>/loeschen")
def delete_target(target_id: int):
    with rt().session_factory() as db:
        target = db.get(Target, target_id)
        if target is not None:
            db.delete(target)
            db.commit()
            flash(f"Ziel „{target.name}“ gelöscht.")
    return redirect(url_for("views.targets"))


# --- Einstellungen ------------------------------------------------------------------------


@bp.route("/einstellungen", methods=["GET", "POST"])
def settings():
    with rt().session_factory() as db:
        if request.method == "POST" and not ebay_from_env():
            set_setting(db, "ebay_client_id", request.form.get("ebay_client_id", "").strip())
            secret = request.form.get("ebay_client_secret", "").strip()
            if secret:
                set_setting(db, "ebay_client_secret", secret)
            db.commit()
            flash("Einstellungen gespeichert.")
            return redirect(url_for("views.settings"))
        return render_template(
            "settings.html",
            from_env=ebay_from_env(),
            client_id=get_setting(db, "ebay_client_id"),
            has_secret=bool(get_setting(db, "ebay_client_secret")),
            calls_today=quota.calls_today(db, rt().now()),
            limit=quota.EBAY_DAILY_LIMIT,
        )
