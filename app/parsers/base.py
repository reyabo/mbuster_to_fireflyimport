"""Parser interface and shared normalisation helpers."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

from ..models import Bill


class ParseError(ValueError):
    """Raised when input cannot be parsed into bills."""


class BaseParser(ABC):
    """Base class for all export parsers.

    A parser turns the raw bytes of an upload into a list of normalised
    :class:`Bill` objects. New formats only need to implement :meth:`parse`
    and :meth:`sniff`.
    """

    name: str = "base"

    @abstractmethod
    def parse(self, content: bytes, filename: str = "") -> list[Bill]:
        ...

    @classmethod
    @abstractmethod
    def sniff(cls, content: bytes, filename: str = "") -> bool:
        """Return True if this parser can likely handle the content."""


# --- shared helpers -------------------------------------------------------

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
)


def decode(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def normalise_date(value: str, timestamp: int | None = None) -> str:
    """Return an ISO date string (YYYY-MM-DD), best effort."""

    value = (value or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    if timestamp:
        return datetime.fromtimestamp(timestamp, tz=timezone.utc).strftime("%Y-%m-%d")
    return value or datetime.now(tz=timezone.utc).strftime("%Y-%m-%d")


def parse_amount(value: str) -> Decimal:
    value = (value or "").strip().replace(" ", "").replace(" ", "")
    if not value:
        return Decimal("0.00")
    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):  # German style 1.234,56
            value = value.replace(".", "").replace(",", ".")
        else:  # English style 1,234.56
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")
    try:
        return Decimal(value).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return Decimal("0.00")


def split_names(value: str) -> list[str]:
    if not value:
        return []
    return [p.strip() for p in re.split(r"[;,]", value) if p.strip()]


def equal_shares(total: Decimal, names: list[str]) -> dict[str, Decimal]:
    """Split ``total`` equally between ``names``, putting any rounding
    remainder on the first participant so the shares sum exactly to total."""

    if not names:
        return {}
    cents = int((total * 100).to_integral_value())
    base, remainder = divmod(cents, len(names))
    shares: dict[str, Decimal] = {}
    for i, name in enumerate(names):
        c = base + (1 if i < remainder else 0)
        shares[name] = (Decimal(c) / 100).quantize(Decimal("0.01"))
    return shares
