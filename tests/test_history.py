from app.history import ImportHistory


def test_record_and_dedupe(tmp_path):
    h = ImportHistory(tmp_path / "hist.sqlite")
    assert h.has("moneybuster:Urlaub:1") is False
    assert h.count() == 0

    h.record("moneybuster:Urlaub:1", date="2026-05-29", amount="60.00",
             description="Restaurant", firefly_transaction_id="42")
    assert h.has("moneybuster:Urlaub:1") is True
    assert h.count() == 1

    # idempotent
    h.record("moneybuster:Urlaub:1", date="2026-05-29", amount="60.00",
             description="Restaurant", firefly_transaction_id="42")
    assert h.count() == 1


def test_known_ids_filters(tmp_path):
    h = ImportHistory(tmp_path / "hist.sqlite")
    h.record("a", date="", amount="", description="", firefly_transaction_id=None)
    h.record("b", date="", amount="", description="", firefly_transaction_id=None)
    assert h.known_ids(["a", "c", "b"]) == {"a", "b"}
    assert h.known_ids([]) == set()
