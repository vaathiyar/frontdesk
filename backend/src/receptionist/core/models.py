"""The shared end-result contract.

`CallRecord` is produced by the agent and read by the store, the email, and the
web view — one type, so those three never drift. This module is the spine both
the agent and the (later) web backend import; it depends on nothing else internal
except `links`.
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


class CapturedField(BaseModel):
    key: str
    label: str
    value: str
    confirmed: bool = False


class CallEvent(BaseModel):
    """One row on the decision timeline — emitted by code, not narrated by the LLM."""

    ts: datetime = Field(default_factory=_now)
    type: str  # e.g. "booking_created", "slot_declined", "question_answered"
    summary: str


class Booking(BaseModel):
    service: str
    slot: str  # human-readable, e.g. "Tuesday 10:00 AM"
    calendar_event_id: str | None = None
    fields: list[CapturedField] = Field(default_factory=list)


class CallRecord(BaseModel):
    """THE end-result — single source of truth for one call."""

    id: UUID = Field(default_factory=uuid4)
    profile_id: str
    caller_number: str  # from the call itself (SIP caller ID); never asked for
    started_at: datetime = Field(default_factory=_now)
    ended_at: datetime | None = None
    outcome: Outcome | None = None
    fields: list[CapturedField] = Field(default_factory=list)
    booking: Booking | None = None
    transcript: list[TranscriptTurn] = Field(default_factory=list)
    events: list[CallEvent] = Field(default_factory=list)
    recording_url: str | None = None

    def emit(self, type: str, summary: str) -> None:
        self.events.append(CallEvent(type=type, summary=summary))

    def share_path(self) -> str:
        from receptionist.core.links import sign

        return f"/c/{self.id}?t={sign(self.id)}"
