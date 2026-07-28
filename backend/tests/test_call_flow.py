"""What the agent does on a call, driven end to end through the graph.

Every test here scripts the model's replies (see `tests/fakes.py`) and then checks the
`CallRecord` — the one artefact the confirmation text, the store and the web page all
read. Nothing here is mocked below the model: the real tools run against the real
in-memory calendar, so a booking that "happened" actually took a slot.
"""

from __future__ import annotations

from receptionist.graph import Conversation
from receptionist.models import CallRecord, Outcome
from receptionist.profiles import get_profile
from receptionist.prompt import render
from receptionist.services.calendar import FakeCalendarService
from tests.fakes import CALLER, ScriptedModel, calls, says


def dial(profile_id: str, model: ScriptedModel, calendar: FakeCalendarService) -> Conversation:
    """One inbound call to a profile, with the model's replies scripted in advance."""
    record = CallRecord(profile_id=profile_id, caller_number=CALLER)
    return Conversation(get_profile(profile_id), calendar, record, model)


async def test_a_caller_books_and_the_record_captures_the_whole_appointment(
    calendar: FakeCalendarService, next_week: str
) -> None:
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
    chat = dial("hvac", model, calendar)

    reply = await chat.say("my furnace quit, can someone come next week?")

    assert "booked" in reply.lower()
    record = chat.call.record
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.service == "furnace repair"
    assert record.booking.starts_at.date().isoformat() == next_week
    assert record.booking.starts_at.hour == 10
    assert record.booking.details == {
        "name": "Sam Lee",
        "address": "12 Oak St, Burnaby",
        "issue": "no heat",
    }
    assert record.booking.calendar_event_id
    assert [e.type for e in record.events] == ["availability_checked", "booking_created"]


async def test_a_time_that_is_taken_is_declined_and_real_alternatives_offered(
    calendar: FakeCalendarService, tomorrow: str
) -> None:
    """The calendar seeds tomorrow at 8:00 AM busy. The tool refuses it rather than
    trusting the model to have checked, and hands back times that are genuinely open."""
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
    chat = dial("hvac", model, calendar)

    await chat.say("book me tomorrow at 8am")

    record = chat.call.record
    assert record.booking is None
    assert record.outcome is None
    assert [e.type for e in record.events] == ["slot_declined"]

    tool_result = model.prompts[-1][-1].text
    assert "isn't available" in tool_result
    assert "9:00 AM" in tool_result


async def test_booking_twice_confirms_the_existing_appointment_instead_of_making_a_second(
    calendar: FakeCalendarService, next_week: str
) -> None:
    """Between turns the model sees only what it said out loud, not its own earlier tool
    calls, so it can forget it already booked and try again."""
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
    chat = dial("hvac", model, calendar)

    await chat.say("book me next week at 10")
    first = chat.call.record.booking
    await chat.say("did that go through?")

    assert chat.call.record.booking is first
    assert "already booked" in model.prompts[-1][-1].text.lower()


async def test_an_appointment_can_be_moved_and_then_cancelled(
    calendar: FakeCalendarService, next_week: str
) -> None:
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
    chat = dial("hvac", model, calendar)
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


async def test_a_message_is_taken_when_the_agent_cannot_help(
    calendar: FakeCalendarService,
) -> None:
    model = ScriptedModel(
        replies=[
            calls("take_message", name="Dana", reason="wants a commercial boiler quote"),
            says("I'll pass that along."),
        ]
    )
    chat = dial("hvac", model, calendar)

    await chat.say("do you service commercial boilers?")

    record = chat.call.record
    assert record.outcome is Outcome.MESSAGE_TAKEN
    assert record.message is not None
    assert record.message.name == "Dana"
    assert record.message.reason == "wants a commercial boiler quote"
    assert record.booking is None


async def test_a_day_the_agent_cannot_read_becomes_a_question_not_dead_air(
    calendar: FakeCalendarService,
) -> None:
    """A tool that rejects its input must come back to the model as a tool result. If it
    raised, the turn would abort — which on a phone call is silence."""
    model = ScriptedModel(
        replies=[
            calls("check_availability", day="whenever"),
            says("Which day did you have in mind?"),
        ]
    )
    chat = dial("hvac", model, calendar)

    reply = await chat.say("come by whenever")

    assert reply == "Which day did you have in mind?"
    assert "That didn't work" in model.prompts[-1][-1].text


async def test_the_restaurant_profile_books_an_evening_table_on_the_same_engine(
    next_week: str,
) -> None:
    """Nothing in the graph knows about HVAC. A second vertical is a prompt plus its own
    `book` tool, its own fields, and its own opening hours — a restaurant seats people at
    7pm, which is long past a furnace shop's last call.
    """
    restaurant = get_profile("restaurant")
    calendar = FakeCalendarService(restaurant.opens, restaurant.closes)
    model = ScriptedModel(
        replies=[
            calls("check_availability", day=next_week),
            calls(
                "book",
                service="table for 4",
                day=next_week,
                time="7:00 PM",
                name="Priya",
                party_size="4",
            ),
            says("You're all set for seven o'clock."),
        ]
    )
    chat = dial("restaurant", model, calendar)

    await chat.say("a table for four next week, around seven?")

    record = chat.call.record
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.service == "table for 4"
    assert record.booking.starts_at.hour == 19
    assert record.booking.details == {"name": "Priya", "party_size": "4"}


def test_the_caller_is_never_asked_for_a_phone_number_or_an_email() -> None:
    """The number comes from caller ID, and nothing downstream needs an email address."""
    for profile_id in ("hvac", "restaurant"):
        prompt = render(get_profile(profile_id))
        assert "never ask for it" in prompt
        assert "Never ask for an email" in prompt
