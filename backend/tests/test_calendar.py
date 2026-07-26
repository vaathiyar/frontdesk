from __future__ import annotations

import pytest

from receptionist.core.models import Booking
from receptionist.services.calendar import FakeCalendarService, NoBooking, SlotUnavailable


async def test_available_slots_excludes_seeded_busy() -> None:
    cal = FakeCalendarService()
    slots = await cal.available_slots("tomorrow")
    assert "8:00 AM" not in slots  # seeded busy
    assert "10:00 AM" in slots


async def test_create_event_then_slot_is_no_longer_available() -> None:
    cal = FakeCalendarService()
    eid = await cal.create_event("+1", service="furnace repair", day="Tuesday", time="10:00 AM")
    assert eid.startswith("evt_")
    assert "10:00 AM" not in await cal.available_slots("Tuesday")


async def test_create_event_on_busy_slot_raises() -> None:
    cal = FakeCalendarService()
    with pytest.raises(SlotUnavailable):
        await cal.create_event("+1", service="repair", day="tomorrow", time="8:00 AM")


async def test_find_event_none_then_present() -> None:
    cal = FakeCalendarService()
    assert await cal.find_event("+1") is None
    await cal.create_event("+1", service="repair", day="Tuesday", time="10:00 AM")
    assert "Tuesday" in (await cal.find_event("+1") or "")


async def test_reschedule_moves_and_frees_old_slot() -> None:
    cal = FakeCalendarService()
    await cal.create_event("+1", service="repair", day="Tuesday", time="10:00 AM")
    await cal.reschedule("+1", day="Tuesday", time="1:00 PM")
    assert "10:00 AM" in await cal.available_slots("Tuesday")  # old freed
    assert "1:00 PM" not in await cal.available_slots("Tuesday")  # new taken


async def test_reschedule_without_booking_raises() -> None:
    with pytest.raises(NoBooking):
        await FakeCalendarService().reschedule("+1", day="Tuesday", time="1:00 PM")


async def test_cancel_frees_slot_and_removes_booking() -> None:
    cal = FakeCalendarService()
    await cal.create_event("+1", service="repair", day="Tuesday", time="10:00 AM")
    await cal.cancel("+1")
    assert await cal.find_event("+1") is None
    assert "10:00 AM" in await cal.available_slots("Tuesday")


async def test_cancel_without_booking_raises() -> None:
    with pytest.raises(NoBooking):
        await FakeCalendarService().cancel("+1")


def test_booking_model_round_trips() -> None:
    b = Booking(service="furnace repair", slot="Tuesday 10:00 AM", calendar_event_id="evt_1")
    assert b.model_dump()["slot"] == "Tuesday 10:00 AM"
