"""What one call produces.

`CallRecord` is the single end-result: the agent's tools write to it, the store
persists it, the confirmation SMS summarises it, and the web page renders it. One
type, so those four never drift.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Outcome(StrEnum):
    BOOKED = "booked"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    ANSWERED = "answered"
    MESSAGE_TAKEN = "message_taken"
    ABANDONED = "abandoned"


class TranscriptTurn(BaseModel):
    ts: datetime = Field(default_factory=_now)
    role: str  # "caller" | "agent"
    text: str


class CallEvent(BaseModel):
    """One row on the decision timeline. Emitted by code, never narrated by the model —
    that's what makes it trustworthy evidence of what actually happened."""

    ts: datetime = Field(default_factory=_now)
    type: str  # e.g. "booking_created", "slot_declined"
    summary: str


class Booking(BaseModel):
    service: str
    starts_at: datetime
    ends_at: datetime
    calendar_event_id: str | None = None
    # Whatever this profile collects: {"name": ..., "address": ..., "issue": ...}
    details: dict[str, str] = Field(default_factory=dict)


class Message(BaseModel):
    name: str
    reason: str


class CallRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    profile_id: str
    caller_number: str  # from the call itself (SIP caller ID); never asked for
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    outcome: Outcome | None = None
    booking: Booking | None = None
    message: Message | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    events: list[CallEvent] = Field(default_factory=list)

    def emit(self, type: str, summary: str) -> None:
        self.events.append(CallEvent(type=type, summary=summary))

    def said(self, role: str, text: str) -> None:
        self.transcript.append(TranscriptTurn(role=role, text=text))
