"""Inspect a MoneyBuster/Cospend export and print a dry-run diagnostic.

Usage:
    python -m app.diagnose <export-file> [--self NAME] [--mode MODE] [--reveal]

By default all personal values (names, amounts, project) are anonymised so the
output is safe to paste into logs/issues. Pass ``--reveal`` to show real values
locally. No Firefly import is ever performed by this command.
"""

from __future__ import annotations

import argparse
import os
import sys

from .config import settings
from .firefly.mapper import MapOptions, build_proposals
from .models import ExportType, ImportMode
from .parsers import ParseError, parse
from .parsers.base import mask
from .rules import load_rules


def _fmt_amount(value, reveal: bool) -> str:
    return f"{value:.2f}" if reveal else "***"


def _fmt(value, reveal: bool) -> str:
    return str(value) if reveal else mask(str(value))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="MoneyBuster/Cospend export diagnostic")
    ap.add_argument("file")
    ap.add_argument("--self", dest="self_name", default=settings.self_name,
                    help="eigener Mitgliedsname (für Modus/Anteil)")
    ap.add_argument("--mode", default="real_payment",
                    choices=[m.value for m in ImportMode])
    ap.add_argument("--type", default="auto",
                    choices=[t.value for t in ExportType])
    ap.add_argument("--reveal", action="store_true",
                    help="echte Werte zeigen (nur lokal!)")
    args = ap.parse_args(argv)

    raw = open(args.file, "rb").read()
    print(f"Datei: {os.path.basename(args.file)}  ({len(raw)} Bytes)")

    try:
        result = parse(raw, args.file, ExportType(args.type))
    except ParseError as exc:
        print(f"PARSE-FEHLER: {exc}")
        return 2

    print(f"Format: {result.fmt}  |  Parser: {result.parser}")
    print("\nFeldzuordnung (Header -> internes Feld):")
    for src, dst in result.field_mapping.items():
        print(f"  {src:<16} -> {dst}")

    opts = MapOptions(
        self_name=args.self_name,
        asset_account=settings.default_expense_account,
        mode=ImportMode(args.mode),
        import_tag=settings.import_tag,
    )
    proposals = build_proposals(result.bills, opts, load_rules(settings.rules_path))

    importable = sum(1 for p in proposals if p.should_import)
    skipped = sum(1 for p in proposals if not p.should_import)
    print("\nZusammenfassung:")
    print(f"  erkannte Bills:        {len(result.bills)}")
    print(f"  importierbar:          {importable}")
    print(f"  nicht importiert:      {skipped}")
    print(f"  übersprungene Zeilen:  {result.skipped} (z. B. Platzhalter)")
    print(f"  Warnungen:             {len(result.warnings)}")
    if not args.self_name:
        print("  HINWEIS: kein --self gesetzt -> im Modus 'reale Zahlung' gilt "
              "niemand als Selbstzahler.")

    if result.warnings:
        print("\nWarnungen:")
        for w in result.warnings:
            print(f"  - {w}")

    print(f"\nErste 5 Importvorschläge ({'KLAR' if args.reveal else 'anonymisiert'}):")
    for p in proposals[:5]:
        print(
            f"  [{p.status.value:>17}] import={p.should_import!s:<5} "
            f"date={p.date} desc={_fmt(p.description, args.reveal):<10} "
            f"payer={_fmt(p.payer, args.reveal):<6} "
            f"total={_fmt_amount(p.amount_total, args.reveal)} "
            f"mine={_fmt_amount(p.my_share, args.reveal)} "
            f"import={_fmt_amount(p.import_amount, args.reveal)} "
            f"cat={p.category} type={p.transaction_type}"
        )

    print("\nKein Firefly-Import durchgeführt (Diagnose-Modus).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
