"""The graph loop: model -> tools -> model, driven by a scripted model."""

from __future__ import annotations

from receptionist.graph import STUCK, Conversation
from receptionist.models import CallRecord, Outcome
from receptionist.profiles import get_profile
from receptionist.services.calendar import FakeCalendarService
from tests.fakes import CALLER, ScriptedModel, calls, says


def _hvac(model: ScriptedModel, calendar: FakeCalendarService) -> Conversation:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    return Conversation(get_profile("hvac"), calendar, record, model)


async def test_books_across_check_then_book(calendar: FakeCalendarService, next_week: str) -> None:
    model = ScriptedModel(
        replies=[
            calls("check_availability", day=next_week),
            calls(
                "book",
                service="furnace repair",
                day=next_week,
                time="10:00 AM",
                name="Sam Lee",
                address="12 Oak St, Burnaby",
                issue="no heat",
            ),
            says("You're booked for 10 in the morning. I'll text you the details."),
        ]
    )
    chat = _hvac(model, calendar)
    reply = await chat.say("my furnace quit, can someone come next week?")

    assert "booked" in reply.lower()
    record = chat.call.record
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.service == "furnace repair"
    assert record.booking.details == {
        "name": "Sam Lee",
        "address": "12 Oak St, Burnaby",
        "issue": "no heat",
    }
    assert record.booking.calendar_event_id
    assert [e.type for e in record.events] == ["availability_checked", "booking_created"]


async def test_a_taken_slot_is_declined_not_faked(
    calendar: FakeCalendarService, tomorrow: str
) -> None:
    """The fake seeds tomorrow 8:00 AM busy. The tool must refuse it outright."""
    model = ScriptedModel(
        replies=[
            calls(
                "book",
                service="furnace repair",
                day=tomorrow,
                time="8:00 AM",
                name="Sam Lee",
                address="12 Oak St",
                issue="no heat",
            ),
            says("Eight is taken, but nine is open. Shall I book that?"),
        ]
    )
    chat = _hvac(model, calendar)
    await chat.say("book me tomorrow at 8am")

    record = chat.call.record
    assert record.booking is None
    assert record.outcome is None
    assert [e.type for e in record.events] == ["slot_declined"]

    # The tool told the model what was actually open, so it can offer a real alternative.
    tool_result = model.prompts[-1][-1].text
    assert "isn't available" in tool_result
    assert "9:00 AM" in tool_result


async def test_booking_twice_confirms_instead_of_double_booking(
    calendar: FakeCalendarService, next_week: str
) -> None:
    """Between turns the model only sees what it said aloud, so it can forget it booked."""
    booking = dict(
        service="furnace repair",
        day=next_week,
        time="10:00 AM",
        name="Sam Lee",
        address="12 Oak St",
        issue="no heat",
    )
    model = ScriptedModel(
        replies=[
            calls("book", **booking),
            says("Booked!"),
            calls("book", **booking),
            says("Still booked!"),
        ]
    )
    chat = _hvac(model, calendar)
    await chat.say("book me next week at 10")
    first = chat.call.record.booking
    await chat.say("did that go through?")

    assert chat.call.record.booking is first
    assert "already booked" in model.prompts[-1][-1].text.lower()


async def test_takes_a_message(calendar: FakeCalendarService) -> None:
    model = ScriptedModel(
        replies=[
            calls("take_message", name="Dana", reason="wants a commercial boiler quote"),
            says("I'll pass that along."),
        ]
    )
    chat = _hvac(model, calendar)
    await chat.say("do you service commercial boilers?")

    record = chat.call.record
    assert record.outcome is Outcome.MESSAGE_TAKEN
    assert record.message is not None
    assert record.message.name == "Dana"
    assert record.booking is None


async def test_reschedule_then_cancel(calendar: FakeCalendarService, next_week: str) -> None:
    model = ScriptedModel(
        replies=[
            calls(
                "book",
                service="AC tune-up",
                day=next_week,
                time="1:00 PM",
                name="Sam",
                address="12 Oak St",
                issue="annual service",
            ),
            says("Booked."),
            calls("reschedule", day=next_week, time="3:00 PM"),
            says("Moved."),
            calls("cancel"),
            says("Cancelled."),
        ]
    )
    chat = _hvac(model, calendar)
    await chat.say("book my tune-up")

    await chat.say("actually can we make it 3pm?")
    assert chat.call.record.outcome is Outcome.RESCHEDULED
    assert chat.call.record.booking is not None
    assert chat.call.record.booking.starts_at.hour == 15
    # The details captured at booking survive the move.
    assert chat.call.record.booking.details["name"] == "Sam"

    await chat.say("you know what, cancel it")
    assert chat.call.record.outcome is Outcome.CANCELLED
    assert chat.call.record.booking is None


async def test_reschedule_without_a_booking_is_graceful(
    calendar: FakeCalendarService, next_week: str
) -> None:
    model = ScriptedModel(
        replies=[calls("reschedule", day=next_week, time="3:00 PM"), says("I don't see one.")]
    )
    chat = _hvac(model, calendar)
    await chat.say("move my appointment")

    assert chat.call.record.outcome is None
    assert "don't see an appointment" in model.prompts[-1][-1].text


async def test_unparseable_day_comes_back_as_something_to_ask_about(
    calendar: FakeCalendarService,
) -> None:
    """A ValueError inside a tool must reach the model as a tool result, not abort the
    turn — on a phone call an aborted turn is dead air."""
    model = ScriptedModel(
        replies=[
            calls("check_availability", day="whenever"),
            says("Which day did you have in mind?"),
        ]
    )
    chat = _hvac(model, calendar)
    reply = await chat.say("come by whenever")

    assert reply == "Which day did you have in mind?"
    assert "That didn't work" in model.prompts[-1][-1].text


async def test_a_stuck_tool_loop_gives_up_gracefully(
    calendar: FakeCalendarService, next_week: str
) -> None:
    model = ScriptedModel(replies=[calls("check_availability", day=next_week)], loop=True)
    chat = _hvac(model, calendar)

    assert await chat.say("hello?") == STUCK


async def test_transcript_records_both_sides(calendar: FakeCalendarService) -> None:
    chat = _hvac(ScriptedModel(replies=[says("We're open 8 to 6.")]), calendar)
    chat.greet()
    await chat.say("what are your hours?")

    assert [(t.role, t.text) for t in chat.call.record.transcript] == [
        ("agent", get_profile("hvac").greeting),
        ("caller", "what are your hours?"),
        ("agent", "We're open 8 to 6."),
    ]
