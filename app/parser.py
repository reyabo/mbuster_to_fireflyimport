"""Parse MoneyBuster / Cospend CSV exports into :class:`Bill` objects.

The export format produced by MoneyBuster (and Nextcloud Cospend) is a CSV
that may contain several *sections* separated by blank lines: the bills, and
optionally the categories, currencies and members. Column order and the exact
set of columns vary between app versions, so instead of hard-coding positions
we detect the bills section by its header and map columns by name.
"""

from __future__ import annotations

import csv
import io
import re

from .models import Bill


class ParseError(ValueError):
    """Raised when no usable bill section can be found in the input."""


# Maps a normalised (lowercased, stripped) header name to a canonical field.
# Cospend / MoneyBuster exports are localised, so both the machine-readable
# English headers and common German labels are recognised.
_COLUMN_ALIASES: dict[str, str] = {
    # what / description
    "what": "what",
    "name": "what",
    "title": "what",
    "description": "what",
    "was": "what",
    "titel": "what",
    "beschreibung": "what",
    # amount
    "amount": "amount",
    "value": "amount",
    "betrag": "amount",
    # date
    "date": "date",
    "datum": "date",
    "timestamp": "timestamp",
    "zeitstempel": "timestamp",
    # payer
    "payer_name": "payer",
    "payer": "payer",
    "payername": "payer",
    "zahler": "payer",
    "zahlername": "payer",
    "bezahltvon": "payer",
    # payer weight (ignored, but recognised so it is not misread)
    "payer_weight": "payer_weight",
    "zahlergewicht": "payer_weight",
    # owers
    "owers": "owers",
    "ower": "owers",
    "owers_name": "owers",
    "schuldner": "owers",
    "fuer": "owers",
    "für": "owers",
    # category (inline name)
    "categoryname": "category",
    "category": "category",
    "category_name": "category",
    "kategorie": "category",
    "kategoriename": "category",
    # category referenced by id (resolved via the category lookup section)
    "categoryid": "category_id",
    "kategorieid": "category_id",
    # payment mode
    "paymentmode": "payment_mode",
    "paymentmodename": "payment_mode",
    "payment_mode": "payment_mode",
    "zahlungsmittel": "payment_mode",
    "zahlungsart": "payment_mode",
    # comment
    "comment": "comment",
    "comments": "comment",
    "kommentar": "comment",
    # currency
    "currencyname": "currency",
    "currency": "currency",
    "waehrung": "currency",
    "währung": "currency",
}

# Header names that identify the *statistics* export (per-member balances),
# which does not contain individual bills and therefore cannot be converted.
_STATS_MARKERS = {
    "mitgliedsname",
    "membername",
    "saldo",
    "balance",
    "gezahlt",
    "paid",
    "ausgegeben",
    "spent",
}


def _normalise(header: str) -> str:
    return re.sub(r"\s+", "", header.strip().lower())


def _split_blocks(text: str) -> list[list[str]]:
    """Split the raw file into blocks of non-empty lines (blank line = break)."""

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
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        return dialect.delimiter
    except csv.Error:
        # Fall back to the most common separator present in the sample.
        return ";" if sample.count(";") > sample.count(",") else ","


def _is_bill_header(fields: list[str]) -> bool:
    canon = {_COLUMN_ALIASES.get(_normalise(f)) for f in fields}
    return "amount" in canon and ("what" in canon or "date" in canon)


def _is_stats_header(fields: list[str]) -> bool:
    normalised = {_normalise(f) for f in fields}
    return len(normalised & _STATS_MARKERS) >= 2


def _is_category_header(fields: list[str]) -> bool:
    canon = {_COLUMN_ALIASES.get(_normalise(f)) for f in fields}
    return "category" in canon and "category_id" in canon


def _parse_category_lookup(block: list[str], delimiter: str) -> dict[str, str]:
    """Build an {id: name} map from a `categoryname,categoryid,...` section."""

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


def _parse_amount(value: str) -> float:
    value = value.strip()
    if not value:
        return 0.0
    # Normalise thousands / decimal separators. Cospend uses "." but exports
    # from localised devices may use "," as the decimal separator.
    value = value.replace(" ", "").replace(" ", "")
    if "," in value and "." in value:
        # Whichever comes last is the decimal separator.
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_owers(value: str) -> list[str]:
    if not value:
        return []
    # Owers are joined by commas; allow other common separators too.
    parts = re.split(r"[;,]", value)
    return [p.strip() for p in parts if p.strip()]


def parse_export(text: str) -> list[Bill]:
    """Parse the textual content of a MoneyBuster/Cospend export."""

    # Strip a UTF-8 BOM if present.
    text = text.lstrip("﻿")
    blocks = _split_blocks(text)
    if not blocks:
        raise ParseError("The uploaded file is empty.")

    delimiter = _detect_delimiter("\n".join(blocks[0][:5]))

    bill_block: list[str] | None = None
    category_lookup: dict[str, str] = {}
    looks_like_stats = False
    for block in blocks:
        reader = csv.reader(io.StringIO("\n".join(block)), delimiter=delimiter)
        header = next(reader, None)
        if not header:
            continue
        if _is_bill_header(header) and bill_block is None:
            bill_block = block
        elif _is_category_header(header):
            category_lookup.update(_parse_category_lookup(block, delimiter))
        elif _is_stats_header(header):
            looks_like_stats = True

    if bill_block is None:
        if looks_like_stats:
            raise ParseError(
                "This looks like the MoneyBuster/Cospend *statistics* export "
                "(per-member balances such as 'Mitgliedsname, Gezahlt, "
                "Ausgegeben, Saldo'). It contains only totals, not individual "
                "transactions, and cannot be imported. Please export the "
                "project bill list instead (MoneyBuster: project menu -> "
                "'Export to CSV')."
            )
        raise ParseError(
            "No bill section found. Expected a header containing at least "
            "'amount'/'Betrag' and 'what'/'Was' or 'date'/'Datum'."
        )

    reader = csv.reader(io.StringIO("\n".join(bill_block)), delimiter=delimiter)
    header = next(reader)
    field_map = {i: _COLUMN_ALIASES.get(_normalise(h)) for i, h in enumerate(header)}

    bills: list[Bill] = []
    for row in reader:
        if not any(cell.strip() for cell in row):
            continue
        values: dict[str, str] = {}
        raw: dict[str, str] = {}
        for i, cell in enumerate(row):
            canon = field_map.get(i)
            raw[header[i] if i < len(header) else f"col{i}"] = cell
            if canon:
                values[canon] = cell.strip()

        amount_raw = values.get("amount", "")
        if amount_raw == "":
            # Rows without an amount are not real bills (section separators,
            # totals, etc.) -> skip.
            continue

        what = values.get("what", "").strip()
        # Cospend seeds every project with a placeholder bill; skip it.
        if what == "deleteMeIfYouWant":
            continue

        timestamp = None
        ts_raw = values.get("timestamp", "").strip()
        if ts_raw.isdigit():
            timestamp = int(ts_raw)

        # Prefer an inline category name; otherwise resolve the category id
        # against the lookup section. Id 0 means "no category" in Cospend.
        category = values.get("category", "").strip() or None
        if not category:
            cid = values.get("category_id", "").strip()
            if cid and cid != "0":
                category = category_lookup.get(cid)

        bills.append(
            Bill(
                what=what,
                amount=_parse_amount(amount_raw),
                date=values.get("date", "").strip(),
                payer=values.get("payer", "").strip(),
                owers=_parse_owers(values.get("owers", "")),
                category=category,
                payment_mode=values.get("payment_mode", "").strip() or None,
                comment=values.get("comment", "").strip() or None,
                currency=values.get("currency", "").strip() or None,
                timestamp=timestamp,
                raw=raw,
            )
        )

    if not bills:
        raise ParseError("The bill section did not contain any usable rows.")
    return bills
