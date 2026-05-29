"""Parser for Cospend / MoneyBuster JSON project exports.

The JSON layout varies between versions; this parser is intentionally
tolerant and resolves member and category ids to names where possible. It
expects a project object containing ``members`` and ``bills`` (and optionally
``categories``).
"""

from __future__ import annotations

import json

from ..models import Bill, Participant
from .base import (
    BaseParser,
    ParseError,
    decode,
    equal_shares,
    normalise_date,
    parse_amount,
)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, dict):
        out = []
        for k, v in value.items():
            if isinstance(v, dict):
                v.setdefault("id", k)
            out.append(v)
        return out
    return []


class CospendJsonParser(BaseParser):
    name = "cospend_json"

    @classmethod
    def sniff(cls, content: bytes, filename: str = "") -> bool:
        text = decode(content).lstrip().lstrip("﻿")
        if not text or text[0] not in "{[":
            return False
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return False
        if isinstance(data, dict):
            return "bills" in data or "members" in data
        return False

    def parse(self, content: bytes, filename: str = "") -> list[Bill]:
        try:
            data = json.loads(decode(content))
        except json.JSONDecodeError as exc:
            raise ParseError(f"Ungültiges JSON: {exc}") from exc

        if not isinstance(data, dict):
            raise ParseError("Erwartet wurde ein Cospend-Projekt-Objekt (JSON).")

        project = str(data.get("name") or data.get("projectid") or "").strip()
        if not project and filename:
            project = filename.rsplit("/", 1)[-1].rsplit(".", 1)[0]

        members = {
            str(m.get("id")): str(m.get("name", "")).strip()
            for m in _as_list(data.get("members"))
            if m.get("name")
        }
        categories = {
            str(c.get("id")): str(c.get("name", "")).strip()
            for c in _as_list(data.get("categories"))
            if c.get("name")
        }

        bills_raw = _as_list(data.get("bills"))
        if not bills_raw:
            raise ParseError("Keine Rechnungen ('bills') im JSON gefunden.")

        bills: list[Bill] = []
        for b in bills_raw:
            payer = self._resolve(b.get("payer_name") or b.get("payer"), b.get("payer_id"), members)
            ower_names = self._resolve_owers(b, members)

            total = parse_amount(str(b.get("amount", "0")))
            shares = equal_shares(abs(total), ower_names)
            participants = [Participant(name=n, share=shares[n]) for n in ower_names]

            cat = b.get("category_name")
            if not cat:
                cid = b.get("categoryid", b.get("category_id"))
                if cid not in (None, 0, "0"):
                    cat = categories.get(str(cid))

            ts = b.get("timestamp")
            bills.append(
                Bill(
                    project=project,
                    bill_id=str(b["id"]) if b.get("id") is not None else None,
                    date=normalise_date(str(b.get("date", "")), int(ts) if ts else None),
                    title=str(b.get("what") or b.get("title") or "").strip(),
                    payer=payer,
                    amount_total=total,
                    currency=str(b.get("currency") or "EUR").strip() or "EUR",
                    participants=participants,
                    category_hint=(cat or None),
                    payment_mode=str(b.get("paymentmode") or "").strip() or None,
                    raw=b if isinstance(b, dict) else {},
                )
            )
        return bills

    @staticmethod
    def _resolve(name, ident, members: dict[str, str]) -> str:
        if name:
            return str(name).strip()
        if ident is not None:
            return members.get(str(ident), "")
        return ""

    @classmethod
    def _resolve_owers(cls, bill: dict, members: dict[str, str]) -> list[str]:
        owers = bill.get("owers")
        names: list[str] = []
        if isinstance(owers, list) and owers:
            for o in owers:
                if isinstance(o, dict):
                    n = o.get("name") or members.get(str(o.get("id")), "")
                else:
                    n = members.get(str(o), str(o))
                if n:
                    names.append(str(n).strip())
        elif bill.get("owerIds"):
            names = [members.get(str(i), "") for i in bill["owerIds"]]
            names = [n for n in names if n]
        return names
