"""Booking, behind an interface, plus the in-memory fake the REPL and tests run on.

The fake enforces the guarantee in code: `create_event` refuses a time that isn't
open, so the agent cannot book over an existing appointment even if the model skips
checking availability first. Both backends work off the same hours grid below, so
what you see in the REPL is what a real calendar would offer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import Protocol, runtime_checkable
from uuid import uuid4

from receptionist.services.when import fmt_time, resolve_datetime, spoken, timezone

# Business hours. Appointments start on the grid and must end by closing.
OPEN_HOUR = 8
CLOSE_HOUR = 18
SLOT_MINUTES = 60
APPOINTMENT_MINUTES = 60


class SlotUnavailable(Exception):
    """The requested time is taken, or outside bookable hours."""


class NoBooking(Exception):
    """Nothing on the books for this caller to move or cancel."""


@dataclass(frozen=True)
class Booked:
    """A confirmed appointment — the only thing that proves a booking happened."""

    event_id: str
    service: str
    starts_at: datetime
    ends_at: datetime

    def spoken(self) -> str:
        return f"{self.service} on {spoken(self.starts_at)}"


# runtime_checkable because the tools carry a CalendarService inside `CallContext`, and
# LangChain builds a pydantic schema for the tool signature that isinstance-checks it.
@runtime_checkable
class CalendarService(Protocol):
    async def available_slots(self, day: str) -> list[str]: ...
    async def create_event(
        self, caller_number: str, *, service: str, day: str, time: str
    ) -> Booked: ...
    async def reschedule(self, caller_number: str, *, day: str, time: str) -> Booked: ...
    async def cancel(self, caller_number: str) -> str: ...


def slot_grid(on: date) -> list[datetime]:
    """Candidate start times on `on` whose appointment still ends by closing."""
    tz = timezone()
    opens = datetime.combine(on, time(OPEN_HOUR), tzinfo=tz)
    closes = datetime.combine(on, time(CLOSE_HOUR), tzinfo=tz)
    starts, cursor = [], opens
    while cursor + timedelta(minutes=APPOINTMENT_MINUTES) <= closes:
        starts.append(cursor)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return starts


@dataclass
class FakeCalendarService:
    """In-memory calendar, one active appointment per caller number.

    Seeds tomorrow at 8:00 AM as busy so a demo call visibly declines a taken time —
    the most convincing thing to show a prospect.
    """

    busy: dict[str, set[str]] = field(default_factory=dict)
    _held: dict[str, Booked] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.busy:
            tomorrow = (datetime.now(timezone()) + timedelta(days=1)).date()
            self.busy = {tomorrow.isoformat(): {"8:00 AM"}}

    async def available_slots(self, day: str) -> list[str]:
        from receptionist.services.when import resolve_date

        now = datetime.now(timezone())
        on = resolve_date(day, now.date())
        taken = self.busy.get(on.isoformat(), set())
        # `s > now` drops times already past, matching what a real calendar would offer.
        return [fmt_time(s) for s in slot_grid(on) if s > now and fmt_time(s) not in taken]

    async def create_event(
        self, caller_number: str, *, service: str, day: str, time: str
    ) -> Booked:
        if time not in await self.available_slots(day):
            raise SlotUnavailable(f"{time} on {day} is not available")
        starts_at = resolve_datetime(day, time, tz=timezone())
        booked = Booked(
            event_id=f"evt_{uuid4().hex[:8]}",
            service=service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=APPOINTMENT_MINUTES),
        )
        self._mark_busy(booked)
        self._held[caller_number] = booked
        return booked

    async def reschedule(self, caller_number: str, *, day: str, time: str) -> Booked:
        held = self._held.get(caller_number)
        if held is None:
            raise NoBooking("no existing booking for this caller")
        if time not in await self.available_slots(day):
            raise SlotUnavailable(f"{time} on {day} is not available")
        self._free(held)
        starts_at = resolve_datetime(day, time, tz=timezone())
        moved = Booked(
            event_id=held.event_id,
            service=held.service,
            starts_at=starts_at,
            ends_at=starts_at + timedelta(minutes=APPOINTMENT_MINUTES),
        )
        self._mark_busy(moved)
        self._held[caller_number] = moved
        return moved

    async def cancel(self, caller_number: str) -> str:
        held = self._held.pop(caller_number, None)
        if held is None:
            raise NoBooking("no existing booking for this caller")
        self._free(held)
        return held.spoken()

    def _mark_busy(self, booked: Booked) -> None:
        key = booked.starts_at.date().isoformat()
        self.busy.setdefault(key, set()).add(fmt_time(booked.starts_at))

    def _free(self, booked: Booked) -> None:
        key = booked.starts_at.date().isoformat()
        self.busy.get(key, set()).discard(fmt_time(booked.starts_at))


def build_calendar(profile_id: str) -> CalendarService:
    """The real Google Calendar when this profile has one configured, else the fake.

    The Google import stays lazy so the offline path never loads googleapiclient.
    """
    from receptionist.settings import settings

    calendar_id = settings.calendar_ids.get(profile_id)
    if not calendar_id:
        return FakeCalendarService()

    from receptionist.services.google_calendar import GoogleCalendarService

    return GoogleCalendarService(calendar_id)
