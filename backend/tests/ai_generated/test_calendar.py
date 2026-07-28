"""The in-memory calendar, and the date/time parsing both backends share."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from receptionist.services.calendar import (
    FakeCalendarService,
    NoBooking,
    SlotUnavailable,
    slot_grid,
)
from receptionist.services.when import (
    fmt_time,
    pretty_day,
    resolve_date,
    resolve_datetime,
    resolve_time,
    timezone,
)
from tests.fakes import CALLER

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


@pytest.mark.parametrize(
    ("said", "expected"),
    [("today", 0), ("tomorrow", 1)],
)
def test_relative_days(said: str, expected: int) -> None:
    assert resolve_date(said, date(2026, 7, 27)) == date(2026, 7, 27 + expected)


def test_a_weekday_means_the_next_one_never_today() -> None:
    monday = date(2026, 7, 27)  # a Monday
    assert resolve_date("monday", monday) == date(2026, 8, 3)
    assert resolve_date("next tuesday", monday) == date(2026, 7, 28)


def test_iso_dates_pass_straight_through() -> None:
    assert resolve_date("2026-08-14", date(2026, 7, 27)) == date(2026, 8, 14)


@pytest.mark.parametrize(
    ("said", "hour", "minute"),
    [("10:00 AM", 10, 0), ("10am", 10, 0), ("14:00", 14, 0), ("2:30 pm", 14, 30)],
)
def test_times_people_actually_say(said: str, hour: int, minute: int) -> None:
    parsed = resolve_time(said)
    assert (parsed.hour, parsed.minute) == (hour, minute)


@pytest.mark.parametrize("said", ["", "whenever", "the usual"])
def test_unreadable_input_is_rejected_so_the_agent_can_ask_again(said: str) -> None:
    with pytest.raises(ValueError):
        resolve_date(said, date(2026, 7, 27))
    with pytest.raises(ValueError):
        resolve_time(said)


def test_dates_are_spoken_as_words_never_digits() -> None:
    assert pretty_day("2026-07-29") == "Wednesday, July 29"
    # Anything not an ISO date is passed through untouched.
    assert pretty_day("tomorrow") == "tomorrow"


def test_times_have_no_leading_zero() -> None:
    assert fmt_time(datetime(2026, 7, 29, 9, 5)) == "9:05 AM"
    assert fmt_time(datetime(2026, 7, 29, 13, 0)) == "1:00 PM"
    assert fmt_time(datetime(2026, 7, 29, 0, 30)) == "12:30 AM"
