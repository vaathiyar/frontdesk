"""Booking against the in-memory calendar, and the slot grid both backends share.

The parsing that turns "tomorrow at 10" into one of these times is in `test_datetimes.py`.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from receptionist.worker.booking.service import NoBooking, SlotUnavailable, slot_grid
from receptionist.worker.lib.datetimes import fmt_time, resolve_datetime, timezone
from tests.support.fake_calendar import FakeCalendarService
from tests.support.fakes import CALLER

BOOKING = dict(service="furnace repair", time="10:00 AM")


async def test_seeded_busy_time_is_not_offered(
    calendar: FakeCalendarService, tomorrow: str
) -> None:
    times = await calendar.available_slots(tomorrow)
    assert "8:00 AM" not in times
    assert "9:00 AM" in times


async def test_booking_takes_the_time_off_the_list(
    calendar: FakeCalendarService, next_week: str
) -> None:
    booked = await calendar.create_event(CALLER, day=next_week, **BOOKING)

    assert booked.event_id
    assert booked.starts_at.hour == 10
    assert (booked.ends_at - booked.starts_at).total_seconds() == 3600
    assert "10:00 AM" not in await calendar.available_slots(next_week)


async def test_cannot_book_a_taken_time(calendar: FakeCalendarService, next_week: str) -> None:
    await calendar.create_event(CALLER, day=next_week, **BOOKING)
    with pytest.raises(SlotUnavailable):
        await calendar.create_event("+16045550999", day=next_week, **BOOKING)


async def test_reschedule_frees_the_old_time(calendar: FakeCalendarService, next_week: str) -> None:
    await calendar.create_event(CALLER, day=next_week, **BOOKING)
    moved = await calendar.reschedule(CALLER, day=next_week, time="3:00 PM")

    assert moved.starts_at.hour == 15
    assert moved.service == "furnace repair"
    times = await calendar.available_slots(next_week)
    assert "10:00 AM" in times
    assert "3:00 PM" not in times


async def test_cancel_frees_the_time_and_forgets_the_caller(
    calendar: FakeCalendarService, next_week: str
) -> None:
    await calendar.create_event(CALLER, day=next_week, **BOOKING)
    assert "furnace repair" in await calendar.cancel(CALLER)
    assert "10:00 AM" in await calendar.available_slots(next_week)
    with pytest.raises(NoBooking):
        await calendar.cancel(CALLER)


async def test_rescheduling_onto_your_own_slot_is_not_a_clash(
    calendar: FakeCalendarService, next_week: str
) -> None:
    """GoogleCalendarService excludes the caller's own event when checking for conflicts,
    so the fake must too, or the two backends disagree about the same request."""
    await calendar.create_event(CALLER, day=next_week, **BOOKING)
    moved = await calendar.reschedule(CALLER, day=next_week, time="10:00 AM")
    assert moved.starts_at.hour == 10


async def test_a_refused_reschedule_leaves_the_original_booking_alone(
    calendar: FakeCalendarService, next_week: str, tomorrow: str
) -> None:
    """The check releases the caller's slot first, so a refusal has to put it back."""
    await calendar.create_event(CALLER, day=next_week, **BOOKING)
    taken = (await calendar.available_slots(tomorrow))[0]
    await calendar.create_event("+16045550999", service="AC repair", day=tomorrow, time=taken)

    with pytest.raises(SlotUnavailable):
        await calendar.reschedule(CALLER, day=tomorrow, time=taken)

    assert "10:00 AM" not in await calendar.available_slots(next_week)
    assert "furnace repair" in await calendar.cancel(CALLER)


async def test_a_profile_with_evening_hours_offers_evening_times(next_week: str) -> None:
    dinner = FakeCalendarService(17, 22)
    times = await dinner.available_slots(next_week)

    assert times[0] == "5:00 PM"
    assert "7:00 PM" in times
    assert times[-1] == "9:00 PM"
    assert "10:00 AM" not in times


async def test_reschedule_and_cancel_need_an_existing_booking(
    calendar: FakeCalendarService, next_week: str
) -> None:
    with pytest.raises(NoBooking):
        await calendar.reschedule(CALLER, day=next_week, time="3:00 PM")
    with pytest.raises(NoBooking):
        await calendar.cancel(CALLER)


async def test_today_no_longer_offers_times_already_past(
    calendar: FakeCalendarService,
) -> None:
    now = datetime.now(timezone())
    for offered in await calendar.available_slots("today"):
        assert resolve_datetime("today", offered, tz=timezone()) > now


def test_appointments_fit_inside_business_hours() -> None:
    grid = slot_grid(date(2026, 8, 3))
    assert fmt_time(grid[0]) == "8:00 AM"
    # The last start is 5pm, so the hour-long appointment still ends by the 6pm close.
    assert fmt_time(grid[-1]) == "5:00 PM"
