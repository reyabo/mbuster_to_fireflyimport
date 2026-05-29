"""Async client for the Firefly III API.

Only the endpoints needed for this tool are implemented. Errors are surfaced
as :class:`FireflyError` with a human-readable message so the UI can display
them directly.
"""

from __future__ import annotations

import httpx

from ..models import ImportOutcome, ImportProposal


class FireflyError(RuntimeError):
    pass


class FireflyClient:
    def __init__(self, base_url: str, token: str, timeout: float = 30.0):
        if not base_url or not token:
            raise FireflyError("Firefly-URL und Token sind erforderlich.")
        self.base_url = base_url.rstrip("/")
        self._headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._timeout = timeout

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=self._timeout, headers=self._headers)

    # --- reads -------------------------------------------------------------

    async def test_connection(self) -> dict:
        async with self._client() as client:
            resp = await client.get(f"{self.base_url}/api/v1/about")
        if resp.status_code == 401:
            raise FireflyError("Authentifizierung fehlgeschlagen (Token prüfen).")
        if resp.status_code >= 400:
            raise FireflyError(f"Firefly nicht erreichbar (HTTP {resp.status_code}).")
        return resp.json().get("data", {})

    async def _paginated(self, path: str, params: dict | None = None) -> list[dict]:
        results: list[dict] = []
        page = 1
        async with self._client() as client:
            while True:
                p = {"limit": 100, "page": page, **(params or {})}
                resp = await client.get(f"{self.base_url}{path}", params=p)
                if resp.status_code >= 400:
                    raise FireflyError(
                        f"GET {path} fehlgeschlagen (HTTP {resp.status_code})."
                    )
                payload = resp.json()
                results.extend(payload.get("data", []))
                meta = payload.get("meta", {}).get("pagination", {})
                if not meta or page >= meta.get("total_pages", page):
                    break
                page += 1
        return results

    async def list_account_names(self, account_type: str) -> list[str]:
        data = await self._paginated("/api/v1/accounts", {"type": account_type})
        return [a["attributes"]["name"] for a in data if a.get("attributes")]

    async def list_category_names(self) -> list[str]:
        data = await self._paginated("/api/v1/categories")
        return [c["attributes"]["name"] for c in data if c.get("attributes")]

    # --- writes ------------------------------------------------------------

    async def ensure_expense_account(self, name: str) -> None:
        await self._ensure("/api/v1/accounts", {"name": name, "type": "expense"})

    async def ensure_category(self, name: str) -> None:
        await self._ensure("/api/v1/categories", {"name": name})

    async def _ensure(self, path: str, body: dict) -> None:
        async with self._client() as client:
            resp = await client.post(f"{self.base_url}{path}", json=body)
        # 200/201 created; 422 typically means it already exists -> fine.
        if resp.status_code not in (200, 201, 422):
            raise FireflyError(
                f"Anlegen via {path} fehlgeschlagen (HTTP {resp.status_code})."
            )

    async def create_transaction(
        self,
        proposal: ImportProposal,
        *,
        error_if_duplicate: bool = True,
        apply_rules: bool = False,
    ) -> ImportOutcome:
        split = {
            "type": proposal.transaction_type,
            "date": proposal.date,
            "amount": str(proposal.import_amount),
            "description": proposal.description or proposal.title,
            "currency_code": proposal.currency,
            "source_name": proposal.source_account,
            "destination_name": proposal.destination_account,
            "tags": proposal.tags,
            "notes": proposal.notes,
            "external_id": proposal.external_id,
        }
        if proposal.category:
            split["category_name"] = proposal.category
        body = {
            "error_if_duplicate_hash": error_if_duplicate,
            "apply_rules": apply_rules,
            "fire_webhooks": False,
            "group_title": None,
            "transactions": [split],
        }
        outcome = ImportOutcome(
            external_id=proposal.external_id,
            description=split["description"],
            date=proposal.date,
            amount=str(proposal.import_amount),
            status="error",
        )
        try:
            async with self._client() as client:
                resp = await client.post(
                    f"{self.base_url}/api/v1/transactions", json=body
                )
        except httpx.HTTPError as exc:
            outcome.detail = f"Netzwerkfehler: {exc}"
            return outcome

        if resp.status_code in (200, 201):
            outcome.status = "created"
            try:
                outcome.firefly_id = resp.json()["data"]["id"]
            except (KeyError, ValueError, TypeError):
                pass
            return outcome

        detail = self._extract_error(resp)
        if resp.status_code == 422 and "duplicate" in detail.lower():
            outcome.status = "duplicate"
        outcome.detail = f"HTTP {resp.status_code}: {detail}"
        return outcome

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
