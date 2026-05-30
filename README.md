# mbuster_to_fireflyimport

Kleiner Docker-Webdienst mit WebUI, der Exporte aus **MoneyBuster** bzw.
**Nextcloud Cospend** einliest, validiert, in ein internes Zwischenformat
überführt und anschließend per **direktem Firefly-III-API-Aufruf** als
Transaktionen anlegt.

> Es wird **nicht** der Firefly III Data Importer verwendet, sondern direkt die
> Firefly-III-API. Keine Bankanbindung, kein externer Dienst, kein Cloud-Zwang.

```
MoneyBuster / Cospend Export
        ↓ Upload (WebUI)
Parsing + Normalisierung (internes Bill-Modell)
        ↓
Preview / Dry-Run  +  Mapping zu Firefly-Konten/Kategorien
        ↓ explizite Bestätigung
direkter Firefly-III-API-Import  +  lokale Dedupe-Historie
```

---

## Zweck

MoneyBuster/Cospend ist ein **Split-Expense-System**, Firefly III eine
persönliche Buchhaltung. Das Tool überführt geteilte Ausgaben so nach Firefly,
dass sie als persönliche Finanzen sinnvoll auswertbar bleiben – mit klar
unterscheidbaren **Importmodi**.

### Importmodi

| Modus | Verhalten | Betrag |
|-------|-----------|--------|
| **Reale Zahlung** (Default) | Nur Rechnungen, die **du** bezahlt hast, werden importiert. | voller gezahlter Betrag |
| **Nur mein Anteil** | Importiert deinen Anteil (auch wenn jemand anderes gezahlt hat – in der Preview markiert). | dein Anteil |
| **Nur Vorschau** | Importiert nie, nur Anzeige. | – |

Hat **eine andere Person** bezahlt (Modus „reale Zahlung"), wird die Zeile
**nicht** automatisch importiert, sondern in der Preview als `other_payer`
markiert (mit Anzeige deines Anteils). Erstattungen/Forderungen werden in v1
bewusst nicht automatisch modelliert.

### Firefly-Abbildung

* **Asset Account** = dein Konto (Quelle), z. B. `Girokonto`
* **Expense Account** = Händler/Gegenkonto (aus Beschreibung erkannt, sonst `MoneyBuster`)
* **Category** = Zweck (aus Keyword-Regeln, sonst Cospend-Kategorie, sonst `Sonstiges`)
* **Tags** = `moneybuster`, Projektname, Teilnehmernamen
* **Notes** = vollständige Split-Infos (Zahler, Anteile, Original-Bill-ID)
* **External ID** = stabiler Dedupe-Key (`moneybuster:projekt:billid` bzw. Hash)

---

## Architektur

```
app/
  main.py            FastAPI-Routen (/, /preview, /import, /rules, /healthz)
  config.py          Settings (.env / ENV / Secret-File)
  models.py          internes Modell: Bill, Participant, ImportProposal (pydantic)
  rules.py           Keyword-Regeln für Kategorie/Gegenkonto
  history.py         SQLite-Dedupe-Historie (/data/import_history.sqlite)
  default_rules.json mitgelieferte Beispielregeln
  parsers/
    base.py          Parser-Interface + Normalisierung (Datum/Betrag/Shares)
    moneybuster_csv.py  CSV-Parser (EN/DE, Mehr-Sektionen, Kategorie-IDs)
    cospend_json.py     JSON-Parser (Member-/Kategorie-Auflösung)
  firefly/
    client.py        async Firefly-III-API-Client (httpx)
    mapper.py        Bill -> ImportProposal (Modi, Shares, Dedupe-Key)
  templates/         Jinja2 (Start, Preview, Ergebnis, Regeln)
tests/               Unit-Tests (Parser, Mapper, History, Firefly gemockt)
```

Neue Exportformate: eine Klasse in `app/parsers/` ergänzen und in
`app/parsers/__init__.py` registrieren.

---

## Sicherheitsmodell

* **Keine eingebaute Authentifizierung** – Zugriffsschutz übernimmt Tailscale
  (+ Caddy). Niemals öffentlich ins Internet stellen.
* Token **niemals** im Code/Image/Compose: nur via `FIREFLY_TOKEN_FILE`
  (Docker-Secret) oder `.env` (gitignored).
* `.env`, `secrets/`, `/data` und `*.sqlite` sind in `.gitignore`.
* Uploads landen **nur** in `<DATA_DIR>/uploads`.
* **Preview vor Import**, Import-Button erst nach Validierung, Dry-Run-Modus.
* Kein Import ohne explizite Auswahl/Bestätigung.
* Dedupe verhindert versehentliche Doppelimporte.

---

## Installation (Homelab)

```bash
git clone https://github.com/reyabo/mbuster_to_fireflyimport.git
cd mbuster_to_fireflyimport

# 1. Konfiguration
cp .env.example .env          # FIREFLY_URL, SELF_NAME, ... anpassen

# 2. Token als Secret ablegen (nicht ins Git!)
mkdir -p secrets
printf '%s' 'DEIN_FIREFLY_PERSONAL_ACCESS_TOKEN' > secrets/firefly_token.txt
chmod 600 secrets/firefly_token.txt

# 3. Starten (Host-Port 8090 -> Container 5000)
docker compose up -d --build
```

### Firefly-Token erzeugen

Firefly III → **Options → Profile → OAuth → Personal Access Tokens** →
*Create new token*. Den Token-String in `secrets/firefly_token.txt` legen.
`FIREFLY_URL` ist die Basis-URL (ohne `/api`).

### Caddy (Reverse Proxy)

```caddy
moneybuster.deubitos.de {
	tls internal
	reverse_proxy host.docker.internal:8090
}
```

### Pi-hole (lokale DNS)

```
moneybuster.deubitos.de → 192.168.0.102
```

Zugriff anschließend nur intern bzw. über Tailscale:
`https://moneybuster.deubitos.de`.

---

## Erster Start / Bedienung

1. **Startseite** öffnen – zeigt den Firefly-Verbindungsstatus und die Anzahl
   Einträge in der lokalen Import-Historie.
2. **Export hochladen**: CSV oder JSON wählen, Exporttyp (`auto` reicht meist),
   eigenen Mitgliedsnamen, Asset-Konto (Dropdown aus Firefly) und Importmodus.
3. **Vorschau / Dry-Run**: Tabelle mit Datum, Titel, Zahler, Gesamtbetrag,
   eigenem Anteil, Importbetrag, Quelle/Ziel, Kategorie, Tags, Dedupe-Key und
   Status (`new`, `other_payer`, `probably_imported`, `skipped`). Es wird
   nichts importiert.
4. **Import**: Haken bei den gewünschten Zeilen setzen und bestätigen. Erst dann
   spricht das Tool die Firefly-API an.
5. **Ergebnis**: Anzahl erstellt / Duplikate / übersprungen / Fehler, Detail je
   Zeile und Link zu Firefly III.

> **Statistik-Export ≠ Rechnungsliste:** Der Statistik-Export
> (`Mitgliedsname, Gezahlt, Ausgegeben, Saldo`) enthält keine Einzelbuchungen.
> Bitte die **Projekt-/Rechnungsliste** exportieren – das Tool erkennt den
> Statistik-Export und weist mit einer klaren Meldung darauf hin.

### Zahlungstyp → Asset-Konto (Quellkonto)

MoneyBuster/Cospend speichert je Buchung einen **Zahlungstyp** (`payment_mode`).
Über `PAYMENT_MODE_ACCOUNT_MAP` (JSON-String) wird daraus das Firefly-**Asset-
Konto** als Quelle der Ausgabe abgeleitet:

```json
{
  "cash": "Bargeld", "bar": "Bargeld", "bargeld": "Bargeld",
  "card": "Girokonto", "karte": "Girokonto", "ec": "Girokonto",
  "creditcard": "Kreditkarte", "kreditkarte": "Kreditkarte",
  "bank": "Girokonto", "überweisung": "Girokonto", "transfer": "Girokonto"
}
```

* Schlüssel sind **case-insensitive**, Whitespace wird getrimmt, Umlaute bleiben
  erhalten; unbekannte/ungültige Werte werden ignoriert.
* **Priorität für das Quellkonto:** (a) Zahlungstyp-Mapping → (b) im Formular
  gewähltes Asset-Konto → (c) `DEFAULT_ASSET_ACCOUNT` → (d) sonst **kein
  Import** (Zeile als `no_source_account` markiert).
* Die Preview zeigt den Zahlungstyp und woher das Quellkonto stammt
  (z. B. „aus Zahlungstyp: Bargeld" bzw. „Fallback aus Formular").

> Hinweis: Der **CSV**-Export nutzt kurze Codes für `paymentmode`
> (z. B. `c`, `n`, `b`, `t`). Diese Codes als Schlüssel ins Mapping aufnehmen,
> z. B. `{"c": "Kreditkarte", "n": "Bargeld"}`.

### Kategorie-Regeln

Beim ersten Start wird `<DATA_DIR>/rules.json` aus den mitgelieferten
Beispielregeln erzeugt. Bearbeitbar als JSON (`contains`-Schlüsselwörter →
Kategorie, optional `destination_account`), Anzeige unter `/rules`.

---

## Backup der Import-Historie

Die Dedupe-Historie liegt in `/data/import_history.sqlite` (im Compose-Setup
unter `/srv/data/moneybuster-converter/`). Sichern z. B. mit:

```bash
sqlite3 /srv/data/moneybuster-converter/import_history.sqlite \
  ".backup '/srv/backup/mbuster_history_$(date +%F).sqlite'"
```

Geht die Historie verloren, greift weiterhin Fireflys eigene
Duplikaterkennung (`error_if_duplicate_hash`) sowie die `external_id`.

---

## Konfiguration (ENV / .env)

| Variable | Bedeutung | Default |
|----------|-----------|---------|
| `FIREFLY_URL` | Basis-URL der Firefly-III-Instanz | – |
| `FIREFLY_TOKEN` | Token (Alternative zum File) | – |
| `FIREFLY_TOKEN_FILE` | Pfad zu einer Token-/Secret-Datei (bevorzugt) | – |
| `DATA_DIR` | Datenverzeichnis (Uploads, History, Rules) | `./data` (`/data` im Container) |
| `SELF_NAME` | eigener MoneyBuster/Cospend-Name | – |
| `DEFAULT_CURRENCY` | Währung (ISO 4217) | `EUR` |
| `DEFAULT_ASSET_ACCOUNT` | Standard-Asset-Konto (Quelle/Ziel), wenn keins gewählt | – |
| `PAYMENT_MODE_ACCOUNT_MAP` | JSON: Zahlungstyp → Firefly-Asset-Konto (siehe unten) | `{}` |
| `IMPORT_TAG` | Tag an jeder Transaktion | `moneybuster` |
| `DEFAULT_EXPENSE_ACCOUNT` | Fallback-Gegenkonto | `MoneyBuster` |
| `DEFAULT_CATEGORY` | Fallback-Kategorie | `Sonstiges` |
| `AUTO_CREATE_EXPENSE_ACCOUNTS` | fehlende Expense Accounts anlegen | `false` |
| `AUTO_CREATE_CATEGORIES` | fehlende Kategorien anlegen | `false` |
| `ERROR_IF_DUPLICATE` | Duplikate von Firefly ablehnen lassen | `true` |
| `APPLY_RULES` | Firefly-Regeln auf Importe anwenden | `false` |

---

## Lokale Entwicklung

```bash
uv venv && source .venv/bin/activate
uv pip install -r requirements.txt pytest
export DATA_DIR=./data
uvicorn app.main:app --reload --port 5000
pytest
```

---

## Grenzen (bewusst nicht in v1)

* kein automatischer Sync mit MoneyBuster, kein direkter Cospend/Nextcloud-API-Zugriff
* keine komplexe Schuldenverwaltung, keine perfekte Abbildung offener Forderungen
* keine Bankdatenverarbeitung, kein Ersatz für den Firefly Data Importer bei Bank-CSV
* Split = Gleichverteilung auf die Owers (gewichtete/individuelle Splits aus dem
  einfachen CSV-Export werden nicht rekonstruiert; in der Preview ausgewiesen)
* **negative Beträge** (Erstattungen/Umbuchungen) werden in der Preview als
  `negative_amount` markiert und **nicht automatisch** importiert
* keine öffentliche Bereitstellung
