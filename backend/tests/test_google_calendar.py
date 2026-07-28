"""GoogleCalendarService tests — fully offline.

Two halves: (1) the pure `resolve_datetime` resolver across day/time cases, and
(2) the service driven end-to-end against an in-memory fake Calendar client that stubs the
`freebusy().query()` and `events()` surfaces — no network, no google-auth/googleapiclient.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from dateutil.parser import isoparse

from receptionist.services.calendar import NoBooking, SlotUnavailable
from receptionist.services.google_calendar import (
    CLOSE_HOUR,
    OPEN_HOUR,
    GoogleCalendarService,
    resolve_datetime,
)

TZ = ZoneInfo("America/Vancouver")
NOW = datetime(2026, 7, 26, 9, 0, tzinfo=TZ)  # a Sunday — anchors the resolver tests


# ---------------------------------------------------------------- resolver (pure) --
def test_resolver_tomorrow_is_aware_and_keeps_time() -> None:
    dt = resolve_datetime("tomorrow", "10:00 AM", tz=TZ, now=NOW)
    assert (dt.year, dt.month, dt.day) == (2026, 7, 27)
    assert (dt.hour, dt.minute) == (10, 0)
    assert dt.tzinfo is not None
    assert dt.utcoffset() == timedelta(hours=-7)  # PDT in July (DST resolved by ZoneInfo)


def test_resolver_accepts_iso_dates() -> None:
    # The contract the tool schemas now advertise: the model resolves the caller's phrasing
    # and sends an absolute YYYY-MM-DD date.
    dt = resolve_datetime("2026-07-29", "12:00 PM", tz=TZ, now=NOW)
    assert (dt.year, dt.month, dt.day) == (2026, 7, 29)
    assert (dt.hour, dt.minute) == (12, 0)


def test_resolver_weekday_is_next_upcoming() -> None:
    # NOW is Sunday 2026-07-26 -> the coming Tuesday is 2026-07-28.
    dt = resolve_datetime("Tuesday", "2pm", tz=TZ, now=NOW)
    assert (dt.month, dt.day, dt.hour) == (7, 28, 14)


def test_resolver_next_qualifier_and_never_today() -> None:
    # "next Monday" from Sunday -> tomorrow (2026-07-27).
    assert resolve_datetime("next Monday", "9:00 AM", tz=TZ, now=NOW).day == 27
    # A bare weekday matching today resolves to next week, never today.
    assert resolve_datetime("Sunday", "9:00 AM", tz=TZ, now=NOW).day == 2  # 2026-08-02


@pytest.mark.parametrize(
    "text,hour,minute",
    [("10am", 10, 0), ("10:00 AM", 10, 0), ("2:30 PM", 14, 30), ("14:00", 14, 0)],
)
def test_resolver_time_formats(text: str, hour: int, minute: int) -> None:
    dt = resolve_datetime("today", text, tz=TZ, now=NOW)
    assert (dt.hour, dt.minute) == (hour, minute)


def test_resolver_explicit_date() -> None:
    dt = resolve_datetime("2026-07-30", "11:00 AM", tz=TZ, now=NOW)
    assert (dt.month, dt.day) == (7, 30)


@pytest.mark.parametrize(
    "day,clock",
    [("someday", "10am"), ("today", "half past ten"), ("", "10am"), ("today", ""), ("today", "10")],
)
def test_resolver_bad_input_raises(day: str, clock: str) -> None:
    with pytest.raises(ValueError):
        resolve_datetime(day, clock, tz=TZ, now=NOW)


# ---------------------------------------------- offline fake Calendar v3 client ----
class _Req:
    """A googleapiclient-style request: built cheaply, blocks on `.execute()`."""

    def __init__(self, fn: Any) -> None:
        self._fn = fn

    def execute(self) -> Any:
        return self._fn()


class _Store:
    """In-memory event store shared by the events/freebusy collections."""

    def __init__(self) -> None:
        self.events: dict[str, dict[str, Any]] = {}
        self.inserts: list[dict[str, Any]] = []  # records body+sendUpdates for assertions
        self._seq = 0

    def insert(self, body: dict[str, Any], send_updates: str | None) -> dict[str, Any]:
        self._seq += 1
        event = {**body, "id": f"evt{self._seq}"}
        self.events[event["id"]] = event
        self.inserts.append({"body": event, "sendUpdates": send_updates})
        return event

    def list(
        self, time_min: str | None, time_max: str | None, private_ext: str | None
    ) -> list[dict[str, Any]]:
        items = list(self.events.values())
        if private_ext:
            key, _, val = private_ext.partition("=")
            items = [
                e
                for e in items
                if e.get("extendedProperties", {}).get("private", {}).get(key) == val
            ]
        lo = isoparse(time_min) if time_min else None
        hi = isoparse(time_max) if time_max else None
        out = []
        for e in items:
            start, end = isoparse(e["start"]["dateTime"]), isoparse(e["end"]["dateTime"])
            if lo is not None and end <= lo:
                continue
            if hi is not None and start >= hi:
                continue
            out.append(e)
        out.sort(key=lambda e: e["start"]["dateTime"])
        return out

    def patch(self, event_id: str, body: dict[str, Any]) -> dict[str, Any]:
        self.events[event_id].update(body)
        return self.events[event_id]

    def delete(self, event_id: str) -> str:
        self.events.pop(event_id, None)
        return ""

    def freebusy(self, body: dict[str, Any]) -> dict[str, Any]:
        cal_id = body["items"][0]["id"]
        lo, hi = isoparse(body["timeMin"]), isoparse(body["timeMax"])
        busy = [
            {"start": e["start"]["dateTime"], "end": e["end"]["dateTime"]}
            for e in self.events.values()
            if isoparse(e["start"]["dateTime"]) < hi and lo < isoparse(e["end"]["dateTime"])
        ]
        return {"calendars": {cal_id: {"busy": busy}}}


class _Events:
    # kwargs mirror the googleapiclient names (camelCase) the service calls with.
    def __init__(self, store: _Store) -> None:
        self._s = store

    def insert(
        self, *, calendarId: str, body: dict[str, Any], sendUpdates: str | None = None
    ) -> _Req:
        return _Req(lambda: self._s.insert(body, sendUpdates))

    def list(
        self,
        *,
        calendarId: str,
        timeMin: str | None = None,
        timeMax: str | None = None,
        privateExtendedProperty: str | None = None,
        singleEvents: bool | None = None,
        orderBy: str | None = None,
        maxResults: int | None = None,
    ) -> _Req:
        return _Req(lambda: {"items": self._s.list(timeMin, timeMax, privateExtendedProperty)})

    def patch(
        self, *, calendarId: str, eventId: str, body: dict[str, Any], sendUpdates: str | None = None
    ) -> _Req:
        return _Req(lambda: self._s.patch(eventId, body))

    def delete(self, *, calendarId: str, eventId: str, sendUpdates: str | None = None) -> _Req:
        return _Req(lambda: self._s.delete(eventId))


class _Freebusy:
    def __init__(self, store: _Store) -> None:
        self._s = store

    def query(self, *, body: dict[str, Any]) -> _Req:
        return _Req(lambda: self._s.freebusy(body))


class FakeCalendarClient:
    """Stand-in for the Calendar v3 client; one shared store across collection calls."""

    def __init__(self) -> None:
        self.store = _Store()

    def events(self) -> _Events:
        return _Events(self.store)

    def freebusy(self) -> _Freebusy:
        return _Freebusy(self.store)


def _service() -> tuple[GoogleCalendarService, FakeCalendarClient]:
    client = FakeCalendarClient()
    return GoogleCalendarService("cal-1", "America/Vancouver", client=client), client


# ----------------------------------------------------------- service (fake client) --
async def test_available_slots_grid() -> None:
    svc, _ = _service()
    slots = await svc.available_slots("tomorrow")  # a full future day: nothing dropped
    # Hourly starts 08:00..17:00 (17:00 + 60min == 18:00 close) -> 10 open slots.
    assert slots[0] == "8:00 AM"
    assert slots[-1] == "5:00 PM"
    assert len(slots) == CLOSE_HOUR - OPEN_HOUR
    assert "6:00 PM" not in slots


async def test_create_event_records_caller_email_without_inviting() -> None:
    # Google 403s `attendees` for a service account without Domain-Wide Delegation, so the
    # address is recorded on the event instead — never sent as an invite.
    svc, client = _service()
    eid = await svc.create_event(
        "+1",
        service="Furnace repair",
        day="tomorrow",
        time="10:00 AM",
        attendee_email="caller@example.com",
    )
    assert eid
    assert "10:00 AM" not in await svc.available_slots("tomorrow")
    body = client.store.inserts[-1]["body"]
    assert "attendees" not in body
    private = body["extendedProperties"]["private"]
    assert private["caller_number"] == "+1"
    assert private["caller_email"] == "caller@example.com"
    assert "caller@example.com" in body["description"]


async def test_create_event_without_email_still_books() -> None:
    svc, client = _service()
    await svc.create_event("+1", service="a", day="tomorrow", time="11:00 AM")
    body = client.store.inserts[-1]["body"]
    assert "attendees" not in body
    assert "caller_email" not in body["extendedProperties"]["private"]


async def test_create_event_on_busy_slot_raises() -> None:
    svc, _ = _service()
    await svc.create_event("+1", service="a", day="tomorrow", time="10:00 AM")
    with pytest.raises(SlotUnavailable):
        await svc.create_event("+2", service="b", day="tomorrow", time="10:00 AM")


async def test_find_event_none_then_present() -> None:
    svc, _ = _service()
    assert await svc.find_event("+1") is None
    await svc.create_event("+1", service="Furnace repair", day="tomorrow", time="10:00 AM")
    desc = await svc.find_event("+1")
    assert desc is not None and "Furnace repair" in desc


async def test_reschedule_moves_and_frees_old_slot() -> None:
    svc, _ = _service()
    await svc.create_event("+1", service="repair", day="tomorrow", time="10:00 AM")
    desc = await svc.reschedule("+1", day="tomorrow", time="1:00 PM")
    assert "repair" in desc
    slots = await svc.available_slots("tomorrow")
    assert "10:00 AM" in slots  # old slot freed
    assert "1:00 PM" not in slots  # new slot taken


async def test_reschedule_onto_taken_slot_raises() -> None:
    svc, _ = _service()
    await svc.create_event("+1", service="a", day="tomorrow", time="10:00 AM")
    await svc.create_event("+2", service="b", day="tomorrow", time="1:00 PM")
    with pytest.raises(SlotUnavailable):
        await svc.reschedule("+1", day="tomorrow", time="1:00 PM")


async def test_reschedule_without_booking_raises() -> None:
    svc, _ = _service()
    with pytest.raises(NoBooking):
        await svc.reschedule("+9", day="tomorrow", time="1:00 PM")


async def test_cancel_removes_booking_and_frees_slot() -> None:
    svc, _ = _service()
    await svc.create_event("+1", service="repair", day="tomorrow", time="10:00 AM")
    desc = await svc.cancel("+1")
    assert "repair" in desc
    assert await svc.find_event("+1") is None
    assert "10:00 AM" in await svc.available_slots("tomorrow")


async def test_cancel_without_booking_raises() -> None:
    svc, _ = _service()
    with pytest.raises(NoBooking):
        await svc.cancel("+1")
