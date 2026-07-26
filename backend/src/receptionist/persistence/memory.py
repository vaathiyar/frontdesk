"""In-memory CallRepository — enough for the dev harness and tests.

Swapping in CockroachDB later means writing one more class that satisfies the
same `CallRepository` interface; nothing that reads records changes.
"""

from __future__ import annotations

from uuid import UUID

from receptionist.core.models import CallRecord


class InMemoryCallRepository:
    def __init__(self) -> None:
        self._records: dict[UUID, CallRecord] = {}

    async def save(self, record: CallRecord) -> None:
        # Store a copy so later mutation of the live record doesn't rewrite history.
        self._records[record.id] = record.model_copy(deep=True)

    async def get(self, call_id: UUID) -> CallRecord | None:
        return self._records.get(call_id)

    async def list_recent(self, limit: int = 50) -> list[CallRecord]:
        recs = sorted(self._records.values(), key=lambda r: r.started_at, reverse=True)
        return recs[:limit]
