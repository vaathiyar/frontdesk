"""Calendar integration behind an interface, plus a seeded in-memory fake.

The fake is what the dev harness and tests run against — no network, deterministic,
and it *enforces* the "never book a busy slot" guarantee in code (`create_event`
refuses an unavailable time), so the guarantee holds even if the model skips the
availability check. A `GoogleCalendarService` will implement the same Protocol later.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol
from uuid import uuid4


def _default_seed_busy() -> dict[str, set[str]]:
    """Pre-booked blocks so a demo call visibly *declines* a taken slot.

    Keyed by both the literal `"tomorrow"` and tomorrow's ISO date: the agent now sends
    absolute YYYY-MM-DD dates, while the tests (and hand-typed input) still say "tomorrow".
    Uses the system date — close enough for a dev fake; the real backend is timezone-aware.
    """
    return {"tomorrow": {"8:00 AM"}, (date.today() + timedelta(days=1)).isoformat(): {"8:00 AM"}}


class SlotUnavailable(Exception):
    """Raised when a requested time is already taken."""


class NoBooking(Exception):
    """Raised when a reschedule/cancel is attempted with nothing on the books."""


class CalendarService(Protocol):
    async def available_slots(self, day: str) -> list[str]: ...
    async def create_event(
        self,
        caller_number: str,
        *,
        service: str,
        day: str,
        time: str,
        attendee_email: str | None = None,
    ) -> str: ...
    async def find_event(self, caller_number: str) -> str | None: ...
    async def reschedule(self, caller_number: str, *, day: str, time: str) -> str: ...
    async def cancel(self, caller_number: str) -> str: ...


@dataclass
class _Held:
    service: str
    day: str
    time: str
    event_id: str


@dataclass
class FakeCalendarService:
    """In-memory calendar. One active booking per caller (keyed by caller number).

    Seed a couple of busy blocks so the demo shows the agent *declining* a taken
    slot — the most convincing thing to show a prospect.
    """

    slots: list[str] = field(default_factory=lambda: ["8:00 AM", "10:00 AM", "1:00 PM", "3:00 PM"])
    # day -> times that are already busy before any booking this session.
    seed_busy: dict[str, set[str]] = field(default_factory=_default_seed_busy)
    _booked: dict[str, set[str]] = field(default_factory=dict)
    _held: dict[str, _Held] = field(default_factory=dict)

    def _taken(self, day: str) -> set[str]:
        return self._booked.get(day, set()) | self.seed_busy.get(day, set())

    async def available_slots(self, day: str) -> list[str]:
        taken = self._taken(day)
        return [s for s in self.slots if s not in taken]

    async def create_event(
        self,
        caller_number: str,
        *,
        service: str,
        day: str,
        time: str,
        attendee_email: str | None = None,
    ) -> str:
        # `attendee_email` exists for parity with GoogleCalendarService (which emails the
        # caller the invite); the in-memory fake has no one to notify, so it ignores it.
        if time not in await self.available_slots(day):
            raise SlotUnavailable(f"{time} on {day} is not available")
        self._booked.setdefault(day, set()).add(time)
        event_id = f"evt_{uuid4().hex[:8]}"
        self._held[caller_number] = _Held(service, day, time, event_id)
        return event_id

    async def find_event(self, caller_number: str) -> str | None:
        held = self._held.get(caller_number)
        if held is None:
            return None
        return f"{held.service} on {held.day} at {held.time}"

    async def reschedule(self, caller_number: str, *, day: str, time: str) -> str:
        held = self._held.get(caller_number)
        if held is None:
            raise NoBooking("no existing booking for this caller")
        if time not in await self.available_slots(day):
            raise SlotUnavailable(f"{time} on {day} is not available")
        self._booked.get(held.day, set()).discard(held.time)
        self._booked.setdefault(day, set()).add(time)
        held.day, held.time = day, time
        return f"{held.service} on {day} at {time}"

    async def cancel(self, caller_number: str) -> str:
        held = self._held.pop(caller_number, None)
        if held is None:
            raise NoBooking("no existing booking for this caller")
        self._booked.get(held.day, set()).discard(held.time)
        return f"{held.service} on {held.day} at {held.time}"
