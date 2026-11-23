# Marktplatz-Sniper

Beobachtet ein paar Suchen auf **eBay**, **Kleinanzeigen** und **willhaben** und schickt neue
Anzeigen mit Foto, Preis und Link aufs Handy. Gedacht als Ergänzung zum
[vinted-bot](https://github.com/jasp-nerd/vinted-bot): Vinted prüft der vinted-bot sehr oft,
die übrigen Plattformen prüft der Sniper in ruhigerem Takt (Standard: alle 5 Minuten).

> **Hinweis:** Diese App wurde mit Hilfe von KI (Claude von Anthropic) entwickelt.
> Idee und Anforderungen kommen vom Projektinhaber, der Code wurde KI-gestützt geschrieben.

## So funktioniert's

1. Auf der Plattform selbst eine Suche einstellen (Suchbegriff, Preis, Größe, Zustand, Umkreis …).
2. Die URL der Ergebnisseite im Sniper einfügen. Der Sniper zeigt eine Vorschau der aktuellen
   Treffer. Dazu kommen Name, Takt, optional Höchstpreis und Ausschlusswörter.
3. Beim ersten Check merkt sich die Suche die aktuelle Seite, ohne etwas zu melden. Danach meldet sie
   jede neue Anzeige, höchstens 10 pro Check. Gibt es mehr, kommt eine Sammelmeldung.

Anzeigen, die älter als 24 Stunden sind (z. B. nach einer Preissenkung hochgerutscht), werden verworfen.
Ebenso TOP-Anzeigen bei Kleinanzeigen. Was verworfen wurde und warum, steht unter **Treffer**.

Wenn etwas nicht klappt, sagt der Sniper Bescheid, statt still zu bleiben. Das betrifft eine Seite,
die blockt, eine Seite, die ihren Aufbau geändert hat, und eine Suche, die 7 Tage lang nichts gefunden hat.

## Starten mit Docker

GitHub baut bei jedem Push auf `main` ein fertiges Image (`amd64` und `arm64`):
`ghcr.io/mysquat516/marktplatz-sniper:latest`. Auf dem Server reicht die `docker-compose.yml`
aus diesem Repo:

```bash
docker compose pull      # neues Image holen
docker compose up -d     # starten bzw. neu starten
```

Danach ist die Oberfläche unter `http://<server>:8092` erreichbar.

**Privates Paket:** Wenn das Repo privat ist, muss sich der Server einmal anmelden:

```bash
docker login ghcr.io -u <github-benutzername>
```

Als Passwort dient ein *Personal Access Token (classic)* mit dem Recht `read:packages`
(GitHub → Settings → Developer settings → Personal access tokens).

### Umgebungsvariablen

| Variable | Standard | Wofür |
|---|---|---|
| `PORT` | `8095` | Port im Container (der Host-Port steht in der `docker-compose.yml`) |
| `APP_PASSWORD` | leer | schaltet den Passwortschutz ein (ohne: nur im Heimnetz/VPN betreiben) |
| `APP_USER` | `admin` | Benutzername für den Login |
| `EBAY_CLIENT_ID` / `EBAY_CLIENT_SECRET` | leer | eBay-Zugangsdaten. Alternativ in der Oberfläche unter *Einstellungen* eintragen |
| `TZ` | `Europe/Berlin` | Zeitzone für Logs |

Alle Daten (Datenbank `sniper.db`, Probe-Dateien) liegen im Volume `./data`.

## Benachrichtigungen

Der Sniper verschickt Meldungen über [Apprise](https://github.com/caronc/apprise) und kann damit
über 100 Dienste bedienen. Unter **Benachrichtigungen** legst du ein Ziel mit einer Apprise-Adresse an
und schickst eine Test-Nachricht. Beispiele:

| Dienst | Adresse |
|---|---|
| Telegram | `tgram://BOT_TOKEN/CHAT_ID` |
| Discord | `discord://WEBHOOK_ID/WEBHOOK_TOKEN` |
| ntfy | `ntfy://THEMA` oder `ntfys://ntfy.example.com/THEMA` |
| Home Assistant | `hassio://HOST/LONG_LIVED_TOKEN` |

Alle Dienste und Formate stehen im [Apprise-Wiki](https://github.com/caronc/apprise/wiki).
Pro Suche wählst du, an welche Ziele sie meldet. Ziele mit **„bekommt Statusmeldungen“** erfahren
außerdem, wenn eine Suche geblockt wird, kaputtgeht oder still ist.

## eBay einrichten

eBay läuft über die offizielle Browse API und braucht deshalb kostenlose Zugangsdaten:

1. Auf [developer.ebay.com](https://developer.ebay.com) mit dem eBay-Konto beim Developers Program anmelden.
2. Eine Anwendung anlegen und ein **Production**-Keyset erzeugen.
3. Der Keyset ist erst aktiv, wenn die Frage nach den **„Marketplace Account Deletion“-Benachrichtigungen**
   beantwortet ist. Dort die **Befreiung (Exemption)** wählen. Begründung: Der Sniper speichert keine
   eBay-Nutzerdaten, nur Titel, Preis, Ort, Fotos und Link der Anzeigen.
4. **App ID (Client ID)** und **Cert ID (Client Secret)** des Production-Keysets kopieren und unter
   *Einstellungen* eintragen (oder als Umgebungsvariablen setzen).

Das Standardlimit liegt bei 5.000 Abfragen am Tag. Der Sniper zählt mit und lässt keine Einstellungen zu,
die hochgerechnet über 4.500 am Tag kämen. Drei eBay-Suchen alle 5 Minuten sind etwa 860 Abfragen am Tag.

## Wenn eine Seite nicht mehr erkannt wird

Kleinanzeigen und willhaben haben keine offizielle Schnittstelle. Ändern sie ihre Seiten, meldet der
Sniper „Seite unbekannt“. Dann hilft eine Probe, also eine einmal gespeicherte echte Antwort:

```bash
docker exec marktplatz-sniper sniper probe "https://www.kleinanzeigen.de/s-jacke/k0"
```

Die Dateien landen unter `./data/probes/`. Damit lässt sich der Parser anpassen.

**Kleinanzeigen und Blocks:** Kleinanzeigen sitzt hinter Cloudflare. Von einem normalen
Internetanschluss aus klappt ein ruhiger Takt meist. Bei zu kurzen Takten oder aus einem Rechenzentrum
wird geblockt. Bei einem Block fragt der Sniper automatisch seltener ab, höchstens bis alle 60 Minuten,
und meldet sich wieder, sobald es läuft.

## Entwickeln

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
DATA_DIR=./data uv run sniper serve
```

Aufbau: `src/sniper/platforms/` (eBay, Kleinanzeigen, willhaben), `engine/` (Neu-Erkennung, Checks,
Planer), `notify/` (Texte, Apprise, Outbox), `web/` (Oberfläche). Design und Plan stehen unter
`docs/superpowers/`.
