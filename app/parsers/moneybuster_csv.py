"""Parser for MoneyBuster / Cospend CSV project exports.

The export is a CSV that may contain several sections separated by blank
lines (bills, categories, currencies, members). Column order and the exact
column set vary between app versions and locales, so the bills section is
detected by its header and columns are mapped by name (English + German).
"""

from __future__ import annotations

import csv
import io
import re

from ..models import Bill, Participant, ParseResult
from .base import (
    BaseParser,
    ParseError,
    decode,
    equal_shares,
    mask,
    normalise_date,
    parse_amount,
    split_names,
)

# normalised header -> canonical field
_COLUMN_ALIASES: dict[str, str] = {
    # title / what
    "what": "what", "name": "what", "title": "what", "description": "what",
    "was": "what", "titel": "what", "beschreibung": "what",
    # amount
    "amount": "amount", "value": "amount", "betrag": "amount",
    # date / timestamp
    "date": "date", "datum": "date",
    "timestamp": "timestamp", "zeitstempel": "timestamp",
    # payer
    "payer_name": "payer", "payer": "payer", "payername": "payer",
    "zahler": "payer", "zahlername": "payer", "bezahltvon": "payer",
    "payer_weight": "payer_weight", "zahlergewicht": "payer_weight",
    # owers
    "owers": "owers", "ower": "owers", "owers_name": "owers",
    "schuldner": "owers", "fuer": "owers", "für": "owers",
    # category (inline name / id)
    "categoryname": "category", "category": "category", "category_name": "category",
    "kategorie": "category", "kategoriename": "category",
    "categoryid": "category_id", "kategorieid": "category_id",
    # payment mode
    "paymentmode": "payment_mode", "paymentmodename": "payment_mode",
    "payment_mode": "payment_mode", "zahlungsmittel": "payment_mode",
    "zahlungsart": "payment_mode",
    # bill id / project
    "id": "bill_id", "billid": "bill_id",
    # comment / currency
    "comment": "comment", "comments": "comment", "kommentar": "comment",
    "currencyname": "currency", "currency": "currency",
    "waehrung": "currency", "währung": "currency",
}

_STATS_MARKERS = {
    "mitgliedsname", "membername", "saldo", "balance",
    "gezahlt", "paid", "ausgegeben", "spent",
}

_SENTINEL_TITLE = "deleteMeIfYouWant"


def _normalise(header: str) -> str:
    return re.sub(r"\s+", "", header.strip().lower())


def _split_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines():
        if line.strip() == "":
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _detect_delimiter(sample: str) -> str:
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def _canon(fields: list[str]) -> set[str | None]:
    return {_COLUMN_ALIASES.get(_normalise(f)) for f in fields}


def _is_bill_header(fields: list[str]) -> bool:
    c = _canon(fields)
    return "amount" in c and ("what" in c or "date" in c)


def _is_category_header(fields: list[str]) -> bool:
    c = _canon(fields)
    return "category" in c and "category_id" in c


def _is_stats_header(fields: list[str]) -> bool:
    return len({_normalise(f) for f in fields} & _STATS_MARKERS) >= 2


class MoneyBusterCsvParser(BaseParser):
    name = "moneybuster_csv"

    @classmethod
    def sniff(cls, content: bytes, filename: str = "") -> bool:
        text = decode(content).lstrip("﻿")
        for block in _split_blocks(text)[:3]:
            delim = _detect_delimiter("\n".join(block[:3]))
            header = next(csv.reader(io.StringIO(block[0]), delimiter=delim), [])
            if _is_bill_header(header) or _is_stats_header(header):
                return True
        return False

    def parse(self, content: bytes, filename: str = "") -> list[Bill]:
        text = decode(content).lstrip("﻿")
        blocks = _split_blocks(text)
        if not blocks:
            raise ParseError("Die hochgeladene Datei ist leer.")

        delimiter = _detect_delimiter("\n".join(blocks[0][:5]))

        bill_block: list[str] | None = None
        category_lookup: dict[str, str] = {}
        looks_like_stats = False
        for block in blocks:
            header = next(csv.reader(io.StringIO(block[0]), delimiter=delimiter), None)
            if not header:
                continue
            if _is_bill_header(header) and bill_block is None:
                bill_block = block
            elif _is_category_header(header):
                category_lookup.update(self._parse_category_lookup(block, delimiter))
            elif _is_stats_header(header):
                looks_like_stats = True

        if bill_block is None:
            if looks_like_stats:
                raise ParseError(
                    "Das sieht nach dem MoneyBuster/Cospend-*Statistik*-Export "
                    "aus (Salden je Mitglied, z. B. 'Mitgliedsname, Gezahlt, "
                    "Ausgegeben, Saldo'). Dieser enthält keine Einzelbuchungen. "
                    "Bitte die Projekt-/Rechnungsliste exportieren "
                    "(MoneyBuster: Projektmenü → 'Export to CSV')."
                )
            raise ParseError(
                "Kein Rechnungs-Abschnitt gefunden. Erwartet wird eine "
                "Kopfzeile mit mindestens 'amount'/'Betrag' und "
                "'what'/'Was' oder 'date'/'Datum'."
            )

        reader = csv.reader(io.StringIO("\n".join(bill_block)), delimiter=delimiter)
        header = next(reader)
        field_map = {i: _COLUMN_ALIASES.get(_normalise(h)) for i, h in enumerate(header)}
        # Header -> canonical field (or "(ignoriert)") for the diagnostics.
        mapping = {h: (field_map[i] or "(ignoriert)") for i, h in enumerate(header)}

        project = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0] if filename else ""

        bills: list[Bill] = []
        warnings: list[str] = []
        skipped = 0
        # Data rows start on the line after the header within this block.
        for offset, row in enumerate(reader, start=2):
            if not any(cell.strip() for cell in row):
                continue
            values: dict[str, str] = {}
            raw: dict[str, str] = {}
            for i, cell in enumerate(row):
                key = header[i] if i < len(header) else f"col{i}"
                raw[key] = cell
                canon = field_map.get(i)
                if canon:
                    values[canon] = cell.strip()

            title = values.get("what", "").strip()
            ref = f"Zeile {offset} (what={mask(title)})"

            if title == _SENTINEL_TITLE:
                skipped += 1
                warnings.append(f"{ref}: Cospend-Platzhalter übersprungen.")
                continue

            amount_raw = values.get("amount", "")
            if amount_raw == "":
                skipped += 1
                warnings.append(f"{ref}: kein Betrag – übersprungen.")
                continue
            total = parse_amount(amount_raw)
            if total == 0 and amount_raw.strip() not in ("0", "0.0", "0,0", "0.00"):
                warnings.append(f"{ref}: Betrag nicht interpretierbar, als 0 gewertet.")

            ts_raw = values.get("timestamp", "").strip()
            timestamp = int(ts_raw) if ts_raw.lstrip("-").isdigit() else None

            date_raw = values.get("date", "").strip()
            date = normalise_date(date_raw, timestamp)
            if not date_raw and timestamp is None:
                warnings.append(f"{ref}: kein Datum – heutiges Datum verwendet.")

            category = values.get("category", "").strip() or None
            if not category:
                cid = values.get("category_id", "").strip()
                if cid and cid != "0":
                    category = category_lookup.get(cid)
                    if category is None:
                        warnings.append(
                            f"{ref}: categoryid {cid} nicht im Lookup gefunden."
                        )

            owers = split_names(values.get("owers", ""))
            if not owers:
                warnings.append(f"{ref}: keine Teilnehmer (owers) – mein Anteil = 0.")
            shares = equal_shares(abs(total), owers)
            participants = [Participant(name=n, share=shares[n]) for n in owers]

            payer = values.get("payer", "").strip()
            if not payer:
                warnings.append(f"{ref}: kein Zahler angegeben.")

            # No explicit id column in this format: use the (unique, stable)
            # timestamp as the bill key; fall back to a content hash otherwise.
            bill_id = (values.get("bill_id") or "").strip() or None
            if bill_id is None and timestamp is not None:
                bill_id = str(timestamp)

            bills.append(
                Bill(
                    project=project,
                    bill_id=bill_id,
                    date=date,
                    title=title,
                    payer=payer,
                    amount_total=total,
                    currency=values.get("currency", "").strip() or "EUR",
                    participants=participants,
                    category_hint=category,
                    payment_mode=values.get("payment_mode", "").strip() or None,
                    raw=raw,
                )
            )

        if not bills:
            raise ParseError("Der Rechnungs-Abschnitt enthielt keine verwertbaren Zeilen.")
        return ParseResult(
            bills=bills,
            warnings=warnings,
            field_mapping=mapping,
            fmt="csv",
            parser=self.name,
            skipped=skipped,
        )

    @staticmethod
    def _parse_category_lookup(block: list[str], delimiter: str) -> dict[str, str]:
        reader = csv.reader(io.StringIO("\n".join(block)), delimiter=delimiter)
        header = next(reader, None)
        if not header:
            return {}
        field_map = {i: _COLUMN_ALIASES.get(_normalise(h)) for i, h in enumerate(header)}
        lookup: dict[str, str] = {}
        for row in reader:
            name = cid = ""
            for i, cell in enumerate(row):
                if field_map.get(i) == "category":
                    name = cell.strip()
                elif field_map.get(i) == "category_id":
                    cid = cell.strip()
            if cid and name:
                lookup[cid] = name
        return lookup
