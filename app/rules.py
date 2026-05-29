"""Keyword based category / destination-account rules.

Rules are loaded from ``<DATA_DIR>/rules.json``; if that file does not exist
the bundled :mod:`app.default_rules` is copied there on first use so the user
has an editable starting point.
"""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, Field

_BUNDLED = Path(__file__).resolve().parent / "default_rules.json"


class Rule(BaseModel):
    contains: list[str] = Field(default_factory=list)
    category: str | None = None
    destination_account: str | None = None


class RuleSet(BaseModel):
    rules: list[Rule] = Field(default_factory=list)
    default_category: str = "Sonstiges"
    default_expense_account: str = "MoneyBuster"

    def match(self, *texts: str | None) -> Rule | None:
        haystack = " ".join(t for t in texts if t).casefold()
        for rule in self.rules:
            for needle in rule.contains:
                if needle.casefold() in haystack:
                    return rule
        return None

    def category_for(self, *texts: str | None, hint: str | None = None) -> str:
        rule = self.match(*texts)
        if rule and rule.category:
            return rule.category
        if hint:
            return hint
        return self.default_category

    def destination_for(self, *texts: str | None) -> str:
        rule = self.match(*texts)
        if rule and rule.destination_account:
            return rule.destination_account
        if rule:
            # Use the matched keyword as the merchant/account name.
            haystack = " ".join(t for t in texts if t).casefold()
            for needle in rule.contains:
                if needle.casefold() in haystack:
                    return needle.title()
        return self.default_expense_account


def load_rules(path: Path) -> RuleSet:
    if not path.exists():
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(_BUNDLED.read_text(encoding="utf-8"), encoding="utf-8")
        except OSError:
            return RuleSet(**json.loads(_BUNDLED.read_text(encoding="utf-8")))
    return RuleSet(**json.loads(path.read_text(encoding="utf-8")))
