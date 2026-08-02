"""The `calls` table, and the two conversions between it and `CallRecord`.

One row per call. The whole record goes in `record` as JSONB; the columns beside it are
call-level facts lifted out of that blob so a query never has to open it — who called,
which business they reached, when, for how long, and how it ended.

Those columns are written and never read. `to_record` reconstructs from the JSONB alone,
which is what makes the round trip exact: pydantic wrote that JSON and pydantic parses it
back, with no column type in between to round a timestamp or widen an enum.

Duration is not a column. It is `ended_at - started_at`, both of which are already here;
storing their difference as a third value is one more thing that can disagree.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from receptionist.core.models import CallRecord


class Base(DeclarativeBase):
    """Alembic's `target_metadata`, and the only declarative base."""


class CallRow(Base):
    __tablename__ = "calls"

    # The id is the /c/{id} slug, so every lookup this app makes is a primary-key point
    # read. A random UUID is also the right choice for CockroachDB specifically:
    # sequential keys hotspot a single range, random ones spread writes across them.
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    profile_id: Mapped[str] = mapped_column(String(64))
    caller_number: Mapped[str] = mapped_column(String(32))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    outcome: Mapped[str | None] = mapped_column(String(32))
    record: Mapped[dict[str, Any]] = mapped_column(JSONB)

    @classmethod
    def of(cls, record: CallRecord) -> CallRow:
        return cls(
            id=record.id,
            profile_id=record.profile_id,
            caller_number=record.caller_number,
            started_at=record.started_at,
            ended_at=record.ended_at,
            outcome=record.outcome.value if record.outcome else None,
            # mode="json" so datetimes and the UUID land as strings rather than as
            # Python objects the JSONB serialiser would refuse.
            record=record.model_dump(mode="json"),
        )

    def to_record(self) -> CallRecord:
        return CallRecord.model_validate(self.record)
