"""Internal data models, independent of any concrete export format."""

from __future__ import annotations

from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

TWOPLACES = Decimal("0.01")


def money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(TWOPLACES)


class ExportType(str, Enum):
    auto = "auto"
    moneybuster = "moneybuster"
    cospend = "cospend"
    csv = "csv"
    json = "json"


class ImportMode(str, Enum):
    real_payment = "real_payment"  # Modus A (default): full paid amount
    my_share = "my_share"          # Modus B: only my own share
    preview_only = "preview_only"  # never import, just inspect


class ImportStatus(str, Enum):
    new = "new"
    probably_imported = "probably_imported"
    skipped = "skipped"
    other_payer = "other_payer"
    negative_amount = "negative_amount"
    error = "error"


class Participant(BaseModel):
    name: str
    share: Decimal = Field(default=Decimal("0.00"))


class Bill(BaseModel):
    """Normalised intermediate representation of a single expense."""

    project: str = ""
    bill_id: str | None = None
    date: str = ""  # ISO 8601 (YYYY-MM-DD)
    title: str = ""
    payer: str = ""
    amount_total: Decimal = Decimal("0.00")
    currency: str = "EUR"
    participants: list[Participant] = Field(default_factory=list)
    category_hint: str | None = None
    payment_mode: str | None = None
    raw: dict = Field(default_factory=dict)

    def share_for(self, name: str) -> Decimal:
        for p in self.participants:
            if p.name.casefold() == name.casefold():
                return p.share
        return Decimal("0.00")

    def is_participant(self, name: str) -> bool:
        return any(p.name.casefold() == name.casefold() for p in self.participants)


class ImportProposal(BaseModel):
    """A single proposed Firefly III transaction derived from a :class:`Bill`."""

    should_import: bool = False
    status: ImportStatus = ImportStatus.new
    status_message: str = ""

    transaction_type: str = "withdrawal"
    date: str = ""
    title: str = ""
    project: str = ""
    payer: str = ""

    amount_total: Decimal = Decimal("0.00")
    my_share: Decimal = Decimal("0.00")
    import_amount: Decimal = Decimal("0.00")
    currency: str = "EUR"

    source_account: str = ""
    destination_account: str = ""
    category: str = ""
    description: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
    external_id: str = ""


class ImportOutcome(BaseModel):
    external_id: str
    description: str
    date: str
    amount: str
    status: str  # created | skipped | duplicate | error
    detail: str = ""
    firefly_id: str | None = None


class ParseResult(BaseModel):
    """Result of parsing an export: the bills plus diagnostics.

    Incomplete or malformed rows are never silently dropped; they are recorded
    in ``warnings`` so the UI / CLI can surface them.
    """

    bills: list[Bill] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    field_mapping: dict[str, str] = Field(default_factory=dict)
    fmt: str = ""        # "csv" | "json"
    parser: str = ""     # parser name that produced the result
    skipped: int = 0     # rows recognised but intentionally not imported (e.g. sentinel)
