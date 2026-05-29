"""Map normalised :class:`Bill` objects to :class:`ImportProposal` objects.

This module holds the core business logic: import modes, share calculation,
category/destination resolution and the stable de-duplication key. It performs
no I/O so it is trivially unit-testable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from decimal import Decimal

from ..models import (
    Bill,
    ImportMode,
    ImportProposal,
    ImportStatus,
    money,
)
from ..rules import RuleSet


@dataclass
class MapOptions:
    self_name: str
    asset_account: str
    mode: ImportMode = ImportMode.real_payment
    import_tag: str = "moneybuster"
    source_label: str = "moneybuster"  # external_id prefix
    known_ids: set[str] = field(default_factory=set)


def external_id(bill: Bill, source_label: str) -> str:
    """Stable de-dupe key. Uses the bill id when available, else a hash."""

    if bill.bill_id:
        project = bill.project or "default"
        return f"{source_label}:{project}:{bill.bill_id}"
    parts = "|".join(
        [
            bill.project,
            bill.date,
            bill.title,
            bill.payer,
            f"{bill.amount_total:.2f}",
            ",".join(f"{p.name}:{p.share:.2f}" for p in bill.participants),
        ]
    )
    digest = hashlib.sha256(parts.encode("utf-8")).hexdigest()[:24]
    return f"{source_label}:{digest}"


def _build_notes(bill: Bill) -> str:
    lines = [f"MoneyBuster project: {bill.project or '-'}", f"Payer: {bill.payer or '-'}"]
    if bill.participants:
        shares = ", ".join(
            f"{p.name} {p.share:.2f} {bill.currency}" for p in bill.participants
        )
        lines.append(f"Shares: {shares}")
    if bill.payment_mode:
        lines.append(f"Payment mode: {bill.payment_mode}")
    if bill.bill_id:
        lines.append(f"Original bill id: {bill.bill_id}")
    return "\n".join(lines)


def _tags(bill: Bill, opts: MapOptions) -> list[str]:
    tags: list[str] = []
    if opts.import_tag:
        tags.append(opts.import_tag)
    if bill.project:
        tags.append(bill.project)
    for p in bill.participants:
        if p.name and p.name not in tags:
            tags.append(p.name)
    return tags


def build_proposal(bill: Bill, opts: MapOptions, rules: RuleSet) -> ImportProposal:
    ext_id = external_id(bill, opts.source_label)
    my_share = bill.share_for(opts.self_name) if opts.self_name else Decimal("0.00")
    payer_is_self = (
        bool(opts.self_name) and bill.payer.casefold() == opts.self_name.casefold()
    )

    category = rules.category_for(bill.title, bill.project, hint=bill.category_hint)
    destination = rules.destination_for(bill.title, bill.payer)

    proposal = ImportProposal(
        date=bill.date,
        title=bill.title,
        project=bill.project,
        payer=bill.payer,
        amount_total=money(bill.amount_total),
        my_share=money(my_share),
        currency=bill.currency,
        source_account=opts.asset_account,
        destination_account=destination,
        category=category,
        description=bill.title or category,
        notes=_build_notes(bill),
        tags=_tags(bill, opts),
        external_id=ext_id,
        transaction_type="withdrawal" if bill.amount_total >= 0 else "deposit",
    )

    # --- decide import amount + whether to import -------------------------
    if opts.mode == ImportMode.preview_only:
        proposal.import_amount = money(abs(bill.amount_total))
        proposal.should_import = False
        proposal.status = ImportStatus.skipped
        proposal.status_message = "Nur-Vorschau-Modus: kein Import."
    elif opts.mode == ImportMode.real_payment:
        if payer_is_self:
            proposal.import_amount = money(abs(bill.amount_total))
            proposal.should_import = True
            proposal.status = ImportStatus.new
        else:
            proposal.import_amount = money(abs(my_share))
            proposal.should_import = False
            proposal.status = ImportStatus.other_payer
            proposal.status_message = (
                f"Andere Person ({bill.payer}) hat bezahlt. "
                f"Dein Anteil: {my_share:.2f} {bill.currency}. "
                f"Kein Import im Modus 'reale Zahlung'."
            )
    else:  # my_share
        proposal.import_amount = money(abs(my_share))
        proposal.should_import = my_share > 0
        proposal.status = ImportStatus.new
        if not payer_is_self:
            proposal.status_message = (
                "Nur eigener Anteil – entspricht nicht dem realen Bankfluss "
                f"(bezahlt von {bill.payer})."
            )
        if my_share <= 0:
            proposal.should_import = False
            proposal.status = ImportStatus.skipped
            proposal.status_message = "Kein eigener Anteil an dieser Ausgabe."

    # --- negative amounts --------------------------------------------------
    # A negative MoneyBuster/Cospend amount usually means a reimbursement /
    # money transfer between members. In v1 we do NOT guess a deposit; the row
    # is flagged in the preview and not imported automatically.
    if bill.amount_total < 0:
        proposal.should_import = False
        proposal.status = ImportStatus.negative_amount
        proposal.status_message = (
            f"Negativer Betrag ({bill.amount_total:.2f} {bill.currency}) – "
            "vermutlich Erstattung/Umbuchung. Kein automatischer Import in v1, "
            "bitte manuell in Firefly prüfen."
        )

    # --- de-duplication ----------------------------------------------------
    if ext_id in opts.known_ids:
        proposal.should_import = False
        proposal.status = ImportStatus.probably_imported
        proposal.status_message = "Bereits importiert (lokale Import-Historie)."

    return proposal


def build_proposals(
    bills: list[Bill], opts: MapOptions, rules: RuleSet
) -> list[ImportProposal]:
    return [build_proposal(b, opts, rules) for b in bills]
