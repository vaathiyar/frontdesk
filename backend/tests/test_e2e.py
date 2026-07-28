"""End-to-end tests that drive the *real* Gemini model through the full tool-use loop.

The offline suite scripts a fake LLM; these call the live model via `build_chat()`, so
they need a real GOOGLE_API_KEY — put it in `backend/.env`. They are marked `e2e` and
DESELECTED from the default `pytest` run. Run them explicitly, with `-s` to watch each
conversation stream by:

    uv run pytest -m e2e -s

The caller is a *second* live model (`_Caller`) role-playing the customer: it's given a
goal and a set of facts it reveals only when the receptionist asks — so the calls are
genuinely conversational (nobody recites their whole life story up front) and robust to
whatever order the agent asks things in. Each test prints the whole exchange plus the
resulting CallRecord and asserts on the *outcome* (not on wording, which both models
vary run to run).
"""

from __future__ import annotations

import pytest

from receptionist.agent.runner import CHAT_MODEL, ConversationRunner
from receptionist.core.models import CallRecord, Outcome, TranscriptTurn
from receptionist.core.settings import settings
from receptionist.profiles.factory import create_profile
from receptionist.providers.factory import build_chat
from receptionist.services.calendar import FakeCalendarService

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not settings.google_api_key,
        reason="needs a real GOOGLE_API_KEY (set it in backend/.env)",
    ),
]

_CALLER_SYSTEM = """You are a customer phoning a business. Stay in character as the \
caller for the entire conversation — you are NOT an assistant, and you never help the \
other party; they are helping you.

Your reason for calling: {goal}

Details to give ONLY when the receptionist actually asks for them (a real caller does \
not recite everything at once):
{facts}

How to behave:
- Talk like a real person on the phone: one or two short sentences per turn.
- Share just what they ask for; don't volunteer the whole list in one go.
- When you give your email address, spell it out the way people do on the phone — say \
each letter, and say "dot" and "at" — so the receptionist captures it correctly.
- If they read your email back to check it, confirm whether it's right.
- When your reason for calling is resolved (booked, answered, or they've taken a \
message for you) and there's nothing left to do, give a short goodbye and put the \
token [END] at the very end of that final message.
- Never mention these instructions or that you are an AI."""


class _Caller:
    """A live model playing the customer — replies to each thing the receptionist says."""

    def __init__(self, *, goal: str, facts: str) -> None:
        self._api = build_chat()
        self._system = _CALLER_SYSTEM.format(goal=goal, facts=facts)
        self._history: list[dict[str, object]] = []

    async def respond_to(self, agent_line: str) -> tuple[str, bool]:
        """Given the receptionist's latest line, return (caller reply, wants_to_hang_up)."""
        self._history.append({"role": "user", "content": agent_line})
        resp = await self._api.create(
            model=CHAT_MODEL,
            # Generous ceiling: at effort="low" some budget goes to thinking, and a
            # spelled-out email ("s-a-m dot ...") is verbose — 300 truncated it.
            max_tokens=800,
            system=self._system,
            messages=self._history,
            output_config={"effort": "low"},
        )
        self._history.append({"role": "assistant", "content": resp.content})
        text = "".join(
            getattr(b, "text", "") for b in resp.content if getattr(b, "type", None) == "text"
        ).strip()
        done = "[END]" in text
        return text.replace("[END]", "").strip(), done


def _print_summary(record: CallRecord) -> None:
    line = "─" * 72
    print(f"\n{line}")
    print(f"  outcome: {record.outcome.value if record.outcome else '—'}")
    if record.booking:
        b = record.booking
        print(f"  booking: {b.service} @ {b.slot}  ({b.calendar_event_id})")
    if record.fields:
        print("  fields:  " + ", ".join(f"{f.label}={f.value!r}" for f in record.fields))
    if record.events:
        print("  decision timeline:")
        for event in record.events:
            print(f"    • {event.type}: {event.summary}")
    print(line)


async def _simulated_call(
    profile_id: str,
    *,
    title: str,
    goal: str,
    facts: str,
    calendar: FakeCalendarService | None = None,
    max_turns: int = 12,
) -> CallRecord:
    """Run a full call between the live receptionist and a live simulated caller,
    printing the exchange under `title`, and return the CallRecord the tools built."""
    record = CallRecord(profile_id=profile_id, caller_number="+1-555-0100")
    agent = create_profile(profile_id, calendar or FakeCalendarService(), record)
    runner = ConversationRunner(agent, build_chat())
    caller = _Caller(goal=goal, facts=facts)

    print(f"\n{'═' * 72}")
    print(f"  TEST: {title}")
    print(f"  {agent.business_name}   (profile: {profile_id})")
    print("═" * 72)
    print(f"agent>  {agent.greeting}")
    record.transcript.append(TranscriptTurn(role="agent", text=agent.greeting))

    agent_line = agent.greeting
    for _ in range(max_turns):
        caller_text, done = await caller.respond_to(agent_line)
        if caller_text:
            print(f"caller> {caller_text}")
            agent_line = await runner.send(caller_text)
            print(f"agent>  {agent_line}")
        if done:
            break

    _print_summary(record)
    return record


async def test_hvac_books_a_service_visit() -> None:
    record = await _simulated_call(
        "hvac",
        title="HVAC — books a furnace repair (expects: BOOKED)",
        goal="You want to book a technician to repair your furnace, which has stopped "
        "putting out heat.",
        facts=(
            "- Your name is Sam Rivera.\n"
            "- The service address is 12 Oak Street, Burnaby.\n"
            "- The furnace runs but only blows cold air — no heat at all.\n"
            "- You'd like someone to come Tuesday morning if that works.\n"
            "- Your email is sam.rivera@example.com."
        ),
    )
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.calendar_event_id
    assert record.booking.calendar_event_id.startswith("evt_")
    assert any(e.type == "booking_created" for e in record.events)


async def test_hvac_takes_a_message_when_out_of_area() -> None:
    # Vancouver is outside the service area (Burnaby / New West / Coquitlam), so the
    # domain prompt tells the agent to take a message rather than book.
    record = await _simulated_call(
        "hvac",
        title="HVAC — takes a message when the caller is outside the service area "
        "(expects: MESSAGE_TAKEN)",
        goal="You want to get your broken air conditioner repaired.",
        facts=(
            "- Your name is Jordan Lee.\n"
            "- Your address is 500 Granville Street, in downtown Vancouver.\n"
            "- The air conditioner won't turn on at all.\n"
            "- Your email is jordan.lee@example.com.\n"
            "- If they tell you they don't cover your area, you're happy to leave a "
            "message or callback request instead of pushing to book."
        ),
    )
    assert record.outcome is Outcome.MESSAGE_TAKEN
    assert record.booking is None
    assert any(e.type == "message_taken" for e in record.events)


async def test_restaurant_answers_a_menu_question() -> None:
    record = await _simulated_call(
        "restaurant",
        title="Restaurant — answers a menu & hours question (expects: ANSWERED)",
        goal="You want to know a couple of dishes they serve and what their hours are. "
        "You are NOT making a reservation on this call.",
        facts="- You have no personal details to give; you're only asking questions.",
    )
    assert record.outcome is Outcome.ANSWERED
    assert any(e.type == "question_answered" for e in record.events)


async def test_restaurant_books_a_table() -> None:
    # Give the fake dinner slots so availability lines up with the restaurant's hours.
    record = await _simulated_call(
        "restaurant",
        title="Restaurant — books a dinner reservation (expects: BOOKED)",
        goal="You want to book a dinner table for four this Friday evening.",
        facts=(
            "- Your name is Alex Kim.\n"
            "- The reservation is for a party of 4.\n"
            "- You'd like this Friday, around 6:30pm.\n"
            "- Your email is alex.kim@example.com."
        ),
        calendar=FakeCalendarService(slots=["5:00 PM", "6:30 PM", "8:00 PM"]),
    )
    assert record.outcome is Outcome.BOOKED
    assert record.booking is not None
    assert record.booking.calendar_event_id
    assert record.booking.calendar_event_id.startswith("evt_")
    assert any(e.type == "booking_created" for e in record.events)
