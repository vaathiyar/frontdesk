"""Where finished calls live, so the link in the confirmation text has something to resolve.

SQLite, one file, no infrastructure — but a real file, which matters: the voice worker
and the web server are separate processes, so an in-memory store would leave every
link in every confirmation text pointing at nothing.

The record is stored as JSON rather than shredded across columns. `CallRecord` is
already the one shared shape, and nothing queries inside it.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from uuid import UUID

from receptionist.core.models import CallRecord
from receptionist.settings import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id         TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    record     TEXT NOT NULL
)
"""


class CallStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self._path = str(path or settings.database_path)
        with self._connect() as db:
            # WAL so the web server can read while the worker is mid-write.
            db.execute("PRAGMA journal_mode=WAL")
            db.execute(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._path)

    async def save(self, record: CallRecord) -> None:
        await asyncio.to_thread(self._save, record)

    async def get(self, call_id: UUID) -> CallRecord | None:
        return await asyncio.to_thread(self._get, call_id)

    async def list_recent(self, limit: int = 50) -> list[CallRecord]:
        return await asyncio.to_thread(self._list_recent, limit)

    def _save(self, record: CallRecord) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT OR REPLACE INTO calls (id, started_at, record) VALUES (?, ?, ?)",
                (str(record.id), record.started_at.isoformat(), record.model_dump_json()),
            )

    def _get(self, call_id: UUID) -> CallRecord | None:
        with self._connect() as db:
            row = db.execute("SELECT record FROM calls WHERE id = ?", (str(call_id),)).fetchone()
        return CallRecord.model_validate_json(row[0]) if row else None

    def _list_recent(self, limit: int) -> list[CallRecord]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT record FROM calls ORDER BY started_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [CallRecord.model_validate_json(row[0]) for row in rows]
