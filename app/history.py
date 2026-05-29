"""Local SQLite import history used for de-duplication.

Stores every successfully imported transaction keyed by its stable
``external_id`` so re-uploading the same export never creates duplicates,
independent of whatever Firefly's own duplicate detection does.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS import_history (
    external_id           TEXT PRIMARY KEY,
    date                  TEXT,
    amount                TEXT,
    description           TEXT,
    firefly_transaction_id TEXT,
    created_at            TEXT
);
"""


class ImportHistory:
    def __init__(self, db_path: Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def has(self, external_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM import_history WHERE external_id = ?",
                (external_id,),
            ).fetchone()
        return row is not None

    def known_ids(self, external_ids: list[str]) -> set[str]:
        if not external_ids:
            return set()
        with self._conn() as conn:
            placeholders = ",".join("?" * len(external_ids))
            rows = conn.execute(
                f"SELECT external_id FROM import_history "
                f"WHERE external_id IN ({placeholders})",
                external_ids,
            ).fetchall()
        return {r["external_id"] for r in rows}

    def record(
        self,
        external_id: str,
        *,
        date: str,
        amount: str,
        description: str,
        firefly_transaction_id: str | None,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO import_history "
                "(external_id, date, amount, description, "
                "firefly_transaction_id, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    external_id,
                    date,
                    amount,
                    description,
                    firefly_transaction_id,
                    datetime.now(tz=timezone.utc).isoformat(),
                ),
            )

    def count(self) -> int:
        with self._conn() as conn:
            return conn.execute("SELECT COUNT(*) AS c FROM import_history").fetchone()["c"]
