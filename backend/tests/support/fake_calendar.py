"""An in-memory calendar, so the suite books nothing against a real Google Calendar.

Lives here rather than in `src/` because it is a test double: production has exactly one
`CalendarService`, the Google one, and a profile without a configured calendar refuses to
start rather than quietly booking into memory.

It still enforces the guarantee in code — `create_event` refuses a time that isn't open —
so a test proves the agent cannot double-book even when the model skips checking
availability. Openings come from the same `slot_grid` and the same profile hours the real
backend uses, so the two cannot drift on what "open" means.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from uuid import uuid4

from receptionist.worker.booking.service import (
    APPOINTMENT_MINUTES,
    CLOSE_HOUR,
    OPEN_HOUR,
    Booked,
    NoBooking,
    SlotUnavailable,
    slot_grid,
)
from receptionist.worker.lib.datetimes import fmt_time, resolve_date, resolve_datetime, timezone


@dataclass
class FakeCalendarService:
    """In-memory calendar, one active appointment per caller number.

    Seeds tomorrow's first opening as busy, so a test can ask for a taken time and watch
    the agent decline it and offer real alternatives.
    """

    open_hour: int = OPEN_HOUR
    close_hour: int = CLOSE_HOUR
    busy: dict[str, set[str]] = field(default_factory=dict)
    _held: dict[str, Booked] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.busy:
            return
        tomorrow = (datetime.now(timezone()) + timedelta(days=1)).date()
        openings = self._grid(tomorrow)
        if openings:
            self.busy = {tomorrow.isoformat(): {fmt_time(openings[0])}}

    def _grid(self, on: date) -> list[datetime]:
        return slot_grid(on, self.open_hour, self.close_hour)

    async def available_slots(self, day: str) -> list[str]:
        now = datetime.now(timezone())
        on = resolve_date(day, now.date())
        taken = self.busy.get(on.isoformat(), set())
        # `s > now` drops times already past, matching what a real calendar would offer.
        return [fmt_time(s) for s in self._grid(on) if s > now and fmt_time(s) not in taken]

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
        # Release the caller's own slot before checking, or moving to the time they
        # already hold looks like a clash with themselves. GoogleCalendarService excludes
        # the caller's own event for the same reason; the two must agree.
        self._free(held)
        if time not in await self.available_slots(day):
            self._mark_busy(held)
            raise SlotUnavailable(f"{time} on {day} is not available")
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
