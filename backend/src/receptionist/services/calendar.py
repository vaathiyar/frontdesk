"""Booking, behind an interface, plus the in-memory fake the REPL and tests run on.

The fake enforces the guarantee in code: `create_event` refuses a time that isn't
open, so the agent cannot book over an existing appointment even if the model skips
checking availability first. Both backends build their openings from the same
`slot_grid` and the same profile hours, so what you see in the REPL is what a real
calendar would offer — the two disagreeing is the bug this arrangement exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable
from uuid import uuid4

if TYPE_CHECKING:
    # Import-time only: `receptionist.profiles` pulls in the tools, which import this
    # module, so importing Profile for real here would be a cycle.
    from receptionist.profiles import Profile

from receptionist.services.when import fmt_time, resolve_datetime, spoken, timezone

# Default business hours — a trades day. Hours differ per business, so a profile sets its
# own (`Profile.opens` / `Profile.closes`); a restaurant taking 7pm reservations does not
# share a furnace shop's 8-to-6.
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


def slot_grid(on: date, open_hour: int = OPEN_HOUR, close_hour: int = CLOSE_HOUR) -> list[datetime]:
    """Candidate start times on `on` whose appointment still ends by closing."""
    tz = timezone()
    opens = datetime.combine(on, time(open_hour), tzinfo=tz)
    closes = datetime.combine(on, time(close_hour), tzinfo=tz)
    starts, cursor = [], opens
    while cursor + timedelta(minutes=APPOINTMENT_MINUTES) <= closes:
        starts.append(cursor)
        cursor += timedelta(minutes=SLOT_MINUTES)
    return starts


@dataclass
class FakeCalendarService:
    """In-memory calendar, one active appointment per caller number.

    Seeds tomorrow's first opening as busy so a demo call visibly declines a taken time —
    the most convincing thing to show a prospect.
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
        from receptionist.services.when import resolve_date

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


def build_calendar(profile: Profile) -> CalendarService:
    """The real Google Calendar when this profile has one configured, else the fake.

    Either way it books inside the profile's own hours. The Google import stays lazy so
    the offline path never loads googleapiclient.
    """
    from receptionist.settings import settings

    calendar_id = settings.calendar_ids.get(profile.id)
    if not calendar_id:
        return FakeCalendarService(profile.opens, profile.closes)

    from receptionist.services.google_calendar import GoogleCalendarService

    return GoogleCalendarService(calendar_id, open_hour=profile.opens, close_hour=profile.closes)
