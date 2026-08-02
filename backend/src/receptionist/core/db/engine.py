"""The connection: one engine, one pool, per process.

Built on first use rather than at import, deliberately. `import receptionist.api.app`
must not dial a database — the web process has to boot and answer /healthz whatever the
database is doing, and the test suite imports the app with no `RECEPTIONIST_DATABASE_URL`
set at all.

`require_database` is the other half of that: both processes check the URL at **startup**,
beside the calendar and Telnyx checks in `worker/voice/session.py`. Same reasoning — a
call whose record cannot be saved fails after the caller has already hung up, which is
the one failure nobody is present to notice.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from receptionist.settings import settings

_engine: AsyncEngine | None = None


class DatabaseNotConfigured(RuntimeError):
    """No RECEPTIONIST_DATABASE_URL, so there is nowhere to put a finished call."""


def require_database() -> None:
    """Fail at startup on a missing database URL, rather than at the end of a call."""
    if not settings.database_url:
        raise DatabaseNotConfigured(
            "RECEPTIONIST_DATABASE_URL is not set, so no call could be saved. "
            "Paste your CockroachDB connection string into it."
        )


def engine() -> AsyncEngine:
    """The process's one engine. Idempotent — every caller shares the same pool."""
    global _engine
    if _engine is None:
        require_database()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


async def dispose() -> None:
    """Close the pool. The web process calls this on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
