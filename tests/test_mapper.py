from decimal import Decimal

from app.firefly.mapper import MapOptions, build_proposal, external_id
from app.models import Bill, ImportMode, ImportStatus, Participant
from app.rules import RuleSet, Rule


def _bill(payer="Oliver", total="60.00", bill_id="123", owers=("Oliver", "Anna")):
    n = len(owers)
    share = (Decimal(total) / n).quantize(Decimal("0.01"))
    return Bill(
        project="Urlaub",
        bill_id=bill_id,
        date="2026-05-29",
        title="Restaurant",
        payer=payer,
        amount_total=Decimal(total),
        currency="EUR",
        participants=[Participant(name=o, share=share) for o in owers],
    )


RULES = RuleSet(
    rules=[Rule(contains=["RESTAURANT"], category="Entertainment & Freizeit")],
    default_category="Sonstiges",
    default_expense_account="MoneyBuster",
)


def _opts(**kw):
    base = dict(self_name="Oliver", asset_account="Girokonto",
                mode=ImportMode.real_payment, import_tag="moneybuster")
    base.update(kw)
    return MapOptions(**base)


def test_mode_a_self_paid_imports_full_amount():
    p = build_proposal(_bill(), _opts(), RULES)
    assert p.should_import is True
    assert p.status == ImportStatus.new
    assert p.import_amount == Decimal("60.00")
    assert p.source_account == "Girokonto"
    assert p.category == "Entertainment & Freizeit"
    assert "moneybuster" in p.tags and "Urlaub" in p.tags


def test_mode_a_other_payer_not_imported():
    p = build_proposal(_bill(payer="Anna"), _opts(), RULES)
    assert p.should_import is False
    assert p.status == ImportStatus.other_payer
    assert p.my_share == Decimal("30.00")
    assert "Anna" in p.status_message


def test_mode_b_my_share():
    p = build_proposal(_bill(), _opts(mode=ImportMode.my_share), RULES)
    assert p.should_import is True
    assert p.import_amount == Decimal("30.00")


def test_mode_b_other_payer_marked_but_importable():
    p = build_proposal(_bill(payer="Anna"), _opts(mode=ImportMode.my_share), RULES)
    assert p.should_import is True
    assert p.import_amount == Decimal("30.00")
    assert "realen Bankfluss" in p.status_message


def test_preview_only_never_imports():
    p = build_proposal(_bill(), _opts(mode=ImportMode.preview_only), RULES)
    assert p.should_import is False
    assert p.status == ImportStatus.skipped


def test_external_id_uses_bill_id():
    assert external_id(_bill(), "moneybuster") == "moneybuster:Urlaub:123"


def test_external_id_hash_fallback_is_stable():
    a = external_id(_bill(bill_id=None), "moneybuster")
    b = external_id(_bill(bill_id=None), "moneybuster")
    assert a == b and a.startswith("moneybuster:")


def test_known_id_marks_probably_imported():
    bill = _bill()
    ext = external_id(bill, "moneybuster")
    p = build_proposal(bill, _opts(known_ids={ext}), RULES)
    assert p.should_import is False
    assert p.status == ImportStatus.probably_imported


def test_negative_amount_flagged_and_not_imported():
    bill = _bill(total="-50.00")
    p = build_proposal(bill, _opts(), RULES)
    assert p.should_import is False
    assert p.status == ImportStatus.negative_amount
    assert "Negativer Betrag" in p.status_message


def test_negative_amount_not_imported_even_in_my_share_mode():
    p = build_proposal(_bill(total="-50.00"), _opts(mode=ImportMode.my_share), RULES)
    assert p.should_import is False
    assert p.status == ImportStatus.negative_amount


def test_notes_contain_split_information():
    p = build_proposal(_bill(), _opts(), RULES)
    assert "Payer: Oliver" in p.notes
    assert "Shares:" in p.notes
    assert "Original bill id: 123" in p.notes
