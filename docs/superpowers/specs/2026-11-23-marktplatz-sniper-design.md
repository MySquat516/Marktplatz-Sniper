# Marktplatz-Sniper – Design

Stand: 23.11.2026 · Status: Entwurf zur Freigabe

## 1. Worum es geht

Leon resellt nebenbei. Vinted deckt er mit dem vinted-bot (jasp-nerd/vinted-bot) ab, der dort
sehr häufig prüft. Der Sniper ist ein **eigener, kleiner Container im Homelab**, der dasselbe für
**eBay, Kleinanzeigen und willhaben** tut: Er beobachtet ein paar Suchen und meldet neue Anzeigen
aufs Handy, damit Leon gute Ware zum Weiterverkaufen früh sieht.

**Erfolg heißt:** Eine neue, passende Anzeige ist wenige Minuten nach dem Einstellen mit Foto,
Preis und Link auf dem Handy. Wenn eine Seite blockt oder eine Suche kaputtgeht, erfährt Leon das,
statt dass der Sniper still bleibt.

## 2. Ziele, Nicht-Ziele, Anti-Ziele

**Ziele (v1)**
- Drei Plattformen: eBay (DE), Kleinanzeigen, willhaben (AT).
- Pro Plattform ca. 2–3 Suchen, insgesamt also unter 10.
- Ruhiger Takt: Standard alle 5 Minuten pro Suche, einstellbar, Minimum 2 Minuten.
- Kleine Weboberfläche zum Einrichten. Eine Suche wird angelegt, indem man die Such-URL der
  Plattform einfügt.
- Pro Suche: Name, Takt, optional Höchstpreis und Ausschlusswörter.
- Benachrichtigungen über Apprise an beliebige Dienste (Telegram, Discord, ntfy, Pushover,
  E-Mail, Home Assistant …), pro Suche wählbar.
- Ehrliche Statusanzeige pro Suche, plus Warnmeldung bei Block und bei verdächtiger Stille.
- Eigenes Docker-Image (amd64 + arm64), gebaut von GitHub Actions wie beim Reseller-Dashboard.

**Nicht-Ziele (v1)**
- Vinted (bleibt beim vinted-bot).
- Automatisch kaufen, Nachrichten an Verkäufer schicken, sich bei Plattformen einloggen.
- Bewertung, ob ein Preis ein guter Deal ist.
- Anbindung ans Reseller-Dashboard. Ist als späteres, eigenes Projekt vorgemerkt: eine API, über
  die Treffer automatisch im Dashboard landen. v1 legt dafür nur die Daten passend ab (siehe 5.2).
- Headless-Browser (Playwright o. ä.) gegen Cloudflare. Erst nachrüsten, wenn es wirklich nötig ist.
- Mehrere Benutzer.

**Anti-Ziele (das wäre ein Fehlschlag, auch wenn es technisch läuft)**
- Stilles Versagen: Eine geblockte oder kaputte Suche sieht aus wie „gerade nichts Neues“.
- Flut beim Anlegen: Eine neue Suche meldet die ganze erste Seite.
- Doppelte Meldungen oder verlorene Meldungen nach einem Neustart.
- So oft abfragen, dass Leons Heim-IP bei Kleinanzeigen dauerhaft gesperrt wird.

## 3. Rahmenbedingungen

- **Betrieb:** Docker im Homelab, Heim-IP (Privatanschluss). Zugriff im LAN bzw. per VPN.
- **eBay:** offizielle Browse API. Standardlimit 5.000 Aufrufe pro Tag. Für den Produktiv-Keyset
  muss man sich von den „Marketplace Account Deletion“-Benachrichtigungen befreien lassen
  (Ausnahme, weil keine eBay-Nutzerdaten gespeichert werden). Daraus folgt: **Der Sniper speichert
  keine Verkäuferdaten von eBay.**
- **Kleinanzeigen:** keine API, Cloudflare vor jeder Seite. Rechenzentrums-IPs werden geblockt,
  Privatanschlüsse bei ruhigem Takt meist nicht. Anfragen mit Browser-TLS-Fingerabdruck
  (`curl_cffi`, `impersonate="chrome"`).
- **willhaben:** Next.js-Seite. Die Suchergebnisse stecken als JSON im `__NEXT_DATA__`-Block der
  Seite, ein reiner HTTP-Abruf reicht. Rein österreichischer Marktplatz.
- **Entwicklung:** Die Cloud-Umgebung, in der Claude baut, erreicht eBay, Kleinanzeigen und
  willhaben nicht. Echte Antworten für Tests kommen deshalb über ein kleines Probe-Kommando,
  das Leon einmal im Homelab ausführt (siehe 5.8).
- **Leons Vorwissen:** Python mit Flask, SQLAlchemy und Alembic. Der Code soll für ihn lesbar und
  selbst anpassbar bleiben: lieber einfach als clever.
- **Lizenz:** Ideen aus dem vinted-bot (MIT) dürfen übernommen werden, z. B. die Outbox und die
  Logik für die Erkennung neuer Anzeigen.

## 4. Ansätze

| | Ansatz | Vorteil | Nachteil |
|---|---|---|---|
| **A** | **Python + Flask + SQLite** | Apprise läuft direkt (Python), `curl_cffi` für Kleinanzeigen, Ideen aus dem vinted-bot übertragbar, Leon kennt Flask | Anderer Stack als das Dashboard (Node) |
| B | Node/Express wie das Reseller-Dashboard | Gleicher Stack und gleicher Docker-Workflow | Apprise nur als Extra-Container, schwächere Werkzeuge gegen Cloudflare |
| C | Fertiges Tool (changedetection.io) | In einer Stunde eingerichtet | Meldet nur Seitenänderungen als Text-Diff, keine einzelnen Anzeigen mit Foto und Preis, keine eBay-API |

**Gewählt: A** (Leons Entscheidung). Die zwei schwierigsten Teile, also Kleinanzeigen und die
Benachrichtigungen, sind damit am einfachsten. Für die spätere Dashboard-API spielt die Sprache
keine Rolle, weil sie über HTTP läuft.

## 5. Aufbau

### 5.1 Komponenten

```
Weboberfläche (Flask + Jinja)  ──┐
                                 ├── SQLite (SQLAlchemy, Alembic)
Planer (ein Hintergrund-Thread) ─┤
   └─ Plattform-Adapter          │
        eBay · Kleinanzeigen · willhaben
   └─ Filter + Neu-Erkennung     │
   └─ Outbox ── Versand (Apprise)┘
```

- **Ein Prozess, ein Planer-Thread.** Der Webserver läuft mit genau einem Prozess (z. B. waitress),
  damit der Planer nie doppelt startet.
- **Plattform-Adapter** mit gleicher Schnittstelle:
  - `parse_url(url) -> SearchSpec` prüft und übersetzt die eingefügte URL, erzwingt die Sortierung
    „neueste zuerst“ und liefert Hinweise auf ignorierte Filter.
  - `fetch(spec) -> list[Listing]` lädt die erste Ergebnisseite und gibt einheitliche Anzeigen zurück.
  - Bei Fehlern wirft er unterscheidbare Fehler: `Blocked`, `RateLimited`, `LayoutChanged`
    (Seite geladen, aber nichts erkennbar), `Network`.

### 5.2 Einheitliche Anzeige (`Listing`)

Dieses Format ist auch die Grundlage für die spätere Dashboard-API.

| Feld | Bedeutung |
|---|---|
| `platform` | `ebay` / `kleinanzeigen` / `willhaben` |
| `external_id` | ID der Plattform, als Text |
| `title` | Titel |
| `price`, `currency` | Preis als Dezimalzahl, `None` bei „Zu verschenken“ oder ohne Preis |
| `negotiable` | „VB“ |
| `listing_type` | `fixed` / `auction` |
| `shipping` | Versand möglich: ja / nein / unbekannt; `shipping_cost` falls bekannt |
| `url` | Link zur Anzeige |
| `photo_urls` | Fotos, Titelbild zuerst |
| `location` | Ort bzw. PLZ, falls angegeben |
| `posted_at` | Einstellzeit, falls die Plattform sie liefert |

Keine Verkäuferdaten (siehe eBay-Ausnahme). Rohdaten werden nicht dauerhaft gespeichert.

### 5.3 Daten (SQLite unter `/data`)

- `searches`: Name, Plattform, Original-URL, übersetzte Parameter, Takt, Höchstpreis,
  Ausschlusswörter, aktiv/pausiert, Zustand, letzter Check, letzter Erfolg, letzter Fehler,
  letzte neue Anzeige.
- `seen`: (Suche, Plattform, external_id) → erstes Sehen, Ergebnis `seeded` / `matched` /
  `rejected` + Grund, Anzeige als JSON. Liefert auch die Trefferliste in der Oberfläche.
- `targets`: Benachrichtigungsziele (Name, Apprise-URL, „bekommt Statusmeldungen“).
- `search_targets`: welche Suche an welche Ziele meldet.
- `outbox`: zu sendende Meldungen (Ziel, Inhalt, Versuche, nächster Versuch, gesendet am, Fehler).
- `settings`: eBay-Zugangsdaten, eBay-Aufrufzähler pro Tag.

### 5.4 Neu-Erkennung und Filter

1. **Erster Check einer Suche:** Alles auf der Seite wird still als `seeded` gemerkt, nichts wird
   gemeldet.
2. **Danach:** Eine Anzeige ist neu, wenn diese Suche sie noch nie gesehen hat.
3. **Frischefenster:** Wenn `posted_at` bekannt ist und älter als 24 Stunden, wird die Anzeige als
   „zu alt“ verworfen. Das betrifft z. B. alte Anzeigen, die durch eine Preissenkung oder ein
   Hochschieben plötzlich auftauchen.
4. **Filter:** Höchstpreis (vergleicht den Artikelpreis ohne Versand; Anzeigen ohne Preis
   kommen durch) und Ausschlusswörter (Titel, ohne Groß-/Kleinschreibung).
5. **Deckel:** höchstens 10 Meldungen pro Check. Gibt es mehr, kommt eine Sammelmeldung
   „… und N weitere“ mit Link zur Suche. Das schützt z. B. nach einer längeren Pause.
6. Verworfene Anzeigen landen mit Grund in der Trefferliste. So sieht man, ob ein Filter zu scharf ist.
7. Wird die URL einer Suche geändert, beginnt sie von vorn: Der nächste Check gilt wieder als
   erster Check. Änderungen an Name, Takt oder Filtern setzen nichts zurück.

### 5.5 Takt und Rücksicht

- Pro Suche fester Takt (Standard 5 min, Minimum 2 min) mit ±20 % Zufall, damit es nicht
  maschinell aussieht.
- Pro Plattform mindestens 10 s Abstand zwischen zwei Anfragen. Es wird immer nur die erste Seite
  geladen.
- **eBay-Kontingent:** Der Zähler läuft pro Tag mit. Die Oberfläche verhindert Einstellungen, die
  hochgerechnet über 4.500 Aufrufe pro Tag kämen. Beispiel: 3 eBay-Suchen alle 5 min ≈ 860 pro Tag.
  Das App-Token (Client-Credentials, ca. 2 h gültig) wird zwischengespeichert.

### 5.6 Zustände, Fehler, Warnungen

Zustand pro Suche: **OK**, **Fehler**, **Geblockt**, **Seite unbekannt** (Layout geändert),
**Pausiert**.

- Bei 403/429/503 oder Cloudflare-Challenge wechselt die Suche auf **Geblockt**. Der Takt
  verdoppelt sich bis maximal 60 min. Nach dem ersten erfolgreichen Abruf gilt wieder der normale Takt.
- **Statusmeldung** über Apprise an alle Ziele mit „bekommt Statusmeldungen“: einmal beim Wechsel
  in Geblockt / Seite unbekannt / Fehler (nach 3 Fehlschlägen am Stück) und einmal, wenn es wieder
  läuft. Keine Wiederholungen dazwischen.
- **Stille-Warnung:** Hat eine Suche seit 7 Tagen keine neue Anzeige gemeldet, kommt eine Meldung,
  und zwar nur einmal, bis wieder etwas gemeldet wurde. Die Frist ist pro Suche einstellbar, 0 = aus.

### 5.7 Plattform-Details

**eBay (Browse API, `item_summary/search`)**
- Header `X-EBAY-C-MARKETPLACE-ID: EBAY_DE`, `sort=newlyListed`, `limit=50`.
- Übersetzung der eingefügten ebay.de-URL:
  `_nkw` → `q`, `_sacat` → `category_ids`, `_udlo`/`_udhi` → `filter=price:[..],priceCurrency:EUR`,
  `LH_ItemCondition` → `conditionIds`, `LH_BIN`/`LH_Auction` → `buyingOptions`,
  `LH_PrefLoc=1` → `itemLocationCountry:DE`. Andere Parameter werden ignoriert und beim Anlegen
  als „wird ignoriert: …“ angezeigt.
- `posted_at` aus `itemCreationDate`.
- Zugangsdaten (Client-ID und Secret) in den Einstellungen oder per Umgebungsvariable. Ohne
  Zugangsdaten lassen sich keine eBay-Suchen anlegen, und die Oberfläche erklärt, warum.

**Kleinanzeigen**
- Abruf der Suchseite mit `curl_cffi` (Chrome-Fingerabdruck), Sitzungs-Cookies bleiben erhalten.
- Die URL wird auf „Neueste zuerst“ umgeschrieben, falls nötig.
- Aus der Ergebnisliste gelesen werden ID, Titel, Preis inkl. „VB“ / „Zu verschenken“, Ort,
  Versand ja/nein, Bild und Zeit („Heute, 07:12“ / „Gestern“ / Datum → `posted_at`, gelesen in
  Europe/Berlin).
- Anzeigen von Gewerblichen bzw. „Top-Anzeigen“, die nicht chronologisch sind, sollen die
  Neu-Erkennung nicht stören. Das deckt die Prüfung „diese Suche hat sie noch nie gesehen“ plus
  das Frischefenster ab.
- Eine Cloudflare-Challenge-Seite wird als `Blocked` erkannt, nicht als „0 Treffer“.

**willhaben**
- Abruf der Suchseite (`curl_cffi`), JSON aus `<script id="__NEXT_DATA__">` lesen.
- Sortierung „neueste zuerst“ erzwingen.
- `posted_at` aus dem Veröffentlichungsdatum der Anzeige.

Die genauen Selektoren, Feldnamen und Sortierparameter legt der Builder anhand echter Antworten
fest (siehe 5.8).

### 5.8 Probe-Kommando

`docker exec sniper sniper probe <URL>` ruft die URL genau einmal ab und speichert die rohe
Antwort plus Header als Datei unter `/data/probes/`. Leon führt das im Homelab für je eine
Beispielsuche pro Plattform aus und gibt die Dateien weiter. Sie werden zu Test-Fixtures. Das
Kommando hilft später auch bei der Fehlersuche, wenn eine Seite ihren Aufbau ändert.

### 5.9 Benachrichtigungen

- Apprise als Python-Bibliothek. Ziele werden als Apprise-URL eingetragen (`tgram://…`,
  `discord://…`, `ntfy://…`, `hassio://…` usw.). In der Oberfläche werden sie maskiert angezeigt
  und haben einen „Test senden“-Knopf.
- **Meldung zu einer Anzeige:**
  - Titel: `[Kleinanzeigen] Jacke Gr. L – 45 € VB`
  - Text: Titel der Anzeige, Preis (+ Versand, falls bekannt), Ort, „eingestellt vor 4 min“, Name
    der Suche, Link.
  - Titelbild als Anhang, falls der Dienst das kann.
- **Outbox:** Jede Meldung wird erst gespeichert, dann gesendet. Nach einem Absturz geht nichts
  verloren und nichts wird doppelt geschickt. Bei Fehlschlag gibt es Wiederholungen nach 1, 5, 15
  und 60 min. Nach 24 h gibt der Sniper auf, und die Meldung ist in der Oberfläche als
  „nicht zugestellt“ sichtbar.

### 5.10 Weboberfläche

Serverseitig gerendert (Flask + Jinja), wenig JavaScript, deutsch, am iPhone gut bedienbar.

```
Sniper                                   [Suchen] [Treffer] [Benachr.] [Einst.]
──────────────────────────────────────────────────────────────────
[ Such-URL von eBay, Kleinanzeigen oder willhaben einfügen…  ] [+]

eBay        Jacke Gr. L      5 min   07:18  OK          neu: heute 06:52
Kleinanz.   Sneaker 43       5 min   07:16  GEBLOCKT    seit 06:40
willhaben   Hoodie           –       –      Pausiert
```

- **Suchen:** Liste mit Zustand. URL einfügen → Formular (Name, Takt, Höchstpreis,
  Ausschlusswörter, Ziele, Stille-Frist) mit **Vorschau**: einmal abrufen und zeigen, was gefunden
  würde, ohne Meldung. Bearbeiten, pausieren, löschen, „jetzt prüfen“.
- **Treffer:** die letzten Anzeigen aller Suchen mit Foto, Preis und Status (gemeldet / verworfen +
  Grund / nicht zugestellt).
- **Benachrichtigungen:** Ziele anlegen, testen, „bekommt Statusmeldungen“ an/aus.
- **Einstellungen:** eBay-Zugangsdaten, eBay-Kontingent heute.
- Optionaler Passwortschutz über `APP_PASSWORD`, wie beim Reseller-Dashboard.
- `/healthz` für den Docker-Healthcheck.

### 5.11 Betrieb

- Image `ghcr.io/mysquat516/marktplatz-sniper` (amd64 + arm64), gebaut per GitHub Actions bei Push
  auf `main`, mit Tags `latest` und `sha-<commit>`, wie beim Dashboard.
- `python:3.12-slim`, läuft als Nicht-Root, Volume `./data:/data` (Datenbank + Probes),
  Port 8095, `TZ=Europe/Berlin`.
- `docker-compose.yml` und eine README auf Deutsch, inklusive Anleitung für den eBay-Developer-
  Account samt Befreiung von den Account-Deletion-Benachrichtigungen.
- Datenbank-Migrationen mit Alembic laufen beim Start automatisch.

### 5.12 Tests

- pytest. Adapter werden gegen gespeicherte Fixtures getestet (aus 5.8), inklusive
  Cloudflare-Challenge-Seite und leerer Ergebnisseite.
- Unit-Tests für: URL-Übersetzung (v. a. eBay), Neu-Erkennung (erster Check, Frischefenster,
  Deckel), Filter, Zustandswechsel + Statusmeldungen, Outbox (Absturz zwischen Speichern und
  Senden, Wiederholungen), eBay-Kontingent.
- CI auf GitHub: Tests + Linting (ruff) bei jedem Push.

## 6. Dem Builder überlassen

- Aussehen und CSS der Oberfläche (schlicht, gut lesbar am Handy).
- Genaue Selektoren und Feldnamen pro Plattform, anhand der Probes.
- Struktur der Module, Name des Webservers (Hauptsache ein Prozess), Logging-Format.
- Ob die Planer-Schleife selbst geschrieben ist oder eine kleine Bibliothek nutzt.

## 7. Später (nicht v1)

- **API zum Reseller-Dashboard:** Treffer per Knopfdruck oder automatisch als Artikel (Status
  „Lager“) im Dashboard anlegen. Baut auf dem `Listing`-Format aus 5.2 auf.
- Headless-Browser als Notlösung für Kleinanzeigen, falls `curl_cffi` dauerhaft geblockt wird.
- Weitere Plattformen.
