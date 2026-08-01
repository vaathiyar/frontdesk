"""The real Google Calendar adapter, driven against a stub client — no network.

The stub implements only the four calls the adapter makes, but it implements them
honestly: overlap filtering, the private property we stamp on bookings, and freebusy.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from dateutil import parser as dateparser

from receptionist.worker.booking.google import GoogleCalendarService
from receptionist.worker.booking.service import NoBooking, SlotUnavailable
from receptionist.worker.lib.datetimes import resolve_datetime, timezone
from tests.support.fakes import CALLER, day_after

CALENDAR_ID = "hvac@group.calendar.google.com"


class _Request:
    """googleapiclient defers work until .execute(); the adapter relies on that."""

    def __init__(self, result: Any) -> None:
        self._result = result

    def execute(self) -> Any:
        return self._result


class FakeGoogleClient:
    """Just enough Calendar v3 to drive the adapter."""

    def __init__(self) -> None:
        self.stored: dict[str, dict[str, Any]] = {}
        self._sequence = 0

    # --- resource accessors the adapter calls ---
    def events(self) -> Any:
        return self

    def freebusy(self) -> Any:
        return self

    # --- events() ---
    def insert(self, *, calendarId: str, body: dict[str, Any]) -> _Request:
        self._sequence += 1
        event_id = f"gcal_{self._sequence}"
        self.stored[event_id] = {**body, "id": event_id}
        return _Request(self.stored[event_id])

    def list(
        self,
        *,
        calendarId: str,
        timeMin: str,
        timeMax: str | None = None,
        privateExtendedProperty: str | None = None,
        **kwargs: Any,
    ) -> _Request:
        found = [
            event
            for event in self.stored.values()
            if self._matches_property(event, privateExtendedProperty)
            and self._in_window(event, timeMin, timeMax)
        ]
        found.sort(key=lambda e: e["start"]["dateTime"])
        return _Request({"items": found})

    def patch(self, *, calendarId: str, eventId: str, body: dict[str, Any]) -> _Request:
        self.stored[eventId].update(body)
        return _Request(self.stored[eventId])

    def delete(self, *, calendarId: str, eventId: str) -> _Request:
        self.stored.pop(eventId, None)
        return _Request({})

    # --- freebusy() ---
    def query(self, *, body: dict[str, Any]) -> _Request:
        busy = [
            {"start": event["start"]["dateTime"], "end": event["end"]["dateTime"]}
            for event in self.stored.values()
            if self._in_window(event, body["timeMin"], body["timeMax"])
        ]
        return _Request({"calendars": {CALENDAR_ID: {"busy": busy}}})

    # --- helpers ---
    @staticmethod
    def _matches_property(event: dict[str, Any], wanted: str | None) -> bool:
        if wanted is None:
            return True
        key, _, value = wanted.partition("=")
        return bool(event.get("extendedProperties", {}).get("private", {}).get(key) == value)

    @staticmethod
    def _in_window(event: dict[str, Any], time_min: str, time_max: str | None) -> bool:
        start = dateparser.isoparse(event["start"]["dateTime"])
        end = dateparser.isoparse(event["end"]["dateTime"])
        if end <= dateparser.isoparse(time_min):
            return False
        return time_max is None or start < dateparser.isoparse(time_max)


@pytest.fixture
def client() -> FakeGoogleClient:
    return FakeGoogleClient()


@pytest.fixture
def google(client: FakeGoogleClient) -> GoogleCalendarService:
    return GoogleCalendarService(CALENDAR_ID, client=client)


async def test_open_times_span_business_hours(
    google: GoogleCalendarService, next_week: str
) -> None:
    times = await google.available_slots(next_week)
    assert times[0] == "8:00 AM"
    assert times[-1] == "5:00 PM"


async def test_booking_stamps_the_caller_and_removes_the_time(
    google: GoogleCalendarService, client: FakeGoogleClient, next_week: str
) -> None:
    booked = await google.create_event(
        CALLER, service="furnace repair", day=next_week, time="10:00 AM"
    )

    assert booked.starts_at.hour == 10
    assert (booked.ends_at - booked.starts_at) == timedelta(hours=1)
    stored = client.stored[booked.event_id]
    assert stored["summary"] == "furnace repair"
    assert stored["extendedProperties"]["private"]["caller_number"] == CALLER
    assert CALLER in stored["description"]
    assert "10:00 AM" not in await google.available_slots(next_week)


async def test_never_books_over_an_existing_event(
    google: GoogleCalendarService, next_week: str
) -> None:
    await google.create_event(CALLER, service="furnace repair", day=next_week, time="10:00 AM")
    with pytest.raises(SlotUnavailable):
        await google.create_event(
            "+16045550999", service="AC repair", day=next_week, time="10:00 AM"
        )


async def test_an_adjacent_appointment_is_not_a_conflict(
    google: GoogleCalendarService, next_week: str
) -> None:
    """Appointments are an hour long, so 11:00 is free right after a 10:00 booking."""
    await google.create_event(CALLER, service="furnace repair", day=next_week, time="10:00 AM")
    booked = await google.create_event(
        "+16045550999", service="AC repair", day=next_week, time="11:00 AM"
    )
    assert booked.starts_at.hour == 11


async def test_reschedule_moves_the_same_event_and_keeps_the_service(
    google: GoogleCalendarService, client: FakeGoogleClient, next_week: str
) -> None:
    booked = await google.create_event(
        CALLER, service="furnace repair", day=next_week, time="10:00 AM"
    )
    moved = await google.reschedule(CALLER, day=next_week, time="3:00 PM")

    assert moved.event_id == booked.event_id
    assert moved.service == "furnace repair"
    assert moved.starts_at.hour == 15
    assert len(client.stored) == 1
    assert "10:00 AM" in await google.available_slots(next_week)


async def test_reschedule_does_not_treat_the_callers_own_event_as_a_conflict(
    google: GoogleCalendarService, next_week: str
) -> None:
    """freebusy can't distinguish events, so moving to an overlapping slot needs the
    caller's own appointment excluded — otherwise every reschedule self-collides."""
    await google.create_event(CALLER, service="furnace repair", day=next_week, time="10:00 AM")
    moved = await google.reschedule(CALLER, day=next_week, time="10:00 AM")
    assert moved.starts_at.hour == 10


async def test_reschedule_onto_someone_elses_slot_is_refused(
    google: GoogleCalendarService, next_week: str
) -> None:
    await google.create_event(CALLER, service="furnace repair", day=next_week, time="10:00 AM")
    await google.create_event("+16045550999", service="AC repair", day=next_week, time="1:00 PM")

    with pytest.raises(SlotUnavailable):
        await google.reschedule(CALLER, day=next_week, time="1:00 PM")


async def test_cancel_deletes_the_event_and_reports_what_went(
    google: GoogleCalendarService, client: FakeGoogleClient, next_week: str
) -> None:
    await google.create_event(CALLER, service="furnace repair", day=next_week, time="10:00 AM")
    spoken = await google.cancel(CALLER)

    assert "furnace repair" in spoken
    assert client.stored == {}


async def test_reschedule_and_cancel_need_a_booking_under_that_number(
    google: GoogleCalendarService, next_week: str
) -> None:
    await google.create_event("+16045550999", service="AC repair", day=next_week, time="10:00 AM")
    with pytest.raises(NoBooking):
        await google.reschedule(CALLER, day=next_week, time="1:00 PM")
    with pytest.raises(NoBooking):
        await google.cancel(CALLER)


async def test_a_past_appointment_is_not_found(
    google: GoogleCalendarService, client: FakeGoogleClient
) -> None:
    """`_find` searches from now onward, so yesterday's visit can't be rescheduled."""
    yesterday = resolve_datetime(day_after(-1), "10:00 AM", tz=timezone())
    client.stored["old"] = {
        "id": "old",
        "summary": "furnace repair",
        "start": {"dateTime": yesterday.isoformat()},
        "end": {"dateTime": (yesterday + timedelta(hours=1)).isoformat()},
        "extendedProperties": {"private": {"caller_number": CALLER}},
    }
    with pytest.raises(NoBooking):
        await google.cancel(CALLER)


async def test_today_only_offers_times_still_to_come(google: GoogleCalendarService) -> None:
    now = datetime.now(timezone())
    for offered in await google.available_slots("today"):
        assert resolve_datetime("today", offered, tz=timezone()) > now
