import re

from fastapi.testclient import TestClient

import app.main as m
from app.main import app

FIXTURE = "tests/fixtures/bills_real_cospend.csv"


def test_app_imports_and_serves():
    """Startup smoke test: importing the app and serving must not crash even
    without an app/static directory (regression for the missing-static blocker).
    """
    c = TestClient(app)
    assert c.get("/healthz").text == "ok"
    assert c.get("/").status_code == 200


def test_missing_asset_account_blocks_import(monkeypatch):
    # Firefly "configured" so we get past that check to the asset validation.
    monkeypatch.setattr(m.settings, "firefly_url", "https://ff.test")
    monkeypatch.setattr(m.settings, "firefly_token", "tok")
    monkeypatch.setattr(m.settings, "default_asset_account", "")  # no fallback
    c = TestClient(app)

    with open(FIXTURE, "rb") as f:
        r = c.post(
            "/preview",
            files={"file": ("K.csv", f, "text/csv")},
            data={"export_type": "auto", "self_name": "M1",
                  "asset_account": "", "mode": "real_payment"},
        )
    assert r.status_code == 200
    assert "Kein Asset-Konto" in r.text  # visible error in preview
    token = re.search(r'name="token" value="([^"]+)"', r.text).group(1)

    r2 = c.post(
        "/import",
        data={"token": token, "filename": "K.csv", "export_type": "auto",
              "self_name": "M1", "asset_account": "", "mode": "real_payment"},
    )
    assert r2.status_code == 400
    assert "Asset-Konto" in r2.text
