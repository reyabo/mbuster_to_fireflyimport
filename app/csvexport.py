"""Produce a Firefly III Data Importer ready CSV and matching config.json.

This is the *optional* file-based path: instead of pushing to the API you can
download these two files and upload them in the Firefly III Data Importer.
"""

from __future__ import annotations

import csv
import io
import json

from .models import FireflyTransaction
from .transform import TransformOptions

# Column order written to the CSV and the matching Data Importer "roles".
_COLUMNS: list[tuple[str, str, bool]] = [
    # (csv header, firefly role, map_to_existing)
    ("date", "date_transaction", False),
    ("amount", "amount", False),
    ("description", "description", False),
    ("source_name", "account-name", True),
    ("destination_name", "opposing-name", True),
    ("category", "category-name", True),
    ("currency_code", "currency-code", True),
    ("tags", "tags-comma", False),
    ("notes", "note", False),
    ("external_id", "external-id", False),
]


def to_csv(transactions: list[FireflyTransaction]) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, quoting=csv.QUOTE_MINIMAL)
    writer.writerow([header for header, _, _ in _COLUMNS])
    for tx in transactions:
        writer.writerow(
            [
                tx.date,
                tx.amount,
                tx.description,
                tx.source_name,
                tx.destination_name,
                tx.category_name or "",
                tx.currency_code,
                ",".join(tx.tags),
                tx.notes.replace("\n", " | "),
                tx.external_id,
            ]
        )
    return buf.getvalue()


def to_config(opts: TransformOptions) -> str:
    """Build a Data Importer config.json matching :func:`to_csv` output."""

    roles = [role for _, role, _ in _COLUMNS]
    do_mapping = [map_to for _, _, map_to in _COLUMNS]
    config = {
        "version": 3,
        "source": "csv",
        "date": "Y-m-d\\TH:i:s",
        "default_account": 0,
        "delimiter": "comma",
        "headers": True,
        "rules": False,
        "skip_form": False,
        "add_import_tag": True,
        "specifics": [],
        "roles": roles,
        "do_mapping": do_mapping,
        "mapping": [{} for _ in _COLUMNS],
        "duplicate_detection_method": "cell",
        "unique_column_index": len(_COLUMNS) - 1,  # external_id column
        "unique_column_type": "external-id",
        "ignore_duplicate_lines": True,
        "ignore_duplicate_transactions": True,
        "flow": "file",
        "content_type": "csv",
        "conversion": False,
        "default_currency": opts.currency,
    }
    return json.dumps(config, indent=2)
