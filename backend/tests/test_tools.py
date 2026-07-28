"""Exercise the tools directly (no LLM) — this is where the real logic lives, and
each test maps to a demo/acceptance behaviour.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from receptionist.core.models import CallRecord, Outcome
from receptionist.core.settings import settings
from receptionist.profiles.factory import PROFILES, create_profile
from receptionist.services.calendar import FakeCalendarService

_BOOK_ARGS = {
    "service": "furnace repair",
    "day": "Tuesday",
    "time": "10:00 AM",
    "name": "Sam Lee",
    "address": "12 Oak St, Burnaby",
    "issue": "no heat",
    "email": "sam@example.com",
}


def _hvac() -> tuple:
    record = CallRecord(profile_id="hvac", caller_number="+1-555-0100")
    calendar = FakeCalendarService()
    return create_profile("hvac", calendar, record), record, calendar


async def test_check_availability_lists_open_and_hides_busy() -> None:
    agent, _, _ = _hvac()
    out = await agent.dispatch("check_availability", {"day": "tomorrow"})
    assert "10:00 AM" in out
    assert "8:00 AM" not in out  # seeded busy


async def test_book_happy_path_sets_record_and_calendar() -> None:
    agent, record, calendar = _hvac()
    out = await agent.dispatch("book", dict(_BOOK_ARGS))
    assert "Booked" in out
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.slot == "Tuesday 10:00 AM"
    assert record.booking.calendar_event_id
    assert {f.key for f in record.fields} == {"name", "address", "issue", "email"}
    assert await calendar.find_event("+1-555-0100") is not None
    assert any(e.type == "booking_created" for e in record.events)


async def test_book_never_fakes_a_taken_slot() -> None:
    agent, record, _ = _hvac()
    args = dict(_BOOK_ARGS, day="tomorrow", time="8:00 AM")  # seeded busy
    out = await agent.dispatch("book", args)
    assert "isn't available" in out
    assert record.outcome is not Outcome.BOOKED
    assert record.booking is None  # nothing fabricated
    assert any(e.type == "slot_declined" for e in record.events)


async def test_reschedule_after_booking() -> None:
    agent, record, _ = _hvac()
    await agent.dispatch("book", dict(_BOOK_ARGS))
    out = await agent.dispatch("reschedule", {"day": "Tuesday", "time": "1:00 PM"})
    assert "Moved" in out
    assert record.outcome is Outcome.RESCHEDULED


async def test_cancel_after_booking() -> None:
    agent, record, _ = _hvac()
    await agent.dispatch("book", dict(_BOOK_ARGS))
    out = await agent.dispatch("cancel", {})
    assert "Cancelled" in out
    assert record.outcome is Outcome.CANCELLED


async def test_reschedule_without_booking_is_graceful() -> None:
    agent, record, _ = _hvac()
    out = await agent.dispatch("reschedule", {"day": "Tuesday", "time": "1:00 PM"})
    assert "don't see" in out
    assert record.outcome is None


async def test_answer_question_returns_knowledge() -> None:
    agent, record, _ = _hvac()
    out = await agent.dispatch("answer_question", {"question": "what are your hours?"})
    assert "8am to 6pm" in out
    assert record.outcome is Outcome.ANSWERED


async def test_take_message_captures_name_and_reason() -> None:
    agent, record, _ = _hvac()
    out = await agent.dispatch("take_message", {"name": "Jo", "reason": "commercial boiler"})
    assert "pass that along" in out
    assert record.outcome is Outcome.MESSAGE_TAKEN
    assert {f.key for f in record.fields} == {"name", "reason"}


async def test_unknown_tool_does_not_crash() -> None:
    agent, _, _ = _hvac()
    assert "Unknown tool" in await agent.dispatch("nonexistent", {})


# ------------------------------------------------------- dates: ISO in, words out --
class _UnparseableDayCalendar(FakeCalendarService):
    """Stands in for the real backend, which raises ValueError on a day it can't parse."""

    async def available_slots(self, day: str) -> list[str]:
        raise ValueError(f"I couldn't understand the day {day!r}.")


async def test_unparseable_day_returns_a_tool_error_instead_of_crashing() -> None:
    # Letting the ValueError escape aborts the turn — on a real call, that's dead air.
    record = CallRecord(profile_id="hvac", caller_number="+1-555-0100")
    agent = create_profile("hvac", _UnparseableDayCalendar(), record)

    out = await agent.dispatch("check_availability", {"day": "day after tomorrow"})

    assert "couldn't understand" in out
    assert "clarify" in out.lower()  # the model is told how to recover
    assert any(e.type == "tool_input_rejected" for e in record.events)


async def test_iso_day_is_stored_and_read_back_in_words() -> None:
    agent, record, _ = _hvac()
    day = date(2026, 7, 29)

    out = await agent.dispatch("book", dict(_BOOK_ARGS, day=day.isoformat()))

    assert record.booking is not None
    assert record.booking.slot == f"{day:%A}, {day:%B} {day.day} at 10:00 AM"
    assert day.isoformat() not in out  # never hands the model a date to read as digits


def test_every_profile_prompt_anchors_today_and_demands_iso_dates() -> None:
    now = datetime.now(ZoneInfo(settings.timezone))
    for pid in PROFILES:
        record = CallRecord(profile_id=pid, caller_number="+1-555-0100")
        prompt = create_profile(pid, FakeCalendarService(), record).system_prompt()
        # Without today's date the model can't resolve "the day after tomorrow" itself.
        assert f"{now:%B} {now.day}, {now.year}" in prompt
        assert "YYYY-MM-DD" in prompt


def test_every_profile_asks_for_iso_dates_in_its_tool_schemas() -> None:
    for pid in PROFILES:
        record = CallRecord(profile_id=pid, caller_number="+1-555-0100")
        schemas = create_profile(pid, FakeCalendarService(), record).tool_schemas()
        days = [
            t["input_schema"]["properties"]["day"]
            for t in schemas
            if "day" in t["input_schema"]["properties"]
        ]
        assert len(days) == 3  # check_availability, book, reschedule
        assert all("YYYY-MM-DD" in d["description"] for d in days)
