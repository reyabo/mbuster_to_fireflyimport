# mbuster_to_fireflyimport

Konvertiert Exportdateien der App **MoneyBuster** (bzw. Nextcloud **Cospend**)
in **Firefly III**-Transaktionen. Die Umwandlung übernimmt Datums- und
Betragsformatierung, Vorzeichen, das Auflösen von Kategorie-IDs sowie das
Feld-Mapping zwischen beiden Tools – damit Transaktionen ohne manuelle
Nacharbeit in Firefly III landen.

Es gibt eine kleine **Web-Oberfläche** (FastAPI). Sie ist für den Betrieb in
einem **Homelab hinter Tailscale** gedacht: Datei hochladen → Vorschau →
**direkter Upload per Firefly-III-API**. Alternativ lässt sich eine
importfertige **CSV + `config.json`** für den Firefly III Data Importer
herunterladen.

---

## Funktionsweise / Mapping

Jede MoneyBuster-„Rechnung" (Bill) wird zu **einer** Firefly-III-Transaktion:

| MoneyBuster / Cospend        | Firefly III                                   |
|------------------------------|-----------------------------------------------|
| `amount` > 0                 | **withdrawal** (Ausgabe)                       |
| `amount` < 0                 | **deposit** (Einnahme/Rückzahlung)            |
| `amount`                     | Betrag (Absolutwert, `.` als Dezimaltrennzeichen) |
| `date` / `timestamp`         | Buchungsdatum (normalisiert nach ISO 8601)    |
| `what`                       | Beschreibung                                  |
| `categoryid` → `categoryname`| Firefly-Kategorie (ID wird aufgelöst)         |
| `payer_name`, `owers`        | werden in den Notizen festgehalten            |
| Quelle/Ziel                  | konfigurierbares Asset-/Ausgaben-/Einnahmenkonto |

* **Vorzeichen** lassen sich mit „Vorzeichen umkehren" / `INVERT_SIGN` drehen.
* Für jede Transaktion wird eine stabile `external_id` (`mb-…`) erzeugt, damit
  Firefly Duplikate beim erneuten Import erkennt.
* Die Cospend-Platzhalterzeile `deleteMeIfYouWant` wird automatisch übersprungen.

### Robustes Parsing

* Erkennt englische **und** deutsche Spaltennamen
  (`what`/`Was`, `amount`/`Betrag`, `date`/`Datum`, `payer_name`/`Zahlername`, …).
* Erkennt das Trennzeichen automatisch (`,`, `;`, Tab) und akzeptiert
  `,` oder `.` als Dezimaltrennzeichen.
* Findet den Rechnungs-Abschnitt selbst dann, wenn die Exportdatei zusätzliche
  Abschnitte (Kategorien, Währungen, Mitglieder) enthält.
* **Wichtig:** Es muss die **Rechnungsliste** exportiert werden, nicht die
  **Statistik** (`Mitgliedsname, Gezahlt, Ausgegeben, Saldo`). Die Statistik
  enthält nur Salden, keine Einzelbuchungen – die App weist in dem Fall mit
  einer klaren Meldung darauf hin.

---

## Schnellstart (Docker / Homelab)

```bash
git clone https://github.com/reyabo/mbuster_to_fireflyimport.git
cd mbuster_to_fireflyimport
cp .env.example .env
# .env bearbeiten: FIREFLY_BASE_URL und FIREFLY_TOKEN setzen
docker compose up -d --build
```

Danach im Browser öffnen (siehe Tailscale-Hinweis unten) und die
MoneyBuster-CSV hochladen.

### Firefly-III-Token

In Firefly III unter **Options → Profile → OAuth → Personal Access Tokens**
ein Token erstellen und als `FIREFLY_TOKEN` in die `.env` eintragen.
`FIREFLY_BASE_URL` ist die Basis-URL der Instanz (ohne `/api`).

### Tailscale

Der Container bindet standardmäßig auf `127.0.0.1` (siehe `BIND_ADDR` in
`.env`). Empfohlene Varianten:

* **`tailscale serve`** auf dem Host:
  ```bash
  tailscale serve --bg 8080
  ```
  Dann ist die App nur innerhalb deines Tailnets erreichbar
  (`https://<host>.<tailnet>.ts.net`).
* oder `BIND_ADDR` in der `.env` auf die **Tailscale-IP** (`100.x.y.z`) des
  Hosts setzen.

> Die App bringt **keine eigene Authentifizierung** mit – die Zugriffskontrolle
> übernimmt Tailscale. Niemals ungeschützt im öffentlichen Internet betreiben.

---

## Lokale Entwicklung

```bash
uv venv && source .venv/bin/activate     # oder: python -m venv .venv
uv pip install -r requirements.txt pytest # oder: pip install ...
uvicorn app.main:app --reload --port 8080
pytest
```

---

## Konfiguration

Alle Werte können über Umgebungsvariablen / `.env` gesetzt werden; die
Konvertierungs-Defaults lassen sich zusätzlich pro Upload im Formular
überschreiben. Siehe [`.env.example`](.env.example).

| Variable                  | Bedeutung                                         | Default                |
|---------------------------|---------------------------------------------------|------------------------|
| `FIREFLY_BASE_URL`        | Basis-URL der Firefly-III-Instanz                 | –                      |
| `FIREFLY_TOKEN`           | Personal Access Token                             | –                      |
| `DEFAULT_ASSET_ACCOUNT`   | Konto, von/auf das gebucht wird                   | `MoneyBuster`          |
| `DEFAULT_EXPENSE_ACCOUNT` | Fallback-Ausgabenkonto                            | `MoneyBuster Expenses` |
| `DEFAULT_REVENUE_ACCOUNT` | Fallback-Einnahmenkonto                           | `MoneyBuster Income`   |
| `DEFAULT_CURRENCY`        | Währung (ISO 4217)                                | `EUR`                  |
| `IMPORT_TAG`              | Tag an jeder importierten Transaktion             | `moneybuster`          |
| `INVERT_SIGN`             | Vorzeichen umkehren                               | `false`                |
| `ERROR_IF_DUPLICATE`      | Duplikate von Firefly ablehnen lassen             | `true`                 |
| `APPLY_RULES`             | Firefly-Regeln auf Importe anwenden               | `false`                |
| `BIND_ADDR`               | Interface für den veröffentlichten Port (compose) | `127.0.0.1`            |

---

## Hinweis zum Datenmodell

MoneyBuster/Cospend ist ein Tool zum **Aufteilen** gemeinsamer Ausgaben,
Firefly III ist persönliche Buchhaltung. Dieses Tool importiert pro Rechnung
den **vollen Rechnungsbetrag** (so wie er in der Quelle steht), nicht nur den
eigenen Anteil. Für ein Ein-Personen-Projekt entspricht das genau den eigenen
Ausgaben. Zahler und Schuldner bleiben in den Notizen erhalten. Wer nur den
eigenen Anteil oder ein anderes Mapping braucht, kann das im
`app/transform.py` anpassen.

---

## Endpunkte

| Methode | Pfad               | Zweck                                    |
|---------|--------------------|------------------------------------------|
| `GET`   | `/`                | Upload-Formular                          |
| `POST`  | `/preview`         | Transaktionen anzeigen (kein Import)     |
| `POST`  | `/import`          | Direkt in Firefly III importieren        |
| `POST`  | `/download/csv`    | Firefly-Importer-CSV herunterladen       |
| `POST`  | `/download/config` | passende `config.json` herunterladen     |
| `GET`   | `/healthz`         | Healthcheck                              |
