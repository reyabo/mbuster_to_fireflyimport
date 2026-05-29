import functools
from decimal import Decimal

import httpx
import pytest

from app.firefly import client as client_mod
from app.firefly.client import FireflyClient, FireflyError
from app.models import ImportProposal


def _proposal(ext="moneybuster:Urlaub:1"):
    return ImportProposal(
        transaction_type="withdrawal", date="2026-05-29",
        import_amount=Decimal("60.00"), description="Restaurant",
        currency="EUR", source_account="Girokonto",
        destination_account="MoneyBuster", category="Sonstiges",
        tags=["moneybuster"], notes="...", external_id=ext,
    )


@pytest.fixture
def patch_transport(monkeypatch):
    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            client_mod.httpx,
            "AsyncClient",
            functools.partial(httpx.AsyncClient, transport=transport),
        )
    return install


def test_requires_credentials():
    with pytest.raises(FireflyError):
        FireflyClient("", "")


@pytest.mark.anyio
async def test_create_transaction_created(patch_transport):
    def handler(request):
        assert request.url.path == "/api/v1/transactions"
        return httpx.Response(200, json={"data": {"id": "99"}})

    patch_transport(handler)
    out = await FireflyClient("https://ff.test", "t").create_transaction(_proposal())
    assert out.status == "created"
    assert out.firefly_id == "99"


@pytest.mark.anyio
async def test_create_transaction_duplicate(patch_transport):
    def handler(request):
        return httpx.Response(422, json={"message": "Duplicate of transaction #5."})

    patch_transport(handler)
    out = await FireflyClient("https://ff.test", "t").create_transaction(_proposal())
    assert out.status == "duplicate"


@pytest.mark.anyio
async def test_test_connection_unauthorised(patch_transport):
    patch_transport(lambda r: httpx.Response(401, json={"message": "no"}))
    with pytest.raises(FireflyError):
        await FireflyClient("https://ff.test", "t").test_connection()


@pytest.mark.anyio
async def test_ensure_expense_account_ignores_only_real_already_exists(patch_transport):
    patch_transport(lambda r: httpx.Response(
        422, json={"message": "Validation failed",
                   "errors": {"name": ["The name has already been taken."]}}))
    # genuine duplicate -> no error
    await FireflyClient("https://ff.test", "t").ensure_expense_account("REWE")


@pytest.mark.anyio
async def test_ensure_expense_account_raises_on_other_422(patch_transport):
    patch_transport(lambda r: httpx.Response(
        422, json={"message": "Validation failed",
                   "errors": {"type": ["The selected type is invalid."]}}))
    with pytest.raises(FireflyError):
        await FireflyClient("https://ff.test", "t").ensure_expense_account("X")


@pytest.mark.anyio
async def test_ensure_category_accepts_already_exists(patch_transport):
    patch_transport(lambda r: httpx.Response(
        422, json={"message": "Validation failed",
                   "errors": {"name": ["The name has already been taken."]}}))
    # Must NOT raise for a genuine "already exists" 422.
    await FireflyClient("https://ff.test", "t").ensure_category("Sonstiges")


@pytest.mark.anyio
async def test_ensure_category_raises_on_other_422(patch_transport):
    patch_transport(lambda r: httpx.Response(
        422, json={"message": "Validation failed",
                   "errors": {"name": ["The name field is required."]}}))
    with pytest.raises(FireflyError):
        await FireflyClient("https://ff.test", "t").ensure_category("")


@pytest.mark.anyio
async def test_list_account_names_paginates(patch_transport):
    def handler(request):
        page = int(request.url.params.get("page", "1"))
        if page == 1:
            return httpx.Response(200, json={
                "data": [{"attributes": {"name": "Girokonto"}}],
                "meta": {"pagination": {"total_pages": 2}},
            })
        return httpx.Response(200, json={
            "data": [{"attributes": {"name": "Bargeld"}}],
            "meta": {"pagination": {"total_pages": 2}},
        })

    patch_transport(handler)
    names = await FireflyClient("https://ff.test", "t").list_account_names("asset")
    assert names == ["Girokonto", "Bargeld"]
