"""Booking, behind an interface.

`CalendarService` is what the tools book through; `GoogleCalendarService` is the one
implementation. There is no in-memory fallback: a profile whose calendar is not
configured refuses to start, rather than accepting bookings that quietly go nowhere.
The suite supplies its own double (`tests/support/fake_calendar.py`).

The slot grid lives here rather than in the Google adapter because it is business policy,
not vendor plumbing — how long an appointment runs and when the last one can start.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    # Import-time only: `receptionist.worker.profiles` pulls in the tools, which import this
    # module, so importing Profile for real here would be a cycle.
    from receptionist.worker.profiles import Profile

from receptionist.settings import settings
from receptionist.worker.lib.datetimes import spoken, timezone

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


class CalendarNotConfigured(RuntimeError):
    """A profile has no Google Calendar to book into."""


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


def require_calendar_ids(profile_ids: Iterable[str]) -> None:
    """Refuse to start unless every profile has a calendar to book into.

    Checked once at worker startup rather than at the first booking: a caller listening to
    the agent fail mid-sentence is the worst possible place to discover a missing id.

    The keys are matched exactly, so the overwhelmingly likely cause of a failure here is a
    misspelled profile id. Unrecognised keys are named for that reason — "restaurant is
    missing" sends you looking at the deployment; "restaurant is missing and you wrote
    restraunt" is the actual answer. Only keys are shown, never calendar ids.
    """
    wanted = set(profile_ids)
    missing = sorted(p for p in wanted if not settings.calendar_ids.get(p))
    if not missing:
        return

    unknown = sorted(set(settings.calendar_ids) - wanted)
    hint = (
        f" It does name {', '.join(unknown)}, which is not a registered profile — "
        "check the spelling."
        if unknown
        else " It must map every registered profile to a calendar id."
    )
    raise CalendarNotConfigured(
        f"RECEPTIONIST_CALENDAR_IDS has no Google Calendar for: {', '.join(missing)}.{hint}"
    )


def build_calendar(profile: Profile) -> CalendarService:
    """This profile's calendar, booking inside its own hours.

    The Google import stays lazy so importing this module doesn't drag googleapiclient
    into processes that never book anything.
    """
    calendar_id = settings.calendar_ids.get(profile.id)
    if not calendar_id:
        raise CalendarNotConfigured(
            f"No Google Calendar configured for profile {profile.id!r}. "
            "Add it to RECEPTIONIST_CALENDAR_IDS."
        )

    from receptionist.worker.booking.google import GoogleCalendarService

    return GoogleCalendarService(calendar_id, open_hour=profile.opens, close_hour=profile.closes)
