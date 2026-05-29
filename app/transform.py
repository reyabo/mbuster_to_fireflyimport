"""Transform :class:`Bill` objects into Firefly III transactions.

Mapping rules (see README for the rationale and how to adjust them):

* A bill with a positive amount becomes a **withdrawal** (an expense); a
  negative amount becomes a **deposit** (a reimbursement / income). The
  ``invert_sign`` option flips this.
* ``date``     -> transaction date (normalised to ISO 8601).
* ``amount``   -> absolute value, two decimals, ``.`` separator.
* ``what``     -> description (falls back to the category, then a placeholder).
* ``category`` -> Firefly category.
* The source/destination accounts default to the configured asset account and
  an expense/revenue account; the original payer and owers are preserved in
  the notes for traceability.
* A stable ``external_id`` is derived from the bill so re-imports can be
  de-duplicated by Firefly.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone

from .config import Settings
from .models import Bill, FireflyTransaction

_DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%d/%m/%Y",
    "%d.%m.%Y",
    "%m/%d/%Y",
)


@dataclass
class TransformOptions:
    """Per-conversion options, seeded from :class:`Settings` but overridable
    from the web form."""

    asset_account: str
    expense_account: str
    revenue_account: str
    currency: str
    import_tag: str
    invert_sign: bool

    @classmethod
    def from_settings(cls, s: Settings) -> "TransformOptions":
        return cls(
            asset_account=s.default_asset_account,
            expense_account=s.default_expense_account,
            revenue_account=s.default_revenue_account,
            currency=s.default_currency,
            import_tag=s.import_tag,
            invert_sign=s.invert_sign,
        )


def normalise_date(bill: Bill) -> str:
    """Return an ISO-8601 date string for the bill, best effort."""

    value = (bill.date or "").strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%dT%H:%M:%S")
        except ValueError:
            continue
    if bill.timestamp:
        return datetime.fromtimestamp(bill.timestamp, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
    # Last resort: keep whatever we have so the user can spot/fix it.
    return value or datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")


def _external_id(bill: Bill) -> str:
    key = "|".join(
        [
            bill.date,
            f"{bill.amount:.2f}",
            bill.what,
            bill.payer,
            ",".join(bill.owers),
        ]
    )
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return f"mb-{digest}"


def _build_notes(bill: Bill) -> str:
    lines = []
    if bill.payer:
        lines.append(f"Payer: {bill.payer}")
    if bill.owers:
        lines.append(f"Owers: {', '.join(bill.owers)}")
    if bill.payment_mode:
        lines.append(f"Payment mode: {bill.payment_mode}")
    if bill.comment:
        lines.append(f"Comment: {bill.comment}")
    lines.append("Imported from MoneyBuster")
    return "\n".join(lines)


def bill_to_transaction(bill: Bill, opts: TransformOptions) -> FireflyTransaction:
    is_expense = bill.amount >= 0
    if opts.invert_sign:
        is_expense = not is_expense

    description = bill.what or bill.category or "(no description)"
    currency = (bill.currency or opts.currency or "EUR").strip()
    tags = [opts.import_tag] if opts.import_tag else []

    if is_expense:
        tx_type = "withdrawal"
        source = opts.asset_account
        destination = bill.category or opts.expense_account
    else:
        tx_type = "deposit"
        source = bill.category or opts.revenue_account
        destination = opts.asset_account

    return FireflyTransaction(
        type=tx_type,
        date=normalise_date(bill),
        amount=f"{abs(bill.amount):.2f}",
        description=description,
        currency_code=currency,
        source_name=source,
        destination_name=destination,
        category_name=bill.category,
        tags=tags,
        notes=_build_notes(bill),
        external_id=_external_id(bill),
    )


def transform_bills(
    bills: list[Bill], opts: TransformOptions
) -> list[FireflyTransaction]:
    return [bill_to_transaction(b, opts) for b in bills]
