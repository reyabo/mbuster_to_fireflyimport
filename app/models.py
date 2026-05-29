"""Data models shared across the parser, transformer and API client."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Bill:
    """A single MoneyBuster / Cospend bill (one expense line)."""

    what: str
    amount: float
    date: str  # original, unparsed value from the export
    payer: str = ""
    owers: list[str] = field(default_factory=list)
    category: str | None = None
    payment_mode: str | None = None
    comment: str | None = None
    currency: str | None = None
    timestamp: int | None = None
    raw: dict[str, str] = field(default_factory=dict)


@dataclass
class FireflyTransaction:
    """A transaction ready to be sent to the Firefly III API.

    The field names match the Firefly III `/api/v1/transactions` split object
    so the client can serialise this almost verbatim.
    """

    type: str  # "withdrawal" | "deposit"
    date: str  # ISO 8601
    amount: str  # positive, "." decimal separator
    description: str
    currency_code: str
    source_name: str
    destination_name: str
    category_name: str | None = None
    tags: list[str] = field(default_factory=list)
    notes: str = ""
    external_id: str = ""

    def to_split(self) -> dict[str, object]:
        split: dict[str, object] = {
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "description": self.description,
            "currency_code": self.currency_code,
            "source_name": self.source_name,
            "destination_name": self.destination_name,
            "tags": self.tags,
        }
        if self.category_name:
            split["category_name"] = self.category_name
        if self.notes:
            split["notes"] = self.notes
        if self.external_id:
            split["external_id"] = self.external_id
        return split


@dataclass
class ImportResult:
    """Outcome of pushing one transaction to Firefly III."""

    description: str
    date: str
    amount: str
    status: str  # "created" | "duplicate" | "error"
    detail: str = ""
