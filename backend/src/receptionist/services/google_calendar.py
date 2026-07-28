"""Real calendar backend: Google Calendar v3, satisfying the same `CalendarService`
Protocol as the in-memory fake.

Only profiles with a Google Calendar ID configured (`RECEPTIONIST_CALENDAR_IDS`) use this;
everything else keeps using `FakeCalendarService`, so local `console` testing needs zero
calendar setup. The factory imports this module lazily, and the googleapiclient/google-auth
imports live inside `_build_client`, so the text/test path never pulls in those heavy vendor
deps — and the client is injectable (`client=`) so the tests drive it fully offline.

Auth: a **service account**. Point `GOOGLE_CREDENTIALS_FILE_PATH` at its JSON key. The
service account must have the **Google Calendar API enabled**, and each target calendar must
be **shared with the service account's email** with "Make changes to events" — otherwise
inserts/patches/deletes 403.

The booking is created on the business calendar only. Google refuses to let a plain service
account invite `attendees` (403 forbiddenForServiceAccounts) without Domain-Wide Delegation,
so the caller's email is *recorded on the event* rather than invited — their own invite is
emailed separately as an .ics.

All googleapiclient calls are blocking, so each `.execute()` is wrapped in
`asyncio.to_thread(...)` to keep the real-time voice loop from stalling.
"""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any
from zoneinfo import ZoneInfo

from dateutil import parser as dateparser
from dateutil.parser import ParserError

from receptionist.core.settings import settings
from receptionist.services.calendar import NoBooking, SlotUnavailable

# --- Business hours / slots (code constants, like the STT/TTS params in providers/factory) ---
# The calendar reasons on an OPEN_HOUR..CLOSE_HOUR grid in the configured timezone; every
# appointment is APPOINTMENT_MINUTES long and candidate starts are SLOT_MINUTES apart.
OPEN_HOUR = 8  # first appointment starts at 08:00
CLOSE_HOUR = 18  # last appointment must *end* by 18:00
SLOT_MINUTES = 60  # spacing between candidate start times
APPOINTMENT_MINUTES = 60  # length of a booked appointment

# OAuth scope: read + write events on the shared calendars.
SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Weekday name -> Python weekday index (Monday == 0), matching datetime.weekday().
_WEEKDAYS = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
# Qualifiers we accept but do not distinguish: a weekday name always resolves to its next
# upcoming occurrence (see resolve_datetime's docstring for the rationale/limits).
_DAY_QUALIFIERS = {"next", "this", "coming", "on"}

# A fixed sentinel date for time-only parsing: if dateutil moves the date off this, the
# string wasn't a plain time (e.g. a bare "10" is read as day-of-month) -> reject it.
_TIME_SENTINEL = datetime(2000, 1, 1, 0, 0)


def _fmt_time(dt: datetime | time) -> str:
    """Format a time the way the fake does: `"8:00 AM"`, `"1:00 PM"` (no leading zero)."""
    hour24 = dt.hour
    minute = dt.minute
    suffix = "AM" if hour24 < 12 else "PM"
    hour12 = hour24 % 12 or 12
    return f"{hour12}:{minute:02d} {suffix}"


def _resolve_date(day: str, today: date) -> date:
    """Resolve a natural `day` string to a calendar date, relative to `today`.

    Handles "today"/"tomorrow", weekday names (optionally with a "next"/"this"/"coming"
    qualifier), and explicit dates (via dateutil). Raises ValueError on anything else.
    """
    text = " ".join(day.strip().lower().split())
    if not text:
        raise ValueError("No day was given.")
    if text == "today":
        return today
    if text == "tomorrow":
        return today + timedelta(days=1)

    # Optional leading qualifier ("next Monday", "this Friday"); we accept it but treat a
    # weekday name as its next upcoming occurrence regardless.
    tokens = text.split()
    if len(tokens) > 1 and tokens[0] in _DAY_QUALIFIERS:
        text = " ".join(tokens[1:])
    if text in _WEEKDAYS:
        days_ahead = (_WEEKDAYS[text] - today.weekday()) % 7 or 7
        return today + timedelta(days=days_ahead)

    # Explicit calendar date. `default=` fills in a missing year from today.
    try:
        return dateparser.parse(day, default=datetime.combine(today, time())).date()
    except (ParserError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"I couldn't understand the day '{day}'. Try 'tomorrow', a weekday, or a date."
        ) from exc


def _resolve_time(value: str) -> time:
    """Resolve a natural `time` string ("10:00 AM", "10am", "14:00") to a time-of-day.

    Raises ValueError on anything that isn't a plain time.
    """
    text = value.strip()
    if not text:
        raise ValueError("No time was given.")
    try:
        parsed = dateparser.parse(text, default=_TIME_SENTINEL)
    except (ParserError, ValueError, OverflowError) as exc:
        raise ValueError(
            f"I couldn't understand the time '{value}'. Try something like '10:00 AM'."
        ) from exc
    # If parsing shifted the date, the input was date-like (e.g. bare "10"), not a time.
    if parsed.date() != _TIME_SENTINEL.date():
        raise ValueError(
            f"I couldn't understand the time '{value}'. Try something like '10:00 AM'."
        )
    return parsed.time()


def resolve_datetime(
    day: str, time: str, *, tz: tzinfo, now: datetime | None = None
) -> datetime:
    """Pure resolver: turn the brain's natural `day` + `time` into a timezone-aware start.

    - `day`: "today", "tomorrow", a weekday ("Tuesday", "next Monday"), or an explicit date.
    - `time`: "10:00 AM", "10am", "14:00", "2:30 pm", ...
    - Result is aware in `tz`; `now` (defaults to `datetime.now(tz)`) anchors relative days.

    Semantics / limits: a bare weekday resolves to its *next upcoming* occurrence and never
    to today (use "today" for that); the "next"/"this" qualifier is accepted but not
    distinguished, so "Tuesday" and "next Tuesday" mean the same day. Combining via
    `datetime.combine(..., tzinfo=tz)` lets ZoneInfo pick the correct DST offset for the
    wall-clock time. Unparseable input raises ValueError (the tool surfaces it to the caller).
    """
    if now is None:
        now = datetime.now(tz)
    resolved_date = _resolve_date(day, now.date())
    resolved_time = _resolve_time(time)
    return datetime.combine(resolved_date, resolved_time, tzinfo=tz)


def _build_client() -> Any:
    """Build the Calendar v3 client from the service-account JSON. Vendor imports are kept
    local so importing this module never pulls in googleapiclient/google-auth."""
    creds_path = settings.google_credentials_file_path
    if not creds_path:
        raise RuntimeError(
            "No service-account credentials: set GOOGLE_CREDENTIALS_FILE_PATH to the path "
            "of the service-account JSON (with the Calendar API enabled). It's required "
            "because RECEPTIONIST_CALENDAR_IDS configures a real Google Calendar — or unset "
            "RECEPTIONIST_CALENDAR_IDS to fall back to the in-memory fake."
        )

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    # cache_discovery=False avoids a noisy warning and a file-cache write we don't need.
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


class GoogleCalendarService:
    """Google Calendar v3 implementation of `CalendarService` (one calendar per profile).

    The client is injectable so tests can drive every method against a stub with no network;
    it's built lazily from `GOOGLE_CREDENTIALS_FILE_PATH` only when `client is None`.
    """

    def __init__(self, calendar_id: str, timezone: str, *, client: Any | None = None) -> None:
        self._calendar_id = calendar_id
        self._tzname = timezone
        self._tz = ZoneInfo(timezone)
        self._client = client if client is not None else _build_client()

    # --- helpers -----------------------------------------------------------------
    def _now(self) -> datetime:
        return datetime.now(self._tz)

    def _iso(self, dt: datetime) -> dict[str, str]:
        return {"dateTime": dt.isoformat(), "timeZone": self._tzname}

    def _describe(self, event: dict[str, Any]) -> str:
        """Human, spoken-friendly description, mirroring the fake's `service on day at time`."""
        summary = event.get("summary") or "your appointment"
        start_raw = (event.get("start") or {}).get("dateTime")
        if not start_raw:
            return summary
        start = dateparser.isoparse(start_raw).astimezone(self._tz)
        return f"{summary} on {start:%A %B %-d} at {_fmt_time(start)}"

    async def _busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        """freebusy() busy intervals overlapping [start, end) on this calendar."""
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": self._tzname,
            "items": [{"id": self._calendar_id}],
        }
        result = await asyncio.to_thread(lambda: self._client.freebusy().query(body=body).execute())
        busy = result["calendars"][self._calendar_id]["busy"]
        return [(dateparser.isoparse(b["start"]), dateparser.isoparse(b["end"])) for b in busy]

    async def _is_free(self, start: datetime, end: datetime) -> bool:
        for busy_start, busy_end in await self._busy(start, end):
            if start < busy_end and busy_start < end:  # half-open overlap; adjacencies are OK
                return False
        return True

    async def _events_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        """Expanded events overlapping [start, end) — used to detect conflicts while excluding
        the caller's own event on reschedule (freebusy has no event ids)."""
        result = await asyncio.to_thread(
            lambda: self._client.events()
            .list(
                calendarId=self._calendar_id,
                timeMin=start.isoformat(),
                timeMax=end.isoformat(),
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return list(result.get("items", []))

    async def _find_raw(self, caller_number: str) -> dict[str, Any] | None:
        """The caller's next upcoming event, matched by the private extended property we
        stamp on every booking."""
        result = await asyncio.to_thread(
            lambda: self._client.events()
            .list(
                calendarId=self._calendar_id,
                privateExtendedProperty=f"caller_number={caller_number}",
                timeMin=self._now().isoformat(),
                singleEvents=True,
                orderBy="startTime",
                maxResults=10,
            )
            .execute()
        )
        items = result.get("items", [])
        return items[0] if items else None

    # --- CalendarService Protocol ------------------------------------------------
    async def available_slots(self, day: str) -> list[str]:
        now = self._now()
        target = _resolve_date(day, now.date())
        day_start = datetime.combine(target, time(OPEN_HOUR, 0), tzinfo=self._tz)
        day_end = datetime.combine(target, time(CLOSE_HOUR, 0), tzinfo=self._tz)

        # Candidate starts on the grid whose appointment still ends by CLOSE_HOUR.
        candidates: list[datetime] = []
        cursor = day_start
        while cursor + timedelta(minutes=APPOINTMENT_MINUTES) <= day_end:
            if cursor > now:  # drop past times (only bites when `day` is today)
                candidates.append(cursor)
            cursor += timedelta(minutes=SLOT_MINUTES)
        if not candidates:
            return []

        busy = await self._busy(day_start, day_end)
        free = []
        for start in candidates:
            end = start + timedelta(minutes=APPOINTMENT_MINUTES)
            if all(not (start < b_end and b_start < end) for b_start, b_end in busy):
                free.append(_fmt_time(start))
        return free

    async def create_event(
        self,
        caller_number: str,
        *,
        service: str,
        day: str,
        time: str,
        attendee_email: str | None = None,
    ) -> str:
        start = resolve_datetime(day, time, tz=self._tz)
        end = start + timedelta(minutes=APPOINTMENT_MINUTES)
        if not await self._is_free(start, end):
            raise SlotUnavailable(f"{time} on {day} is not available")

        details = [f"Booked by phone from {caller_number}."]
        if attendee_email:
            details.append(f"Caller email: {attendee_email}")

        body: dict[str, Any] = {
            "summary": service,
            "start": self._iso(start),
            "end": self._iso(end),
            "description": "\n".join(details),
            # Stamp the caller number so we can find/reschedule/cancel this booking later.
            "extendedProperties": {"private": {"caller_number": caller_number}},
        }
        if attendee_email:
            # Deliberately NOT an `attendees` entry: Google 403s that for a service account
            # without Domain-Wide Delegation. Keeping the address on the event lets the owner
            # see it and gives the .ics invite email somewhere to read it from.
            body["extendedProperties"]["private"]["caller_email"] = attendee_email

        created = await asyncio.to_thread(
            # sendUpdates is a no-op while there are no attendees; it's kept so guest
            # notifications resume automatically if invites are ever enabled via DWD.
            lambda: self._client.events()
            .insert(calendarId=self._calendar_id, body=body, sendUpdates="all")
            .execute()
        )
        return str(created["id"])

    async def find_event(self, caller_number: str) -> str | None:
        event = await self._find_raw(caller_number)
        return self._describe(event) if event else None

    async def reschedule(self, caller_number: str, *, day: str, time: str) -> str:
        event = await self._find_raw(caller_number)
        if event is None:
            raise NoBooking("no existing booking for this caller")

        start = resolve_datetime(day, time, tz=self._tz)
        end = start + timedelta(minutes=APPOINTMENT_MINUTES)
        # Conflict check excluding the caller's own event (freebusy can't tell them apart).
        for other in await self._events_between(start, end):
            if other.get("id") == event.get("id"):
                continue
            o_start = dateparser.isoparse(other["start"]["dateTime"])
            o_end = dateparser.isoparse(other["end"]["dateTime"])
            if start < o_end and o_start < end:
                raise SlotUnavailable(f"{time} on {day} is not available")

        patched = await asyncio.to_thread(
            lambda: self._client.events()
            .patch(
                calendarId=self._calendar_id,
                eventId=event["id"],
                body={"start": self._iso(start), "end": self._iso(end)},
                sendUpdates="all",
            )
            .execute()
        )
        return self._describe(patched)

    async def cancel(self, caller_number: str) -> str:
        event = await self._find_raw(caller_number)
        if event is None:
            raise NoBooking("no existing booking for this caller")
        await asyncio.to_thread(
            lambda: self._client.events()
            .delete(calendarId=self._calendar_id, eventId=event["id"], sendUpdates="all")
            .execute()
        )
        return self._describe(event)
