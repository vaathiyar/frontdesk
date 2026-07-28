"""Google Calendar v3 — the same `CalendarService` the fake implements.

Only profiles with a calendar ID in `RECEPTIONIST_CALENDAR_IDS` use this; everything
else stays on the fake, so local testing needs no calendar setup.

Auth is a **service account**: point `GOOGLE_CREDENTIALS_FILE_PATH` at its JSON key,
enable the Calendar API on it, and share each calendar with the service account's
email as "Make changes to events" — otherwise writes 403.

Every googleapiclient call is blocking, so each `.execute()` runs in a thread; a
stalled HTTP round-trip must not freeze the voice loop mid-sentence.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

from dateutil import parser as dateparser

from receptionist.services.calendar import (
    APPOINTMENT_MINUTES,
    Booked,
    NoBooking,
    SlotUnavailable,
    slot_grid,
)
from receptionist.services.when import fmt_time, resolve_date, resolve_datetime, timezone
from receptionist.settings import settings

SCOPES = ["https://www.googleapis.com/auth/calendar"]


def _build_client() -> Any:
    """Vendor imports stay local so importing this module doesn't pull in
    googleapiclient/google-auth for callers that only need the fake."""
    creds_path = settings.google_credentials_file_path
    if not creds_path:
        raise RuntimeError(
            "RECEPTIONIST_CALENDAR_IDS names a real Google Calendar, so "
            "GOOGLE_CREDENTIALS_FILE_PATH must point at a service-account JSON with the "
            "Calendar API enabled — or unset RECEPTIONIST_CALENDAR_IDS to use the fake."
        )

    from google.oauth2.service_account import Credentials
    from googleapiclient.discovery import build

    credentials = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    return build("calendar", "v3", credentials=credentials, cache_discovery=False)


class GoogleCalendarService:
    """One calendar per profile. `client` is injectable so tests drive it offline."""

    def __init__(self, calendar_id: str, *, client: Any | None = None) -> None:
        self._calendar_id = calendar_id
        self._tz = timezone()
        self._tzname = settings.timezone
        self._client = client if client is not None else _build_client()

    async def available_slots(self, day: str) -> list[str]:
        now = datetime.now(self._tz)
        candidates = [s for s in slot_grid(resolve_date(day, now.date())) if s > now]
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
