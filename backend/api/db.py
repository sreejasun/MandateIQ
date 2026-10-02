"""SQLite storage for datasets, reviews and what-if scenarios.

A new connection is opened per operation, which keeps the module safe to use
from the API threads and the background review worker.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS datasets (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    csv         TEXT NOT NULL,
    row_count   INTEGER NOT NULL,
    is_demo     INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reviews (
    id            TEXT PRIMARY KEY,
    kind          TEXT NOT NULL DEFAULT 'review',   -- review | scenario
    parent_id     TEXT,                             -- scenario -> original review
    dataset_id    TEXT NOT NULL,
    fund_id       TEXT NOT NULL,
    fund_name     TEXT,
    ticker        TEXT,
    mandate       TEXT NOT NULL,
    provider      TEXT NOT NULL,
    model         TEXT,
    status        TEXT NOT NULL,                    -- queued | running | completed | failed
    outcome       TEXT NOT NULL DEFAULT 'pending',
    trust_score   REAL,
    fund          TEXT,                             -- JSON: dataset row reviewed
    changes       TEXT,                             -- JSON: scenario changes
    options       TEXT,                             -- JSON: run options (demo seeding)
    state         TEXT,                             -- JSON: final WorkflowState
    events        TEXT NOT NULL DEFAULT '[]',       -- JSON: progress events
    error         TEXT,
    created_at    TEXT NOT NULL,
    started_at    TEXT,
    completed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_reviews_kind ON reviews(kind, created_at);
CREATE INDEX IF NOT EXISTS idx_reviews_parent ON reviews(parent_id);
"""

_JSON_FIELDS = ("fund", "changes", "options", "state", "events")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=30, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------ helpers
    @staticmethod
    def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
        if row is None:
            return None
        out = dict(row)
        for key in _JSON_FIELDS:
            if key in out and out[key] is not None:
                out[key] = json.loads(out[key])
        return out

    def _execute(self, sql: str, params: tuple = ()) -> None:
        with self._lock, self._connect() as conn:
            conn.execute(sql, params)

    # ------------------------------------------------------------ datasets
    def add_dataset(self, id: str, name: str, csv: str, row_count: int, is_demo: bool = False) -> None:
        self._execute(
            "INSERT OR REPLACE INTO datasets (id, name, csv, row_count, is_demo, created_at) VALUES (?,?,?,?,?,?)",
            (id, name, csv, row_count, int(is_demo), now()),
        )

    def get_dataset(self, id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._row(conn.execute("SELECT * FROM datasets WHERE id = ?", (id,)).fetchone())

    def list_datasets(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT id, name, row_count, is_demo, created_at FROM datasets ORDER BY is_demo DESC, created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------ reviews
    def add_review(self, record: dict[str, Any]) -> None:
        data = {**record}
        for key in _JSON_FIELDS:
            if key in data and data[key] is not None:
                data[key] = json.dumps(data[key], default=str)
        data.setdefault("created_at", now())
        cols = ", ".join(data)
        marks = ", ".join("?" for _ in data)
        self._execute(f"INSERT INTO reviews ({cols}) VALUES ({marks})", tuple(data.values()))

    def update_review(self, id: str, **fields: Any) -> None:
        if not fields:
            return
        for key in _JSON_FIELDS:
            if key in fields and fields[key] is not None:
                fields[key] = json.dumps(fields[key], default=str)
        assignments = ", ".join(f"{k} = ?" for k in fields)
        self._execute(f"UPDATE reviews SET {assignments} WHERE id = ?", (*fields.values(), id))

    def get_review(self, id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            return self._row(conn.execute("SELECT * FROM reviews WHERE id = ?", (id,)).fetchone())

    def list_reviews(self, kind: str = "review", parent_id: str | None = None,
                     with_state: bool = False) -> list[dict[str, Any]]:
        cols = "*" if with_state else (
            "id, kind, parent_id, dataset_id, fund_id, fund_name, ticker, mandate, provider, model, status, "
            "outcome, trust_score, changes, options, error, created_at, started_at, completed_at"
        )
        sql = f"SELECT {cols} FROM reviews WHERE kind = ?"
        params: list[Any] = [kind]
        if parent_id is not None:
            sql += " AND parent_id = ?"
            params.append(parent_id)
        sql += " ORDER BY created_at DESC, rowid DESC"
        with self._connect() as conn:
            rows = conn.execute(sql, tuple(params)).fetchall()
        return [self._row(r) for r in rows]

    def delete_review(self, id: str) -> None:
        self._execute("DELETE FROM reviews WHERE id = ? OR parent_id = ?", (id, id))

    def fail_interrupted(self) -> int:
        """Mark reviews left running by a previous server process as failed."""
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "UPDATE reviews SET status = 'failed', outcome = 'failed', "
                "error = 'Interrupted because the server stopped before the review finished.', completed_at = ? "
                "WHERE status IN ('queued', 'running')",
                (now(),),
            )
            return cur.rowcount
