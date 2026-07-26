"""Persistence seam. `core` defines the interface; an implementation lives elsewhere
(an in-memory one for now; CockroachDB later). Both the agent and the web backend
depend on this interface, never on a concrete store.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from receptionist.core.models import CallRecord


class CallRepository(Protocol):
    async def save(self, record: CallRecord) -> None: ...
    async def get(self, call_id: UUID) -> CallRecord | None: ...
    async def list_recent(self, limit: int = 50) -> list[CallRecord]: ...
