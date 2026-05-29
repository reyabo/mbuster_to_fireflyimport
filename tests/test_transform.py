from pathlib import Path

from app.config import Settings
from app.parser import parse_export
from app.transform import (
    TransformOptions,
    bill_to_transaction,
    normalise_date,
    transform_bills,
)
from app.models import Bill

FIXTURES = Path(__file__).parent / "fixtures"


def _opts(**kw) -> TransformOptions:
    base = TransformOptions.from_settings(Settings())
    for k, v in kw.items():
        setattr(base, k, v)
    return base


def test_positive_bill_becomes_withdrawal():
    bill = Bill(what="Hotel", amount=240.0, date="2024-03-01", payer="Jan",
                owers=["Jan", "Oli"], category="Unterkunft")
    tx = bill_to_transaction(bill, _opts(asset_account="Reisekasse"))
    assert tx.type == "withdrawal"
    assert tx.amount == "240.00"
    assert tx.source_name == "Reisekasse"
    assert tx.destination_name == "Unterkunft"  # category used as expense acct
    assert tx.category_name == "Unterkunft"
    assert "Payer: Jan" in tx.notes
    assert tx.external_id.startswith("mb-")


def test_negative_bill_becomes_deposit():
    bill = Bill(what="Refund", amount=-50.0, date="2024-03-05", payer="Oli")
    tx = bill_to_transaction(bill, _opts(asset_account="Reisekasse"))
    assert tx.type == "deposit"
    assert tx.amount == "50.00"
    assert tx.destination_name == "Reisekasse"


def test_invert_sign_flips_type():
    bill = Bill(what="Salary", amount=100.0, date="2024-03-05")
    tx = bill_to_transaction(bill, _opts(invert_sign=True))
    assert tx.type == "deposit"


def test_iso_date_normalisation():
    assert normalise_date(Bill("x", 1, "01.03.2024")).startswith("2024-03-01")
    assert normalise_date(Bill("x", 1, "2024-03-01")).startswith("2024-03-01")
    assert normalise_date(Bill("x", 1, "", timestamp=1709251200)).startswith("2024")


def test_external_id_is_stable():
    bill = Bill(what="Hotel", amount=240.0, date="2024-03-01", payer="Jan")
    a = bill_to_transaction(bill, _opts())
    b = bill_to_transaction(bill, _opts())
    assert a.external_id == b.external_id


def test_transform_roundtrip_from_fixture():
    bills = parse_export((FIXTURES / "bills_en.csv").read_text(encoding="utf-8"))
    txs = transform_bills(bills, _opts())
    assert len(txs) == 4
    assert [t.type for t in txs] == [
        "withdrawal", "withdrawal", "withdrawal", "deposit",
    ]
