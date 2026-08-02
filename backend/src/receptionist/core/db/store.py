"""Saving a finished call, and getting it back.

`CallStore` is the seam — a two-method protocol, the same shape as `CalendarService` in
`worker/booking/service.py`. `SqlCallStore` is the one implementation; the suite supplies
its own double (`tests/support/fakes.py`), which is why no test needs a database.

Named for SQLAlchemy rather than for CockroachDB, unlike `GoogleCalendarService`: almost
nothing in here is CockroachDB-specific. The exception is the retry, and it is the one
thing about this database you cannot skip — see `_RETRYABLE` below.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy.exc import DBAPIError

from receptionist.core.db.engine import sessions
from receptionist.core.db.tables import CallRow
from receptionist.core.models import CallRecord

logger = logging.getLogger(__name__)

# SQLSTATE 40001, serialization_failure. CockroachDB runs SERIALIZABLE and pushes
# conflict resolution onto the client: under contention it aborts a transaction and
# expects it to be retried. Postgres surfaces this only at SERIALIZABLE, so it is easy to
# forget — and forgetting it here loses a call record *after* the caller has hung up,
# which is the one failure nobody is present to notice.
#
# Retrying is only safe because both operations are idempotent: `save` merges by primary
# key, `get` reads one.
_RETRYABLE = "40001"
_ATTEMPTS = 3
_BACKOFF_SECONDS = 0.1


def _is_retryable(exc: DBAPIError) -> bool:
    return getattr(exc.orig, "sqlstate", None) == _RETRYABLE


async def _with_retry(what: str, operation: Any) -> Any:
    """Run `operation()`, retrying a serialization failure with a short backoff."""
    for attempt in range(1, _ATTEMPTS + 1):
        try:
            return await operation()
        except DBAPIError as exc:
            if attempt == _ATTEMPTS or not _is_retryable(exc):
                raise
            logger.warning("%s hit a serialization failure, retry %d", what, attempt)
            await asyncio.sleep(_BACKOFF_SECONDS * attempt)
    raise AssertionError("unreachable")  # pragma: no cover


class CallStore(Protocol):
    """Where a finished call goes, and where the texted link resolves it from."""

    async def save(self, record: CallRecord) -> None: ...

    async def get(self, call_id: UUID) -> CallRecord | None: ...


class SqlCallStore:
    async def save(self, record: CallRecord) -> None:
        """Write the call, whether or not it is already there.

        `merge` rather than `add`: a record may be saved more than once — the id is
        minted at call start and `worker/lifecycle.py` writes the finished version — and
        the second write must update the first, not collide with it. That is also what
        makes the retry above safe.
        """

        async def write() -> None:
            async with sessions().begin() as session:
                await session.merge(CallRow.of(record))

        await _with_retry(f"saving call {record.id}", write)

    async def get(self, call_id: UUID) -> CallRecord | None:
        """One primary-key point read. The blob is parsed, the columns are ignored."""

        async def read() -> CallRecord | None:
            async with sessions().begin() as session:
                row = await session.get(CallRow, call_id)
                return row.to_record() if row else None

        result: CallRecord | None = await _with_retry(f"reading call {call_id}", read)
        return result
