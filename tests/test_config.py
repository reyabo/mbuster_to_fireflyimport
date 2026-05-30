from app.config import Settings


def test_payment_mode_map_normalises_keys_case_and_whitespace():
    s = Settings(payment_mode_account_map=
                 '{"Cash":"Bargeld"," EC ":"Girokonto","Überweisung":"Giro"}')
    m = s.payment_mode_map
    assert m["cash"] == "Bargeld"        # case-folded
    assert m["ec"] == "Girokonto"        # trimmed
    assert m["überweisung"] == "Giro"    # umlaut preserved


def test_payment_mode_map_drops_empty_values():
    s = Settings(payment_mode_account_map='{"cash":"Bargeld","x":""}')
    assert s.payment_mode_map == {"cash": "Bargeld"}


def test_payment_mode_map_invalid_or_empty_yields_empty():
    assert Settings(payment_mode_account_map="not json").payment_mode_map == {}
    assert Settings(payment_mode_account_map="[1,2]").payment_mode_map == {}
    assert Settings(payment_mode_account_map="").payment_mode_map == {}
