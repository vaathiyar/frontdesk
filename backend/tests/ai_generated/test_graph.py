"""Graph-loop leftovers: a tool with nothing to act on, a runaway loop, the transcript.

The booking guarantees themselves live in `tests/test_call_flow.py`.
"""

from __future__ import annotations

from receptionist.core.models import CallRecord
from receptionist.worker.agent.graph import STUCK
from receptionist.worker.profiles import get_profile
from tests.support.conversation import Conversation
from tests.support.fake_calendar import FakeCalendarService
from tests.support.fakes import CALLER, ScriptedModel, calls, says


def _hvac(model: ScriptedModel, calendar: FakeCalendarService) -> Conversation:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    return Conversation(get_profile("hvac"), calendar, record, model)


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
