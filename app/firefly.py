"""Minimal async client for the Firefly III API."""

from __future__ import annotations

import httpx

from .models import FireflyTransaction, ImportResult


class FireflyError(RuntimeError):
    pass


class FireflyClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        if not base_url or not token:
            raise FireflyError("Firefly base URL and token are required.")
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.api+json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    async def test_connection(self) -> dict:
        """Return the Firefly III `/about` info, raising on failure."""

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(
                f"{self.base_url}/api/v1/about", headers=self._headers
            )
        if resp.status_code == 401:
            raise FireflyError("Authentication failed (check the access token).")
        resp.raise_for_status()
        return resp.json().get("data", {})

    @staticmethod
    def _body(tx: FireflyTransaction, *, error_if_duplicate: bool, apply_rules: bool):
        return {
            "error_if_duplicate_hash": error_if_duplicate,
            "apply_rules": apply_rules,
            "fire_webhooks": False,
            "group_title": None,
            "transactions": [tx.to_split()],
        }

    async def create_transactions(
        self,
        transactions: list[FireflyTransaction],
        *,
        error_if_duplicate: bool = True,
        apply_rules: bool = False,
    ) -> list[ImportResult]:
        """Create each transaction as its own group. Returns per-item results."""

        results: list[ImportResult] = []
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            for tx in transactions:
                results.append(
                    await self._create_one(
                        client, tx, error_if_duplicate, apply_rules
                    )
                )
        return results

    async def _create_one(
        self,
        client: httpx.AsyncClient,
        tx: FireflyTransaction,
        error_if_duplicate: bool,
        apply_rules: bool,
    ) -> ImportResult:
        base = ImportResult(
            description=tx.description,
            date=tx.date,
            amount=tx.amount,
            status="error",
        )
        try:
            resp = await client.post(
                f"{self.base_url}/api/v1/transactions",
                headers=self._headers,
                json=self._body(
                    tx,
                    error_if_duplicate=error_if_duplicate,
                    apply_rules=apply_rules,
                ),
            )
        except httpx.HTTPError as exc:
            base.detail = f"Network error: {exc}"
            return base

        if resp.status_code in (200, 201):
            base.status = "created"
            return base

        detail = self._extract_error(resp)
        if resp.status_code == 422 and "duplicate" in detail.lower():
            base.status = "duplicate"
            base.detail = detail
            return base

        base.detail = f"HTTP {resp.status_code}: {detail}"
        return base

    @staticmethod
    def _extract_error(resp: httpx.Response) -> str:
        try:
            data = resp.json()
        except ValueError:
            return resp.text[:300]
        message = data.get("message", "")
        errors = data.get("errors", {})
        if errors:
            flat = "; ".join(f"{k}: {', '.join(v)}" for k, v in errors.items())
            return f"{message} ({flat})" if message else flat
        return message or resp.text[:300]
