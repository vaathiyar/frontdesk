"""Turning what the caller said about time into real datetimes, and back into words.

Both calendar backends resolve `day` + `time` through here, so the fake and Google
agree on what "tomorrow at 10" means. The prompt asks the model for ISO dates, but
the natural-language fallbacks stay: a model that slips, or a human typing into the
dev REPL, should still be understood rather than dropped.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from dateutil.parser import ParserError

from receptionist.settings import settings

_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
# Accepted but not distinguished: a weekday name always means its next occurrence.
_QUALIFIERS = {"next", "this", "coming", "on"}

# Time-only parsing anchor: if dateutil moves the date off this, the input was
# date-like (a bare "10" reads as day-of-month), not a time.
_TIME_ANCHOR = datetime(2000, 1, 1, 0, 0)


def timezone() -> ZoneInfo:
    return ZoneInfo(settings.timezone)


def fmt_time(when: datetime | time) -> str:
    """`"2:05 PM"` — no leading zero, matching how open times are listed."""
    suffix = "AM" if when.hour < 12 else "PM"
    return f"{when.hour % 12 or 12}:{when.minute:02d} {suffix}"


def pretty_day(day: str) -> str:
    """`"2026-07-29"` -> `"Wednesday, July 29"`, so nothing is ever read out as digits.

    Anything that isn't an ISO date passes straight through.
    """
    try:
        parsed = date.fromisoformat(day.strip())
    except ValueError:
        return day
    return f"{parsed:%A}, {parsed:%B} {parsed.day}"


def spoken(when: datetime) -> str:
    """How the agent should say a booked appointment back to the caller."""
    return f"{when:%A}, {when:%B} {when.day} at {fmt_time(when)}"


def describe_now(now: datetime | None = None) -> str:
    """The prompt's date anchor.

    Today's and tomorrow's ISO dates are both spelled out, because "tomorrow" is by far
    the most common thing a caller says and models get the arithmetic wrong — one
    observed call booked today at 8am for a caller who had asked for tomorrow morning.
    Handing over both dates removes the calculation instead of trusting it.
    """
    current = now or datetime.now(timezone())
    tomorrow = current + timedelta(days=1)
    return (
        f"{current:%A}, {current:%B} {current.day}, {current.year} "
        f"at {fmt_time(current)} ({settings.timezone}). "
        f"Today's date is {current:%Y-%m-%d} and tomorrow's is {tomorrow:%Y-%m-%d}"
    )


def resolve_date(day: str, today: date) -> date:
    """ "today" / "tomorrow" / a weekday / an explicit date -> a calendar date."""
    text = " ".join(day.strip().lower().split())
    if not text:
        raise ValueError("No day was given.")
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)

    tokens = text.split()
    if len(tokens) > 1 and tokens[0] in _QUALIFIERS:
        text = " ".join(tokens[1:])
    if text in _WEEKDAYS:
        ahead = (_WEEKDAYS[text] - today.weekday()) % 7 or 7
        return today + timedelta(days=ahead)

    try:
        return dateparser.parse(day, default=datetime.combine(today, time())).date()
    except (ParserError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"I couldn't understand the day '{day}'. Try 'tomorrow', a weekday, or a date."
        ) from exc


def resolve_time(value: str) -> time:
    """ "10:00 AM" / "10am" / "14:00" -> a time of day."""
    text = value.strip()
    if not text:
        raise ValueError("No time was given.")
    unreadable = ValueError(f"I couldn't understand the time '{value}'. Try '10:00 AM'.")
    try:
        parsed = dateparser.parse(text, default=_TIME_ANCHOR)
    except (ParserError, ValueError, OverflowError) as exc:
        raise unreadable from exc
    if parsed.date() != _TIME_ANCHOR.date():
        raise unreadable
    return parsed.time()


def resolve_datetime(day: str, clock: str, *, tz: tzinfo, now: datetime | None = None) -> datetime:
    """`day` + `time` -> a timezone-aware start.

    A bare weekday resolves to its next upcoming occurrence and never to today (say
    "today" for that). Combining with `tzinfo=` lets ZoneInfo pick the right DST
    offset for the wall-clock time. Unparseable input raises ValueError, which the
    tools hand back to the model as something to ask the caller about.
    """
    anchor = now or datetime.now(tz)
    return datetime.combine(resolve_date(day, anchor.date()), resolve_time(clock), tzinfo=tz)
