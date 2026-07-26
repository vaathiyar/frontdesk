"""Prove the tool-use loop end to end with a scripted fake LLM (no network)."""

from __future__ import annotations

from fakes import FakeMessages, text, tool
from receptionist.agent.runner import ConversationRunner
from receptionist.core.models import CallRecord, Outcome
from receptionist.profiles.factory import create_profile
from receptionist.services.calendar import FakeCalendarService


def _hvac_runner(script):
    record = CallRecord(profile_id="hvac", caller_number="+1-555-0100")
    agent = create_profile("hvac", FakeCalendarService(), record)
    return ConversationRunner(agent, FakeMessages(script)), record


async def test_full_turn_books_across_check_then_book_then_text() -> None:
    fm_script = [
        tool("check_availability", tool_id="a", day="Tuesday"),
        tool(
            "book",
            tool_id="b",
            service="furnace repair",
            day="Tuesday",
            time="10:00 AM",
            name="Sam",
            address="12 Oak St",
            issue="no heat",
            email="sam@example.com",
        ),
        text("You're all set for Tuesday at 10 AM. Anything else?"),
    ]
    runner, record = _hvac_runner(fm_script)

    reply = await runner.send("my furnace died, can someone come Tuesday morning?")

    assert reply == "You're all set for Tuesday at 10 AM. Anything else?"
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None and record.booking.slot == "Tuesday 10:00 AM"
    # transcript captured both sides of the exchange
    assert [t.role for t in record.transcript] == ["caller", "agent"]


async def test_runner_passes_system_tools_and_effort_to_the_model() -> None:
    runner, _ = _hvac_runner([text("Hi!")])
    await runner.send("hello")
    call = runner._messages_api.calls[0]  # type: ignore[attr-defined]
    assert call["model"]
    assert call["system"]
    assert {t["name"] for t in call["tools"]} >= {"book", "answer_question"}
    assert call["output_config"] == {"effort": "medium"}


async def test_plain_question_turn_returns_text_without_tools() -> None:
    runner, record = _hvac_runner([text("We're open Mon–Sat, 8 to 6.")])
    reply = await runner.send("what are your hours?")
    assert "8 to 6" in reply
