from decimal import Decimal
from pathlib import Path

import pytest

from app.models import ExportType
from app.parsers import ParseError, parse
from app.parsers.base import equal_shares, normalise_date, parse_amount

FIX = Path(__file__).parent / "fixtures"


def _bytes(name: str) -> bytes:
    return (FIX / name).read_bytes()


# --- normalisation helpers ------------------------------------------------

def test_date_normalisation_formats():
    assert normalise_date("01.03.2024") == "2024-03-01"
    assert normalise_date("2024-03-01") == "2024-03-01"
    assert normalise_date("", 1709251200).startswith("2024")


def test_amount_normalisation():
    assert parse_amount("1.234,56") == Decimal("1234.56")
    assert parse_amount("1,234.56") == Decimal("1234.56")
    assert parse_amount("36,80") == Decimal("36.80")
    assert parse_amount("7.1") == Decimal("7.10")


def test_equal_shares_sum_exactly():
    shares = equal_shares(Decimal("10.00"), ["A", "B", "C"])
    assert sum(shares.values()) == Decimal("10.00")
    # remainder cent goes to the first participant
    assert shares["A"] == Decimal("3.34")


# --- CSV ------------------------------------------------------------------

def test_real_cospend_csv_resolves_categories_and_skips_sentinel():
    bills = parse(_bytes("bills_real_cospend.csv"), "Klassenfahrt.csv")
    assert [b.title for b in bills] == ["Kaffee", "Pizza", "schokomuseun"]
    assert bills[0].category_hint == "Gesundheit"      # id 75
    assert bills[2].category_hint == "Ausflug/Kultur"  # id 74
    assert bills[0].payer == "Oli"
    assert bills[0].participants[0].name == "Oli"


def test_german_csv_semicolon_and_comma_decimal():
    bills = parse(_bytes("bills_de.csv"), "x.csv", ExportType.csv)
    assert bills[0].title == "Hotel Tokio"
    assert bills[0].amount_total == Decimal("240.00")
    assert bills[0].date == "2024-03-01"
    assert bills[0].category_hint == "Unterkunft"


def test_statistics_export_raises():
    with pytest.raises(ParseError) as exc:
        parse(_bytes("stats_de.csv"), "stats.csv")
    assert "statistik" in str(exc.value).lower()


# --- JSON -----------------------------------------------------------------

def test_cospend_json_resolves_members_and_categories():
    bills = parse(_bytes("cospend.json"), "Urlaub.json", ExportType.auto)
    assert len(bills) == 2
    b = bills[0]
    assert b.project == "Urlaub"
    assert b.bill_id == "123"
    assert b.payer == "Oliver"
    assert b.title == "Restaurant"
    assert b.category_hint == "Restaurant"
    assert {p.name for p in b.participants} == {"Oliver", "Anna"}
    assert b.share_for("Oliver") == Decimal("30.00")
    # second bill: payer resolved via id, no category (id 0)
    assert bills[1].payer == "Anna"
    assert bills[1].category_hint is None


def test_auto_detect_picks_json_then_csv():
    assert len(parse(_bytes("cospend.json"), "p.json")) == 2
    assert len(parse(_bytes("bills_en.csv"), "p.csv")) == 4
