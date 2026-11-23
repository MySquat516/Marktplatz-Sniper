# Marktplatz-Sniper Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ein eigener Docker-Container, der wenige Suchen auf eBay, Kleinanzeigen und willhaben im
ruhigen Takt prüft und neue Anzeigen über Apprise aufs Handy meldet, mit kleiner Weboberfläche.

**Architecture:** Ein Python-Prozess: Flask-Oberfläche (über waitress) und ein Planer-Thread teilen
sich eine SQLite-Datenbank. Plattform-Adapter liefern einheitliche `Listing`s, eine reine
Funktion entscheidet „neu/verworfen“, eine Outbox verschickt Meldungen über Apprise.

**Tech Stack:** Python 3.12, uv, Flask 3, SQLAlchemy 2, Alembic, curl_cffi, beautifulsoup4,
apprise, waitress, pytest, ruff. Docker (amd64 + arm64) über GitHub Actions nach ghcr.io.

**Spec:** `docs/superpowers/specs/2026-11-23-marktplatz-sniper-design.md`

## Global Constraints

- Python `>=3.12`; Abhängigkeiten über `pyproject.toml` + `uv.lock`; Paket `src/sniper/`, Kommando `sniper`.
- Oberfläche, Meldungen, Fehlertexte und README auf Deutsch; Code-Bezeichner englisch.
- Ein Prozess, genau ein Planer-Thread (waitress, kein gunicorn mit mehreren Workern).
- Standard-Takt 300 s, Minimum 120 s, Zufall ±20 %; mindestens 10 s Abstand zwischen zwei Anfragen an denselben Host.
- Frischefenster 24 h; höchstens 10 Meldungen pro Check; Stille-Warnung Standard 7 Tage (0 = aus).
- Bei Block: Takt verdoppelt sich je weiterem Fehlschlag, höchstens 3600 s.
- Fehler-Statusmeldung erst nach 3 Fehlschlägen am Stück; Block/Seite-unbekannt sofort; jeweils einmal, plus einmal „läuft wieder“.
- Outbox-Wiederholungen nach 1, 5, 15, 60 min (danach alle 60 min), Aufgeben nach 24 h.
- eBay: `X-EBAY-C-MARKETPLACE-ID: EBAY_DE`, `sort=newlyListed`, `limit=50`; Oberfläche verweigert hochgerechnet > 4500 eBay-Aufrufe/Tag.
- **Keine Verkäuferdaten speichern** (eBay-Ausnahme). Rohantworten nicht dauerhaft speichern (außer Probes).
- Datenverzeichnis `DATA_DIR` (Standard `/data`), Port `PORT` (Standard 8095), `APP_PASSWORD`/`APP_USER` (Standard `admin`) wie im Reseller-Dashboard.
- Image `ghcr.io/mysquat516/marktplatz-sniper`, Tags `latest` und `sha-<commit>`, läuft als Nicht-Root.
- Zeiten in der DB als UTC; Anzeige und Kleinanzeigen-Zeitangaben in `Europe/Berlin`.
- CI grün halten: `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`.
- Die Entwicklungsumgebung erreicht die Plattformen nicht: Adapter-Tests laufen ausschließlich gegen Fixtures, nie live.

## Review Focus

1. **Eingefügte URLs in Alltagsform** (ohne `www.`, `m.ebay.de`, mit Tracking-Parametern, aus der App geteilt) sollen erkannt werden statt „unbekannte Seite“ → Tests in Task 3 (`adapter_for_url`) und Task 4/5.
2. **Deutsche Preisformate** (`1.250 €`, `12,50 €`, `VB`, `Zu verschenken`, willhaben `"1.250"`) werden richtig zu `Decimal`, nie zum Absturz → Tests in Task 5 und 6.
3. **Ein kaputtes Benachrichtigungsziel** (ungültige Apprise-URL, Dienst down) darf andere Ziele und den Planer nicht blockieren → Test in Task 8.
4. **Neustart nach langer Pause** (alle `next_check_at` in der Vergangenheit): jede Suche läuft genau einmal, kein Nachholen in Schleife → Test in Task 10.
5. **Dieselbe Anzeige in zwei Suchen**: jede Suche entscheidet für sich, beide melden an ihre Ziele → Test in Task 9.

---

## Dateistruktur

```
pyproject.toml, uv.lock, alembic.ini, Dockerfile, docker-compose.yml, docker-entrypoint.sh, README.md
.github/workflows/ci.yml, .github/workflows/docker.yml
migrations/env.py, migrations/versions/0001_initial.py
src/sniper/
  __init__.py
  config.py            Settings aus Umgebungsvariablen
  models.py            Platform, Listing, SearchSpec, SearchState
  db.py                ORM-Tabellen, Engine, Migration beim Start
  cli.py               `sniper serve`, `sniper probe`
  platforms/
    __init__.py        adapter_for_url, build_adapters
    base.py            Adapter-Protokoll, Fehlerklassen
    http.py            HttpClient (curl_cffi), Block-Erkennung
    ebay.py, kleinanzeigen.py, willhaben.py
    prices.py          deutsche Preis-Strings → Decimal
  engine/
    detect.py          Neu-Erkennung + Filter (rein)
    check.py           ein Check: Abruf → Entscheidung → Seen/Outbox → Zustand
    quota.py           eBay-Tageskontingent
    scheduler.py       Planer-Schleife
  notify/
    message.py         Meldungstexte
    sender.py          Apprise-Wrapper
    outbox.py          Einreihen, Zustellen, Wiederholen
  web/
    __init__.py        create_app
    auth.py            optionaler Login
    views.py           alle Routen
    templates/*.html, static/style.css
tests/  (spiegelt src/; Fixtures unter tests/fixtures/<plattform>/)
```

---

### Task 1: Projektgerüst, Modelle, CI

**Files:**
- Create: `pyproject.toml`, `src/sniper/__init__.py`, `src/sniper/models.py`, `src/sniper/config.py`, `.github/workflows/ci.yml`, `.gitignore`
- Test: `tests/test_models.py`, `tests/test_config.py`

**Interfaces:**
- Produces:
  - `class Platform(StrEnum)`: `EBAY="ebay"`, `KLEINANZEIGEN="kleinanzeigen"`, `WILLHABEN="willhaben"`; Property `label` → `"eBay"`, `"Kleinanzeigen"`, `"willhaben"`.
  - `@dataclass(frozen=True) class Listing`: `platform: Platform`, `external_id: str`, `title: str`, `url: str`, `price: Decimal | None = None`, `currency: str = "EUR"`, `negotiable: bool = False`, `listing_type: Literal["fixed","auction"] = "fixed"`, `shipping: bool | None = None`, `shipping_cost: Decimal | None = None`, `photo_urls: tuple[str, ...] = ()`, `location: str | None = None`, `posted_at: datetime | None = None` (UTC, tz-aware); `to_dict() -> dict` (JSON-tauglich: Decimal als String, datetime ISO) und `Listing.from_dict(d) -> Listing`.
  - `@dataclass(frozen=True) class SearchSpec`: `platform: Platform`, `url: str` (normalisiert), `params: dict[str, str]`, `ignored: tuple[str, ...] = ()`; `to_dict()`/`from_dict()`.
  - `class SearchState(StrEnum)`: `PENDING="pending"`, `OK="ok"`, `ERROR="error"`, `BLOCKED="blocked"`, `LAYOUT_CHANGED="layout_changed"`, `PAUSED="paused"`; Property `label` → `"Neu"`, `"OK"`, `"Fehler"`, `"Geblockt"`, `"Seite unbekannt"`, `"Pausiert"`.
  - `@dataclass(frozen=True) class Settings`: `data_dir: Path`, `port: int`, `app_password: str`, `app_user: str`, `ebay_client_id: str`, `ebay_client_secret: str`; `Settings.from_env(env: Mapping[str,str] = os.environ) -> Settings` mit Standards `/data`, `8095`, `""`, `"admin"`, `""`, `""`.

- [ ] **Step 1: Write the failing tests**
  - `test_listing_roundtrip`: Listing mit allen Feldern (Preis `Decimal("12.50")`, `posted_at` UTC, zwei Fotos) → `Listing.from_dict(json.loads(json.dumps(l.to_dict()))) == l`.
  - `test_listing_dict_has_no_seller_fields`: `set(l.to_dict())` enthält keinen Schlüssel mit `seller`.
  - `test_search_spec_roundtrip`: analog.
  - `test_labels`: `Platform.KLEINANZEIGEN.label == "Kleinanzeigen"`, `SearchState.LAYOUT_CHANGED.label == "Seite unbekannt"`.
  - `test_settings_defaults`: `Settings.from_env({})` → `data_dir == Path("/data")`, `port == 8095`, `app_user == "admin"`.
- [ ] **Step 2: Run `uv run pytest -q`** → FAIL (Module fehlen).
- [ ] **Step 3: Implement** `pyproject.toml` (Abhängigkeiten aus Tech Stack, `[project.scripts] sniper = "sniper.cli:main"`, ruff line-length 100, pytest `testpaths=["tests"]`), Modelle und Settings wie oben; `ci.yml` führt pytest, `ruff check`, `ruff format --check` mit `astral-sh/setup-uv` aus.
- [ ] **Step 4: Run `uv run pytest -q && uv run ruff check . && uv run ruff format --check .`** → alles grün.
- [ ] **Step 5: Commit** `Add project skeleton, listing model and CI`

---

### Task 2: Datenbank und Migration

**Files:**
- Create: `src/sniper/db.py`, `alembic.ini`, `migrations/env.py`, `migrations/versions/0001_initial.py`
- Test: `tests/test_db.py`

**Interfaces:**
- Consumes: `Platform`, `SearchState` (Task 1).
- Produces (SQLAlchemy 2, `DeclarativeBase`):
  - `Search`: `id`, `name: str`, `platform: str`, `url: str`, `spec_json: str`, `interval_s: int = 300`, `max_price: Decimal | None`, `exclude_words: str = ""` (ein Wort pro Zeile), `silence_days: int = 7`, `active: bool = True`, `state: str = "pending"`, `notified_state: str | None`, `consecutive_failures: int = 0`, `next_check_at: datetime | None`, `last_check_at`, `last_ok_at`, `last_match_at: datetime | None`, `last_error: str | None`, `silence_notified: bool = False`, `created_at: datetime`; Beziehung `targets: list[Target]` über `search_targets`.
  - `Seen`: `id`, `search_id` (FK, `ondelete=CASCADE`), `platform`, `external_id`, `status` (`seeded|matched|rejected`), `reason: str | None`, `listing_json: str`, `first_seen_at`; `UniqueConstraint(search_id, platform, external_id)`.
  - `Target`: `id`, `name`, `apprise_url`, `status_notices: bool = False`.
  - `search_targets`: `search_id`, `target_id`, beide `ondelete=CASCADE`.
  - `OutboxEntry`: `id`, `target_id` (FK CASCADE), `search_id` (FK `SET NULL`, nullable), `kind` (`listing|status`), `title`, `body`, `attach_url: str | None`, `attempts: int = 0`, `next_attempt_at`, `created_at`, `sent_at`, `failed_at: datetime | None`, `last_error: str | None`.
  - `Setting`: `key` (PK), `value`.
  - `make_engine(data_dir: Path) -> Engine` (SQLite `sniper.db`, `PRAGMA foreign_keys=ON` per Connect-Event, WAL), `make_session_factory(engine) -> sessionmaker[Session]`, `migrate(engine) -> None` (Alembic `upgrade head` programmatisch).
  - `get_setting(session, key, default="") -> str`, `set_setting(session, key, value) -> None`.

- [ ] **Step 1: Write the failing tests**
  - `test_migrate_creates_tables(tmp_path)`: nach `migrate` existieren alle sechs Tabellen.
  - `test_seen_unique_per_search`: zweites `Seen` mit gleichem (search, platform, external_id) → `IntegrityError`; gleiches in anderer Suche → ok.
  - `test_delete_search_cascades_seen_and_keeps_outbox`: Suche löschen → Seen weg, OutboxEntry bleibt mit `search_id is None`.
  - `test_settings_roundtrip`.
- [ ] **Step 2: Run `uv run pytest tests/test_db.py -q`** → FAIL.
- [ ] **Step 3: Implement** Modelle, Engine, Alembic-Setup (`script_location` relativ zum Paket auflösen, damit es im Container funktioniert) und Migration `0001_initial`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add database schema and migrations`

---

### Task 3: HTTP-Schicht, Probe-Kommando, Docker-Image

Ziel dieses Tasks ist auch, dass Leon früh echte Antworten aufnehmen kann (siehe Task 12).

**Files:**
- Create: `src/sniper/platforms/base.py`, `src/sniper/platforms/http.py`, `src/sniper/platforms/__init__.py`, `src/sniper/cli.py`, `Dockerfile`, `docker-entrypoint.sh`, `docker-compose.yml`, `.dockerignore`, `.github/workflows/docker.yml`
- Test: `tests/platforms/test_http.py`, `tests/platforms/test_registry.py`, `tests/test_cli_probe.py`

**Interfaces:**
- Produces:
  - Fehler in `base.py`: `class AdapterError(Exception)`; Unterklassen `Blocked`, `RateLimited(retry_after: float | None)`, `LayoutChanged`, `NetworkError`, `MissingCredentials`; separat `class InvalidUrl(ValueError)` (Text für die Oberfläche).
  - `class Adapter(Protocol)`: `platform: Platform`; `parse_url(url: str) -> SearchSpec`; `fetch(spec: SearchSpec) -> list[Listing]` (neueste zuerst).
  - `@dataclass class HttpResponse`: `status: int`, `text: str`, `headers: dict[str, str]`.
  - `class HttpClient`: `__init__(min_spacing_s: float = 10.0, clock=time.monotonic, sleep=time.sleep, session=None)`; `get(url, *, params=None, headers=None) -> HttpResponse`; `post(url, *, data=None, headers=None, auth=None) -> HttpResponse`. curl_cffi-`Session(impersonate="chrome")`, Cookies bleiben erhalten, Timeout 20 s, Netzwerkfehler → `NetworkError`. Wartet so, dass zwischen zwei Anfragen an denselben Host ≥ `min_spacing_s` liegen.
  - `check_blocked(resp: HttpResponse) -> None`: 429 → `RateLimited` (Header `Retry-After` als Sekunden, sonst None); 403/503 → `Blocked`; Status 200 mit `"Just a moment"`, `"cf-chl"` oder `"challenge-platform"` im Text → `Blocked`.
  - `adapter_for_url(url: str, adapters: Mapping[Platform, Adapter]) -> Adapter`: Host (ohne `www.`/`m.`) `ebay.de` → eBay, `kleinanzeigen.de` → Kleinanzeigen, `willhaben.at` → willhaben; URL ohne Schema bekommt `https://`; sonst `InvalidUrl("Unbekannte Seite – unterstützt werden eBay, Kleinanzeigen und willhaben.")`.
  - `build_adapters(http: HttpClient, credentials: Callable[[], tuple[str, str]]) -> dict[Platform, Adapter]` (füllt sich in Task 4–6).
  - CLI: `sniper probe <url> [--out DIR]` (Standard `DATA_DIR/probes`) ruft die URL einmal per `HttpClient.get` ab und schreibt `<plattform>-<YYYYmmdd-HHMMSS>.html` (Body) und `.headers.json` (Status + Header); gibt beide Pfade aus. Kein `check_blocked` – auch Challenge-Seiten sollen gespeichert werden.
  - Docker: `python:3.12-slim`, `uv sync --frozen --no-dev`, Nicht-Root-Benutzer `sniper`, Entrypoint setzt Rechte auf `/data` und wechselt den Benutzer (wie im Dashboard), `ENTRYPOINT ["docker-entrypoint.sh", "sniper"]`, `CMD ["serve"]`, `EXPOSE 8095`, `VOLUME /data`. Healthcheck kommt in Task 10. `docker.yml` 1:1 nach dem Muster des Dashboards (QEMU, buildx, amd64+arm64, Tags `latest` + `sha-`).

- [ ] **Step 1: Write the failing tests**
  - `test_check_blocked_*`: 403 → `Blocked`; 503 → `Blocked`; 429 mit `Retry-After: 120` → `RateLimited(retry_after=120)`; 200 mit `<title>Just a moment...</title>` → `Blocked`; 200 normal → kein Fehler.
  - `test_spacing_per_host`: Fake-Clock/-Sleep, Fake-Session; zwei `get` an denselben Host direkt hintereinander → `sleep(10.0)` aufgerufen; an zwei verschiedene Hosts → kein Sleep.
  - `test_network_error_wrapped`: Fake-Session wirft → `NetworkError`.
  - `test_adapter_for_url` (parametrisiert): `www.ebay.de/sch/i.html?_nkw=x`, `ebay.de/sch/...`, `https://m.ebay.de/sch/...`, `www.kleinanzeigen.de/s-jacke/k0`, `kleinanzeigen.de/s-jacke/k0?utm_source=app`, `https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz?keyword=x` → richtige Plattform; `https://example.com` → `InvalidUrl`.
  - `test_probe_writes_files(tmp_path)`: Fake-HttpClient liefert 200/`<html>x</html>` → beide Dateien existieren, `.headers.json` enthält `"status": 200`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** wie in Interfaces.
- [ ] **Step 4: Run** `uv run pytest -q` → PASS; `docker build -t sniper .` → baut, `docker run --rm sniper probe --help` → Hilfe erscheint (ist Docker in der Arbeitsumgebung nicht verfügbar: nach dem Push muss der Workflow `docker.yml` grün sein).
- [ ] **Step 5: Commit** `Add HTTP client, probe command and Docker image`

---

### Task 4: eBay-Adapter

**Files:**
- Create: `src/sniper/platforms/ebay.py`, `tests/fixtures/ebay/search.json`, `tests/fixtures/ebay/token.json`
- Modify: `src/sniper/platforms/__init__.py` (in `build_adapters` registrieren)
- Test: `tests/platforms/test_ebay.py`

**Interfaces:**
- Consumes: `HttpClient`, `check_blocked`, Fehlerklassen (Task 3), `Listing`, `SearchSpec` (Task 1).
- Produces: `class EbayAdapter(Adapter)`: `__init__(http: HttpClient, credentials: Callable[[], tuple[str, str]], clock=time.time)`.
  - Token: `POST https://api.ebay.com/identity/v1/oauth2/token`, Basic-Auth `client_id:secret`, `grant_type=client_credentials`, `scope=https://api.ebay.com/oauth/api_scope`; zwischenspeichern bis `expires_in - 60` s. Leere Zugangsdaten → `MissingCredentials("eBay-Zugangsdaten fehlen (Einstellungen).")`.
  - Suche: `GET https://api.ebay.com/buy/browse/v1/item_summary/search` mit `Authorization: Bearer …`, `X-EBAY-C-MARKETPLACE-ID: EBAY_DE`, Parametern aus `spec.params` plus `sort=newlyListed`, `limit=50`.
  - `parse_url`: Pfad muss mit `/sch/` beginnen, sonst `InvalidUrl`. Übersetzung: `_nkw→q`; `_sacat→category_ids` (Wert `0` ignorieren); `_udlo`/`_udhi→price:[lo..hi]` (offene Seite leer lassen) plus `priceCurrency:EUR`; `LH_ItemCondition` (`|`-getrennt) `→conditionIds:{a|b}`; `LH_BIN=1`/`LH_Auction=1 → buyingOptions:{FIXED_PRICE|AUCTION}`; `LH_PrefLoc=1 → itemLocationCountry:DE`. Filterteile mit `,` zu `params["filter"]` verbinden. Ohne `q` und ohne `category_ids` → `InvalidUrl("Die eBay-URL enthält keinen Suchbegriff.")`. Stillschweigend übergehen: `_from`, `_trksid`, `rt`, `_sop`, `_osacat`, `_odkw`, `_ipg`, `_pgn`. Alle anderen Parameter → `ignored`.
  - Mapping: `external_id = legacyItemId or itemId`; `url = itemWebUrl`; Preis aus `price` bzw. bei Auktionen `currentBidPrice`; `listing_type="auction"` wenn `"AUCTION"` in `buyingOptions` und nicht `"FIXED_PRICE"`; `shipping_cost` aus `shippingOptions[0].shippingCost.value` (`shipping=True`, wenn Versandoptionen da); Fotos `image.imageUrl` + `additionalImages[].imageUrl`; `location = "{postalCode} {city}"` (fehlende Teile weglassen); `posted_at` aus `itemCreationDate`. Seller-Felder werden nicht gelesen.
  - HTTP 401 beim Suchen → Token verwerfen, einmal neu holen, dann erneut versuchen.

- [ ] **Step 1: Write the failing tests** (Fixture `search.json` mit drei `itemSummaries` nach der dokumentierten Browse-API-Form: Festpreis mit Versandkosten, Auktion mit `currentBidPrice`, Artikel ohne `additionalImages`; jeder mit `seller`-Block)
  - `test_parse_url_translates_filters`: `https://www.ebay.de/sch/i.html?_nkw=carhartt+jacke&_sacat=57988&_udlo=10&_udhi=60&LH_ItemCondition=3000&LH_BIN=1&LH_PrefLoc=1&_sop=10` → `params == {"q": "carhartt jacke", "category_ids": "57988", "filter": "price:[10..60],priceCurrency:EUR,conditionIds:{3000},buyingOptions:{FIXED_PRICE},itemLocationCountry:DE"}`, `ignored == ()`.
  - `test_parse_url_reports_unknown_params`: `…&_nkw=x&LH_Sold=1` → `ignored == ("LH_Sold",)`.
  - `test_parse_url_open_price`: nur `_udlo=10` → `price:[10..]`.
  - `test_parse_url_requires_keyword_or_category` → `InvalidUrl`.
  - `test_fetch_maps_listings`: Fake-HTTP; erstes Listing: `external_id`, `price == Decimal("45.00")`, `shipping_cost == Decimal("4.99")`, `posted_at` tz-aware; Auktion: `listing_type == "auction"`; kein Listing-Dict enthält Verkäuferangaben.
  - `test_fetch_sends_marketplace_header_and_sort`: Anfrage hat `X-EBAY-C-MARKETPLACE-ID: EBAY_DE`, `sort=newlyListed`, `limit=50`.
  - `test_token_is_cached`: zwei `fetch` → ein Token-POST; nach `expires_in` → zweiter Token-POST.
  - `test_401_refreshes_token_once`.
  - `test_missing_credentials`: `credentials=lambda: ("", "")` → `MissingCredentials`.
  - `test_429_raises_rate_limited`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `EbayAdapter`.
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add eBay adapter`

---

### Task 5: Kleinanzeigen-Adapter

**Files:**
- Create: `src/sniper/platforms/kleinanzeigen.py`, `src/sniper/platforms/prices.py`, `tests/fixtures/kleinanzeigen/results.html`, `tests/fixtures/kleinanzeigen/empty.html`, `tests/fixtures/kleinanzeigen/challenge.html`
- Modify: `src/sniper/platforms/__init__.py`
- Test: `tests/platforms/test_kleinanzeigen.py`, `tests/platforms/test_prices.py`

**Interfaces:**
- Produces:
  - `parse_price(text: str) -> tuple[Decimal | None, bool]` in `prices.py`: gibt (Preis, VB) zurück. `"45 €"→(45, False)`, `"45 € VB"→(45, True)`, `"VB"→(None, True)`, `"1.250 €"→(1250, False)`, `"12,50 €"→(12.50, False)`, `"Zu verschenken"→(0, False)`, `""→(None, False)`; unbekannter Text → `(None, False)`, nie eine Exception.
  - `class KleinanzeigenAdapter(Adapter)`: `__init__(http: HttpClient, now=lambda: datetime.now(UTC))`.
  - `parse_url`: nur Pfade mit `/s-`; Tracking-Parameter (`utm_*`) entfernen; Sortierung „neueste“ erzwingen (Kandidat: Pfadsegment `sortierung:neueste` direkt nach `/s-`, z. B. `/s-sortierung:neueste/jacke/k0`; in Task 12 gegen eine echte Probe prüfen).
  - `fetch`: `GET` + `check_blocked`; Parsen mit BeautifulSoup (`html.parser`). Alle CSS-Selektoren stehen in **einem** Modul-Dict `SELECTORS` (Kandidaten: Ergebnisliste `#srchrslt-adtable`, Eintrag `article.aditem` mit `data-adid` und `data-href`, Titel `.aditem-main .text-module-begin a`, Preis `.aditem-main--middle--price-shipping--price`, Ort `.aditem-main--top--left`, Zeit `.aditem-main--top--right`, Bild `.imagebox img`, Versand-Hinweis: Text „Versand möglich“). Fehlt die Ergebnisliste und es gibt keinen Hinweis auf „keine Ergebnisse“ → `LayoutChanged`.
  - Zeit: `"Heute, 07:12"`, `"Gestern, 18:30"`, `"21.11.2026"` (dann 00:00) in `Europe/Berlin` → UTC; Unbekanntes → `None`.
  - Ort: Mehrfach-Leerzeichen/Zeilenumbrüche zu einem Leerzeichen zusammenfassen.

- [ ] **Step 1: Write the failing tests** (`results.html` synthetisch nach den Selektoren oben: vier Anzeigen mit `45 € VB`, `Zu verschenken`, `1.250 €`, `VB`; eine mit „Versand möglich“)
  - `test_parse_price` (parametrisiert über alle Beispiele oben, plus `"  45 €\n VB "`).
  - `test_parse_url_forces_newest_and_strips_tracking`: `https://kleinanzeigen.de/s-jacke/k0?utm_source=app` → `spec.url == "https://www.kleinanzeigen.de/s-sortierung:neueste/jacke/k0"`.
  - `test_fetch_parses_listings`: 4 Listings, IDs aus `data-adid`, absolute URLs, Preise/VB korrekt, `shipping is True` beim einen.
  - `test_relative_times` mit festem `now` (`2026-11-23 07:30 Europe/Berlin`): „Heute, 07:12“ → `2026-11-23T06:12Z`; „Gestern, 18:30“ → `2026-11-22T17:30Z`.
  - `test_empty_results_returns_empty_list` (`empty.html`).
  - `test_challenge_page_is_blocked` (`challenge.html`).
  - `test_unknown_page_is_layout_changed` (`<html><body>neu</body></html>`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add Kleinanzeigen adapter`

---

### Task 6: willhaben-Adapter

**Files:**
- Create: `src/sniper/platforms/willhaben.py`, `tests/fixtures/willhaben/results.html`, `tests/fixtures/willhaben/no_next_data.html`
- Modify: `src/sniper/platforms/__init__.py`
- Test: `tests/platforms/test_willhaben.py`

**Interfaces:**
- Consumes: `parse_price` (Task 5).
- Produces: `class WillhabenAdapter(Adapter)`: `__init__(http: HttpClient)`.
  - `parse_url`: Host `willhaben.at`, Pfad unter `/iad/`; Sortierung „neueste“ erzwingen (Kandidat: Query `sort=1`; in Task 12 prüfen); `utm_*` entfernen.
  - `fetch`: `GET` + `check_blocked`; JSON aus `<script id="__NEXT_DATA__">`; Liste unter `props.pageProps.searchResult.advertSummaryList.advertSummary` (Pfad als Konstante `RESULT_PATH`). Pro Eintrag: `external_id = str(id)`, `title = description`; Attribute über Hilfsfunktion `attr(summary, name) -> str | None` aus `attributes.attribute[]` (`name`, `values[0]`). Namen als Konstanten (Kandidaten `PRICE`, `LOCATION`, `POSTCODE`, `PUBLISHED`, `SEO_URL`). URL `https://www.willhaben.at/iad/` + `SEO_URL`; Fotos aus `advertImageList.advertImage[].mainImageUrl`; Preis über `parse_price` (willhaben liefert Zahlen-Strings wie `"1.250"` oder `"45"`); `posted_at` aus `PUBLISHED` (ISO-String oder Epoch-Millisekunden, beides unterstützen).
  - Kein `__NEXT_DATA__` oder Pfad fehlt → `LayoutChanged`; leere Liste → `[]`.

- [ ] **Step 1: Write the failing tests** (`results.html` mit eingebettetem JSON, drei Anzeigen; eine mit Preis `"1.250"`, eine mit `PUBLISHED` als Epoch-ms)
  - `test_parse_url_forces_newest`.
  - `test_fetch_parses_listings`: IDs, URLs, `price == Decimal("1250")`, Fotos, `posted_at` für beide Zeitformate.
  - `test_missing_next_data_is_layout_changed`.
  - `test_challenge_page_is_blocked`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add willhaben adapter`

---

### Task 7: Neu-Erkennung und Filter

**Files:**
- Create: `src/sniper/engine/detect.py`
- Test: `tests/engine/test_detect.py`

**Interfaces:**
- Consumes: `Listing` (Task 1).
- Produces:
  - `FRESHNESS = timedelta(hours=24)`, `MAX_NOTIFICATIONS_PER_CHECK = 10`.
  - `@dataclass(frozen=True) class Filters`: `max_price: Decimal | None = None`, `exclude_words: tuple[str, ...] = ()`; `Filters.from_text(max_price, exclude_text: str) -> Filters` (ein Wort pro Zeile, leer/Whitespace verworfen).
  - `@dataclass(frozen=True) class Verdict`: `listing: Listing`, `status: Literal["seeded","matched","rejected"]`, `reason: str | None`, `notify: bool`.
  - `@dataclass(frozen=True) class Detection`: `verdicts: list[Verdict]`, `overflow: int`.
  - `detect(listings: Sequence[Listing], seen_ids: set[str], filters: Filters, *, first_check: bool, now: datetime) -> Detection`.
- Regeln (in dieser Reihenfolge, Listings in Eingabereihenfolge = neueste zuerst): IDs in `seen_ids` werden übersprungen (kein Verdict); doppelte IDs innerhalb einer Antwort zählen einmal. `first_check` → alle `seeded`, `notify=False`. Sonst: `posted_at` älter als `FRESHNESS` → `rejected`, Grund exakt `"zu alt"`; `price is not None and max_price is not None and price > max_price` → `"über Höchstpreis"`; Ausschlusswort (`casefold`-Teilstring im Titel) → `"Ausschlusswort: {wort}"` (Wort so, wie es eingetragen wurde); sonst `matched`. Die ersten 10 `matched` bekommen `notify=True`, weitere `notify=False`; `overflow` = Anzahl dieser weiteren.

- [ ] **Step 1: Write the failing tests**
  - `test_first_check_seeds_silently`.
  - `test_seen_ids_are_skipped`.
  - `test_duplicate_ids_in_one_response_count_once`.
  - `test_too_old_rejected` (25 h alt) / `test_unknown_age_passes` (`posted_at=None`).
  - `test_max_price` (Preis 61 bei max 60 → rejected; Preis `None` → matched; Preis 0 → matched).
  - `test_exclude_words_casefold`: Wort `"Defekt"` trifft Titel `"jacke DEFEKT"`; Wort `"ärmel"` trifft `"Ärmel kaputt"`; Grund `"Ausschlusswort: Defekt"`.
  - `test_cap_and_overflow`: 13 neue passende → 10 `notify=True`, `overflow == 3`, die ersten 10 sind die ersten 10 der Eingabe.
  - `test_filters_from_text`: `"defekt\n\n  fake \n"` → `("defekt", "fake")`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add new-listing detection and filters`

---

### Task 8: Meldungstexte, Versand, Outbox

**Files:**
- Create: `src/sniper/notify/message.py`, `src/sniper/notify/sender.py`, `src/sniper/notify/outbox.py`
- Test: `tests/notify/test_message.py`, `tests/notify/test_outbox.py`, `tests/notify/test_sender.py`

**Interfaces:**
- Consumes: `Listing`, `Platform`, `SearchState` (Task 1); `OutboxEntry`, `Target` (Task 2).
- Produces:
  - `@dataclass(frozen=True) class Message`: `title: str`, `body: str`, `attach_url: str | None = None`.
  - `format_price(listing: Listing) -> str`: `None`+VB → `"VB"`; `None` → `"ohne Preis"`; `0` → `"Zu verschenken"`; sonst deutsches Format `"45 €"` / `"45,50 €"` / `"1.250 €"`, mit `" VB"` wenn verhandelbar, mit `" (Auktion)"` bei Auktionen.
  - `listing_message(listing, search_name, now) -> Message`: Titel exakt `"[{platform.label}] {title} – {format_price}"`; Body-Zeilen: Titel; Preis plus `" + {Versand} Versand"` wenn `shipping_cost`, `"nur Abholung"` wenn `shipping is False`; Ort (falls vorhanden); `"eingestellt vor {n} min"` (< 60 min) bzw. `"eingestellt vor {n} h"` (falls `posted_at`); `"Suche: {search_name}"`; URL. `attach_url` = erstes Foto.
  - `overflow_message(search_name, platform, count, search_url) -> Message`: Titel `"[{label}] {search_name}: {count} weitere neue Anzeigen"`, Body `"Mehr als 10 Treffer auf einmal. Alle ansehen: {search_url}"`.
  - `status_message(search_name, platform, state, detail) -> Message` für `BLOCKED` (Titel `"Sniper: {name} geblockt"`, Body `"{label} blockt die Abfragen gerade. Der Sniper versucht es seltener weiter (bis alle 60 min) und meldet sich, wenn es wieder läuft."`), `LAYOUT_CHANGED` (`"Sniper: {name} – Seite unbekannt"`, `"{label} hat die Seite geändert, der Sniper erkennt keine Anzeigen mehr. Probe-Kommando ausführen und Datei weitergeben."`), `ERROR` (`"Sniper: {name} – Fehler"`, `"Die letzten 3 Abfragen sind fehlgeschlagen. Letzter Fehler: {detail}"`).
  - `recovery_message(search_name) -> Message`: `"Sniper: {name} läuft wieder"` / `"Die Suche funktioniert wieder normal."`.
  - `silence_message(search_name, platform, days) -> Message`: `"Sniper: {name} ist still"` / `"Seit {days} Tagen keine neue Anzeige. Prüf die Suche oder ob {label} sich verändert hat."`.
  - `class SendError(Exception)`; `send(apprise_url: str, message: Message) -> None` in `sender.py`: `apprise.Apprise().add(url)` false → `SendError("Ungültige Apprise-Adresse")`; `notify(title, body, attach=…)` false → `SendError("Zustellung fehlgeschlagen")`. Bei fehlgeschlagenem Anhang einmal ohne Anhang wiederholen.
  - `BACKOFF = (1, 5, 15, 60)` Minuten, `GIVE_UP_AFTER = timedelta(hours=24)`.
  - `enqueue(session, targets: Iterable[Target], message, *, kind: Literal["listing","status"], search_id: int | None, now) -> None` (kein Commit; Aufrufer committet).
  - `deliver_due(session, now, send=sender.send) -> int`: alle Einträge mit `sent_at is None and failed_at is None and next_attempt_at <= now`, älteste zuerst; jeder Versand einzeln, nach Erfolg sofort `sent_at` + Commit; bei `SendError` oder anderer Exception: `attempts += 1`, `last_error`, `next_attempt_at = now + BACKOFF[min(attempts-1, 3)]`, bei `now - created_at >= GIVE_UP_AFTER` stattdessen `failed_at = now`; Commit. Gibt Anzahl erfolgreicher Sendungen zurück.

- [ ] **Step 1: Write the failing tests**
  - `test_format_price` (parametrisiert: 45, 45.50, 1250, 0, None+VB, None, 45+VB, Auktion 12).
  - `test_listing_message_title_and_body`: `now` fix, `posted_at = now - 4 min` → Body enthält `"eingestellt vor 4 min"`, `"Suche: Jacken"`, URL; Titel `"[Kleinanzeigen] Jacke Gr. L – 45 € VB"`; `attach_url` = erstes Foto.
  - `test_listing_message_shipping_lines`: `shipping_cost=4.99` → `"+ 4,99 € Versand"`; `shipping=False` → `"nur Abholung"`.
  - `test_status_texts` (Titel aller drei Zustände + recovery + silence + overflow exakt).
  - `test_deliver_due_marks_sent`.
  - `test_failed_target_does_not_block_others`: zwei Einträge, Fake-`send` wirft für Ziel A → B trotzdem `sent_at` gesetzt, A `attempts == 1`, `next_attempt_at == now + 1 min`.
  - `test_backoff_sequence`: nach 1, 2, 3, 4, 5 Fehlschlägen → Abstände 1, 5, 15, 60, 60 min.
  - `test_gives_up_after_24h`: Eintrag 24 h alt, Versand scheitert → `failed_at` gesetzt, wird nicht mehr versucht.
  - `test_sender_invalid_url_raises` (echtes Apprise, URL `"kaputt://"`).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add messages, Apprise sender and outbox`

---

### Task 9: Ein Check: Zustände, Statusmeldungen, eBay-Kontingent

**Files:**
- Create: `src/sniper/engine/check.py`, `src/sniper/engine/quota.py`
- Test: `tests/engine/test_check.py`, `tests/engine/test_quota.py`

**Interfaces:**
- Consumes: `Adapter` + Fehler (Task 3), `detect`, `Filters` (Task 7), `enqueue`, Meldungsfunktionen (Task 8), ORM (Task 2).
- Produces:
  - `MAX_INTERVAL_S = 3600`, `ERROR_NOTICE_AFTER = 3`.
  - `run_check(session, search: Search, adapter: Adapter, now: datetime, rng=random.random) -> SearchState`. Ablauf in **einer** Transaktion (am Ende ein Commit):
    1. `adapter.fetch(SearchSpec.from_dict(json.loads(search.spec_json)))`.
    2. Erfolg: `first_check = search.last_ok_at is None`; `seen_ids` aus `Seen` dieser Suche; `detect(...)`; pro Verdict ein `Seen` (mit `listing_json`, `reason`); für `notify`-Verdicts `listing_message` an `search.targets`; bei `overflow > 0` eine `overflow_message`. Bei mindestens einem `notify`: `last_match_at = now`, `silence_notified = False`. Zustand `OK`, `consecutive_failures = 0`, `last_ok_at = now`, `last_error = None`. War `notified_state` gesetzt → `recovery_message` an Ziele mit `status_notices` und `notified_state = None`. Stille: `silence_days > 0`, nicht `silence_notified`, `now - (last_match_at or created_at) >= silence_days` Tage → `silence_message`, `silence_notified = True`.
    3. `Blocked`/`RateLimited` → `BLOCKED`; `LayoutChanged` → `LAYOUT_CHANGED`; andere `AdapterError` → `ERROR`. Jeweils `consecutive_failures += 1`, `last_error = str(exc)`. Statusmeldung an Ziele mit `status_notices`, wenn `notified_state != state` und (state ist `BLOCKED`/`LAYOUT_CHANGED` oder `consecutive_failures >= 3`); dann `notified_state = state`.
    4. Immer: `last_check_at = now`; `next_check_at = now + next_interval(search, state, rng)`; bei `platform == "ebay"`: `quota.record_call(session, now)`.
  - `next_interval(search, state, rng) -> timedelta`: Basis `interval_s`; bei `BLOCKED` `min(interval_s * 2**consecutive_failures, 3600)`; Zufall `basis * (0.8 + 0.4 * rng())`.
  - `quota.record_call(session, now) -> None` (Zähler pro UTC-Tag in `Setting` `ebay_calls:{YYYY-MM-DD}`), `quota.calls_today(session, now) -> int`, `quota.projected_daily_calls(intervals_s: Iterable[int]) -> int` (= Summe `ceil(86400 / i)`), `EBAY_DAILY_BUDGET = 4500`.

- [ ] **Step 1: Write the failing tests** (Fake-Adapter mit vorgegebener Liste oder Exception; In-Memory-SQLite mit `migrate`)
  - `test_first_check_seeds_and_sends_nothing`.
  - `test_second_check_notifies_new_listing`: Outbox enthält einen `listing`-Eintrag pro Ziel der Suche.
  - `test_same_listing_in_two_searches_notifies_both` (Review Focus 5).
  - `test_overflow_enqueues_summary`.
  - `test_blocked_notifies_once_and_backs_off`: drei Blocks hintereinander → genau eine Statusmeldung; Intervalle (rng=0.5) 600, 1200, 2400 s; vierter → 3600 (Deckel).
  - `test_error_notifies_after_three`: Fehlschlag 1 und 2 → keine Meldung, 3 → eine, 4 → keine.
  - `test_recovery_after_notice`: Block mit Meldung, dann Erfolg → `recovery_message`; Erfolg ohne vorherige Meldung → keine.
  - `test_silence_warning_once`: `created_at` 8 Tage her, keine Treffer → eine Stille-Meldung; nächster Check → keine weitere; neuer Treffer setzt zurück.
  - `test_status_notices_only_to_flagged_targets`.
  - `test_ebay_check_counts_quota`; `test_projected_daily_calls`: `[300, 300, 300]` → 864.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS.
- [ ] **Step 5: Commit** `Add check run with states, notices and eBay quota`

---

### Task 10: Planer und `sniper serve`

**Files:**
- Create: `src/sniper/engine/scheduler.py`
- Modify: `src/sniper/cli.py` (Kommando `serve`), `Dockerfile` (Healthcheck)
- Test: `tests/engine/test_scheduler.py`, `tests/test_cli_serve.py`

**Interfaces:**
- Consumes: `run_check` (Task 9), `deliver_due` (Task 8), `make_engine`/`migrate`/`make_session_factory` (Task 2), `build_adapters` (Task 3–6), `create_app` (Task 11 – bis dahin eine minimale Flask-App mit nur `/healthz`).
- Produces:
  - `class Scheduler`: `__init__(session_factory, adapters: Mapping[Platform, Adapter], now=lambda: datetime.now(UTC), tick_s: float = 5.0)`; `tick() -> None`: alle aktiven Suchen mit `next_check_at is None or next_check_at <= now()`, sortiert nach `next_check_at` (None zuerst), je genau ein `run_check`; Exceptions pro Suche loggen und mit der nächsten weitermachen; danach `deliver_due`. `start() -> threading.Thread` (Daemon, ruft `tick` alle `tick_s`, Exceptions werden geloggt, die Schleife läuft weiter). `check_now(search_id) -> None` setzt `next_check_at = now()`.
  - `sniper serve`: `Settings.from_env()`, `migrate`, Adapter bauen (eBay-Zugangsdaten: Umgebungsvariablen vor DB-Setting `ebay_client_id`/`ebay_client_secret`), Scheduler starten, `waitress.serve(app, host="0.0.0.0", port=settings.port, threads=4)`. Beim Start eine Zeile loggen, ob der Passwortschutz aktiv ist (Text wie im Dashboard).
  - `GET /healthz` → 200 `"ok"`, ohne Anmeldung. Dockerfile-`HEALTHCHECK` ruft es per `python -c` auf.

- [ ] **Step 1: Write the failing tests**
  - `test_tick_runs_due_searches_once`: drei Suchen, `next_check_at` alle 3 Tage in der Vergangenheit (Review Focus 4) → jede genau einmal `run_check`, danach liegt `next_check_at` in der Zukunft; zweiter `tick` mit gleichem `now` → keine Checks.
  - `test_paused_searches_are_skipped`.
  - `test_one_failing_search_does_not_stop_others`: Fake-Adapter wirft `RuntimeError` für Suche 1 → Suche 2 wird trotzdem geprüft.
  - `test_tick_delivers_outbox`.
  - `test_healthz` (Flask-Testclient).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** → PASS; `sniper serve` lokal mit `DATA_DIR=$(mktemp -d)` starten → `curl localhost:8095/healthz` liefert `ok`; mit Docker zusätzlich `docker run -p 8095:8095 sniper` → Container wird „healthy“.
- [ ] **Step 5: Commit** `Add scheduler and serve command`

---

### Task 11: Weboberfläche mit optionalem Login

**Files:**
- Create: `src/sniper/web/__init__.py`, `src/sniper/web/auth.py`, `src/sniper/web/views.py`, `src/sniper/web/templates/{base,searches,search_form,hits,targets,settings,login}.html`, `src/sniper/web/static/style.css`
- Test: `tests/web/test_searches.py`, `tests/web/test_targets.py`, `tests/web/test_settings.py`, `tests/web/test_auth.py`

**Interfaces:**
- Consumes: alles Vorherige; `Scheduler.check_now`, `adapter_for_url`, `quota.*`, `sender.send`.
- Produces: `create_app(settings: Settings, session_factory, adapters, scheduler) -> Flask`.
- Routen (serverseitig gerendert, Navigation „Suchen | Treffer | Benachrichtigungen | Einstellungen“, am iPhone bedienbar):
  - `GET /` → Redirect `/suchen`.
  - `GET /suchen`: Tabelle Plattform, Name, Takt, letzter Check, Zustand (`SearchState.label`, Geblockt/Fehler/Seite unbekannt farbig), letzter Treffer; oben Eingabefeld „Such-URL einfügen“.
  - `POST /suchen/neu` (Feld `url`): `adapter_for_url` + `parse_url`; `InvalidUrl` → Fehlermeldung über dem Feld. Sonst Formular `search_form.html` mit Name (vorbelegt aus `q`/Pfad), Takt in Minuten (Standard 5, min 2), Höchstpreis, Ausschlusswörter (Textarea), Stille-Frist in Tagen (Standard 7), Ziele (Checkboxen), Hinweis `"Wird ignoriert: …"` bei `spec.ignored`, und **Vorschau**: einmal `adapter.fetch` → Liste mit Foto/Titel/Preis (ohne Meldung, ohne Speichern); Fehler der Vorschau werden als Text angezeigt, blockieren das Speichern aber nicht.
  - `POST /suchen`: anlegen (`next_check_at = now`). eBay: wenn `quota.projected_daily_calls` aller aktiven eBay-Suchen inkl. dieser > 4500 → Formular erneut mit Fehler `"Zu viele eBay-Abfragen: hochgerechnet {n} pro Tag, erlaubt sind 4500. Takt erhöhen."`. eBay ohne Zugangsdaten → Fehler `"Erst eBay-Zugangsdaten in den Einstellungen eintragen."`.
  - `GET/POST /suchen/<id>`: bearbeiten; geänderte URL → neu parsen, `last_ok_at = None` (beginnt von vorn), alte `Seen` dieser Suche löschen.
  - `POST /suchen/<id>/pausieren`, `/fortsetzen` (setzt `state = pending`, `next_check_at = now`), `/loeschen`, `/pruefen` (`scheduler.check_now`).
  - `GET /treffer`: die letzten 100 `Seen` mit Status ≠ `seeded`, neueste zuerst: Foto, Titel (Link), Preis, Plattform, Suche, Status („gemeldet“ / „verworfen: {reason}“). Darunter Outbox-Einträge mit `failed_at` als „nicht zugestellt“.
  - `GET/POST /benachrichtigungen`: Ziele anlegen (Name, Apprise-URL, „bekommt Statusmeldungen“), Liste mit maskierter URL (Schema + `…` + letzte 4 Zeichen), `POST /benachrichtigungen/<id>/test` (direkt `sender.send` mit `Message("Sniper: Test", "Wenn du das liest, klappt die Benachrichtigung.")`, Ergebnis als Hinweis), `POST /benachrichtigungen/<id>/loeschen`.
  - `GET/POST /einstellungen`: eBay-Client-ID und -Secret (Secret nie zurück ins Formular rendern, leeres Feld = unverändert), Anzeige „eBay-Abfragen heute: {n} von 5000“; sind die Zugangsdaten per Umgebungsvariable gesetzt, Felder deaktiviert mit Hinweis.
  - Login (`auth.py`) nur wenn `APP_PASSWORD` gesetzt: `GET/POST /login` (Benutzer `APP_USER`), Flask-Session-Cookie signiert mit Schlüssel aus `DATA_DIR/session-secret` (bei Fehlen 32 Byte zufällig erzeugen, Dateirechte 0600), gültig 90 Tage; Vergleich mit `hmac.compare_digest`; 5 Fehlversuche je IP in 5 min → 429 bis das Fenster abläuft. `/healthz` und `/static` ohne Login.
  - Alle POST-Formulare mit CSRF-Token (eigener kleiner Helfer: Token in der Session, Hidden Field, Prüfung in `before_request`).

- [ ] **Step 1: Write the failing tests** (Flask-Testclient, Fake-Adapter, Fake-Scheduler)
  - `test_add_search_flow`: `POST /suchen/neu` mit Kleinanzeigen-URL → 200, enthält Vorschau-Titel; `POST /suchen` → Suche in DB mit `interval_s == 300`, `next_check_at` gesetzt.
  - `test_add_unknown_url_shows_error`: `https://example.com` → Text `"Unbekannte Seite"`.
  - `test_ignored_params_are_shown`.
  - `test_ebay_quota_guard`: drei aktive eBay-Suchen mit 2 min (2160/Tag) + neue mit 2 min → abgelehnt mit Text `"Zu viele eBay-Abfragen"`.
  - `test_ebay_requires_credentials`.
  - `test_url_change_resets_search`: `last_ok_at` → None, `Seen` der Suche gelöscht.
  - `test_pause_resume_delete_check_now`.
  - `test_hits_page_hides_seeded_and_shows_reason`.
  - `test_target_url_is_masked` und `test_target_test_send` (Fake-`send`).
  - `test_settings_secret_not_rendered`.
  - `test_auth_disabled_without_password`; `test_login_required_with_password`; `test_login_lockout_after_five_failures`; `test_healthz_without_login`.
  - `test_post_without_csrf_rejected`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Schlichtes CSS, ein Spaltenlayout unter 700 px, Tap-Ziele ≥ 44 px.
- [ ] **Step 4: Run** → PASS; zusätzlich im Browser gegen `docker run` prüfen: Suche anlegen, Ziel testen, Seiten am Handy-Viewport (375 px) ansehen.
- [ ] **Step 5: Commit** `Add web interface with optional login`

---

### Task 12: Echte Probes einspielen, README

Braucht Leon: Er führt im Homelab für je eine Beispielsuche pro Plattform
`docker run --rm -v ./probes:/data/probes ghcr.io/mysquat516/marktplatz-sniper probe "<URL>"` aus
(Kleinanzeigen und willhaben je einmal mit der Original-URL und einmal mit der vom Adapter
normalisierten URL aus `parse_url`) und gibt die Dateien weiter. eBay braucht keine Probe
(dokumentierte API), aber einen Testlauf mit echten Zugangsdaten.

**Files:**
- Create: `tests/fixtures/kleinanzeigen/real-*.html`, `tests/fixtures/willhaben/real-*.html`, `README.md`
- Modify: `src/sniper/platforms/kleinanzeigen.py` (`SELECTORS`, Sortier-Umschreibung), `src/sniper/platforms/willhaben.py` (`RESULT_PATH`, Attributnamen, Sortierung)
- Test: `tests/platforms/test_kleinanzeigen.py`, `tests/platforms/test_willhaben.py`

- [ ] **Step 1: Write the failing tests** gegen die echten Dateien: Anzahl Listings > 0; jedes Listing hat `external_id`, Titel, absolute URL; mindestens ein Preis ist nicht None; mindestens ein `posted_at` ist gesetzt; die normalisierte URL liefert Anzeigen in absteigender Einstellzeit (`posted_at` nicht aufsteigend, `None` ignoriert).
- [ ] **Step 2: Run** → FAIL (wo Kandidaten-Selektoren oder -Parameter nicht stimmen).
- [ ] **Step 3: Selektoren, Pfade und Sortierparameter anpassen**, bis die echten und die synthetischen Fixtures grün sind. Synthetische Fixtures an die echte Struktur angleichen.
- [ ] **Step 4: README schreiben** (deutsch): Was der Sniper tut; Start mit `docker compose pull && docker compose up -d`; `docker login ghcr.io` bei privatem Paket (wie im Dashboard beschrieben); Umgebungsvariablen (`PORT`, `APP_PASSWORD`, `APP_USER`, `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `TZ`); eBay-Developer-Account Schritt für Schritt inklusive Produktiv-Keyset und Befreiung von den „Marketplace Account Deletion“-Benachrichtigungen (Begründung: speichert keine eBay-Nutzerdaten); Beispiele für Apprise-URLs (Telegram, Discord, ntfy, Home Assistant) mit Link auf die Apprise-Wiki; Probe-Kommando für die Fehlersuche; Hinweis, dass Kleinanzeigen bei zu kurzem Takt blocken kann.
- [ ] **Step 5: Run** `uv run pytest -q && uv run ruff check . && uv run ruff format --check .` → grün. Danach mit Leon einen echten Durchlauf im Homelab: je Plattform eine Suche anlegen, Vorschau zeigt Anzeigen, Test-Benachrichtigung kommt an.
- [ ] **Step 6: Commit** `Verify adapters against real pages and add README`
