"""Google Calendar v3 — the one `CalendarService` in production.

Every profile books through this, against the calendar named for it in
`RECEPTIONIST_CALENDAR_IDS`; the worker refuses to start if one is missing.

Auth is a **service account**: supply its key as `GOOGLE_CREDENTIALS_JSON` or point
`GOOGLE_CREDENTIALS_FILE_PATH` at the file, enable the Calendar API on it, and share each
calendar with the service account's email as "Make changes to events" — otherwise writes
403.

Every googleapiclient call is blocking, so each `.execute()` runs in a thread; a
stalled HTTP round-trip must not freeze the voice loop mid-sentence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

from receptionist.settings import settings
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
from receptionist.worker.lib.google_auth import service_account_credentials

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _build_client() -> Any:
    """Vendor imports stay local so importing this module doesn't pull in
    googleapiclient for callers that never book anything."""
    credentials = service_account_credentials(SCOPES)
    if credentials is None:
        raise RuntimeError(
            "Booking needs a Google service account: GOOGLE_CREDENTIALS_JSON must hold a "
            "service-account JSON with the Calendar API enabled, or "
            "GOOGLE_CREDENTIALS_FILE_PATH must point at one."
        )

    from googleapiclient.discovery import build

    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


class GoogleCalendarService:
    """One calendar per profile. `client` is injectable so tests drive it offline."""

    def __init__(
        self,
        calendar_id: str,
        *,
        open_hour: int = OPEN_HOUR,
        close_hour: int = CLOSE_HOUR,
        client: Any | None = None,
    ) -> None:
        self._calendar_id = calendar_id
        self._open_hour = open_hour
        self._close_hour = close_hour
        self._tz = timezone()
        self._tzname = settings.timezone
        self._client = client if client is not None else _build_client()

    async def available_slots(self, day: str) -> list[str]:
        now = datetime.now(self._tz)
        grid = slot_grid(resolve_date(day, now.date()), self._open_hour, self._close_hour)
        candidates = [s for s in grid if s > now]
        if not candidates:
            return []
        busy = await self._busy(candidates[0], candidates[-1] + self._length)
        return [fmt_time(s) for s in candidates if self._free_at(s, busy)]

    async def create_event(
        self, caller_number: str, *, service: str, day: str, time: str
    ) -> Booked:
        starts_at = resolve_datetime(day, time, tz=self._tz)
        ends_at = starts_at + self._length
        if not self._free_at(starts_at, await self._busy(starts_at, ends_at)):
            raise SlotUnavailable(f"{time} on {day} is not available")

        body = {
            "summary": service,
            "start": self._when(starts_at),
            "end": self._when(ends_at),
            "description": f"Booked by phone from {caller_number}.",
            # Stamped so reschedule/cancel can find this caller's appointment later.
            "extendedProperties": {"private": {"caller_number": caller_number}},
        }
        created = await asyncio.to_thread(
            lambda: self._client.events().insert(calendarId=self._calendar_id, body=body).execute()
        )
        return Booked(str(created["id"]), service, starts_at, ends_at)

    async def reschedule(self, caller_number: str, *, day: str, time: str) -> Booked:
        event = await self._find(caller_number)
        if event is None:
            raise NoBooking("no existing booking for this caller")

        starts_at = resolve_datetime(day, time, tz=self._tz)
        ends_at = starts_at + self._length
        # Conflict check that ignores the caller's own event — freebusy can't tell
        # events apart, so this walks the actual event list instead.
        for other in await self._events_between(starts_at, ends_at):
            if other.get("id") != event.get("id") and self._overlaps(other, starts_at, ends_at):
                raise SlotUnavailable(f"{time} on {day} is not available")

        await asyncio.to_thread(
            lambda: (
                self._client.events()
                .patch(
                    calendarId=self._calendar_id,
                    eventId=event["id"],
                    body={"start": self._when(starts_at), "end": self._when(ends_at)},
                )
                .execute()
            )
        )
        return Booked(str(event["id"]), self._service_of(event), starts_at, ends_at)

    async def cancel(self, caller_number: str) -> str:
        event = await self._find(caller_number)
        if event is None:
            raise NoBooking("no existing booking for this caller")
        await asyncio.to_thread(
            lambda: (
                self._client.events()
                .delete(calendarId=self._calendar_id, eventId=event["id"])
                .execute()
            )
        )
        starts_at = dateparser.isoparse(event["start"]["dateTime"]).astimezone(self._tz)
        return Booked(str(event["id"]), self._service_of(event), starts_at, starts_at).spoken()

    # --- Google plumbing ---------------------------------------------------------

    @property
    def _length(self) -> timedelta:
        return timedelta(minutes=APPOINTMENT_MINUTES)

    def _when(self, dt: datetime) -> dict[str, str]:
        return {"dateTime": dt.isoformat(), "timeZone": self._tzname}

    @staticmethod
    def _service_of(event: dict[str, Any]) -> str:
        return str(event.get("summary") or "your appointment")

    async def _busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        body = {
            "timeMin": start.isoformat(),
            "timeMax": end.isoformat(),
            "timeZone": self._tzname,
            "items": [{"id": self._calendar_id}],
        }
        result = await asyncio.to_thread(lambda: self._client.freebusy().query(body=body).execute())
        return [
            (dateparser.isoparse(b["start"]), dateparser.isoparse(b["end"]))
            for b in result["calendars"][self._calendar_id]["busy"]
        ]

    def _free_at(self, start: datetime, busy: list[tuple[datetime, datetime]]) -> bool:
        end = start + self._length
        # Half-open comparison: an appointment ending exactly when another starts is fine.
        return all(not (start < b_end and b_start < end) for b_start, b_end in busy)

    def _overlaps(self, event: dict[str, Any], start: datetime, end: datetime) -> bool:
        other_start = dateparser.isoparse(event["start"]["dateTime"])
        other_end = dateparser.isoparse(event["end"]["dateTime"])
        return start < other_end and other_start < end

    async def _events_between(self, start: datetime, end: datetime) -> list[dict[str, Any]]:
        result = await asyncio.to_thread(
            lambda: (
                self._client.events()
                .list(
                    calendarId=self._calendar_id,
                    timeMin=start.isoformat(),
                    timeMax=end.isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                )
                .execute()
            )
        )
        return list(result.get("items", []))

    async def _find(self, caller_number: str) -> dict[str, Any] | None:
        """The caller's next upcoming appointment, by the property we stamp on booking."""
        result = await asyncio.to_thread(
            lambda: (
                self._client.events()
                .list(
                    calendarId=self._calendar_id,
                    privateExtendedProperty=f"caller_number={caller_number}",
                    timeMin=datetime.now(self._tz).isoformat(),
                    singleEvents=True,
                    orderBy="startTime",
                    maxResults=10,
                )
                .execute()
            )
        )
        items = result.get("items", [])
        return dict(items[0]) if items else None
