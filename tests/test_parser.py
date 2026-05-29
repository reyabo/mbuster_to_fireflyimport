from pathlib import Path

import pytest

from app.parser import ParseError, parse_export

FIXTURES = Path(__file__).parent / "fixtures"


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_english_bills():
    bills = parse_export(_read("bills_en.csv"))
    assert len(bills) == 4
    first = bills[0]
    assert first.what == "Hotel Tokyo"
    assert first.amount == pytest.approx(240.00)
    assert first.date == "2024-03-01"
    assert first.payer == "Jan"
    assert first.owers == ["Jan", "Oli"]
    # Negative amounts are preserved (sign handling happens in transform).
    assert bills[3].amount == pytest.approx(-50.00)


def test_parse_german_bills_semicolon_and_comma_decimal():
    bills = parse_export(_read("bills_de.csv"))
    assert len(bills) == 2
    assert bills[0].what == "Hotel Tokio"
    assert bills[0].amount == pytest.approx(240.00)
    assert bills[0].date == "01.03.2024"
    assert bills[0].category == "Unterkunft"
    assert bills[0].comment == "2 Nächte"
    assert bills[1].amount == pytest.approx(36.80)


def test_statistics_export_raises_helpful_error():
    with pytest.raises(ParseError) as exc:
        parse_export(_read("stats_de.csv"))
    assert "statistics" in str(exc.value).lower()


def test_empty_input_raises():
    with pytest.raises(ParseError):
        parse_export("")


def test_real_cospend_export_resolves_categories_and_skips_sentinel():
    bills = parse_export(_read("bills_real_cospend.csv"))
    # The "deleteMeIfYouWant" placeholder bill must be skipped.
    assert [b.what for b in bills] == ["Kaffee", "Pizza", "schokomuseun"]
    # categoryid is resolved to the name via the trailing lookup section.
    assert bills[0].category == "Gesundheit"      # id 75
    assert bills[2].category == "Ausflug/Kultur"  # id 74
    # owers with a trailing comma collapse to a single member.
    assert bills[0].owers == ["Oli"]
    assert bills[1].amount == pytest.approx(45.0)
