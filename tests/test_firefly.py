import functools

import httpx
import pytest

from app import firefly as firefly_mod
from app.firefly import FireflyClient
from app.models import FireflyTransaction


def _tx(desc="Test", amount="10.00"):
    return FireflyTransaction(
        type="withdrawal", date="2024-03-01T00:00:00", amount=amount,
        description=desc, currency_code="EUR", source_name="A",
        destination_name="B", external_id="mb-x",
    )


@pytest.fixture
def patched_client(monkeypatch):
    """Patch httpx.AsyncClient so FireflyClient talks to a handler instead."""

    def install(handler):
        transport = httpx.MockTransport(handler)
        monkeypatch.setattr(
            firefly_mod.httpx,
            "AsyncClient",
            functools.partial(httpx.AsyncClient, transport=transport),
        )

    return install


@pytest.mark.anyio
async def test_created_duplicate_and_error(patched_client):
    seen = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["n"] += 1
        if seen["n"] == 1:
            return httpx.Response(200, json={"data": {"id": "1"}})
        if seen["n"] == 2:
            return httpx.Response(
                422, json={"message": "Duplicate transaction found.",
                           "errors": {"transactions.0.description": ["dup"]}}
            )
        return httpx.Response(
            422, json={"message": "Validation failed",
                       "errors": {"transactions.0.amount": ["bad"]}}
        )

    patched_client(handler)
    client = FireflyClient("https://firefly.test", "token")
    results = await client.create_transactions([_tx(), _tx(), _tx()])
    assert [r.status for r in results] == ["created", "duplicate", "error"]


def test_requires_credentials():
    with pytest.raises(Exception):
        FireflyClient("", "")
