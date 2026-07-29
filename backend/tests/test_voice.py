"""The voice path. LiveKit hands each caller turn to `llm_node`; what that yields is
spoken aloud, so what it must never yield is the more interesting half."""

from __future__ import annotations

from dataclasses import dataclass

from receptionist.agent.graph import STUCK
from receptionist.agent.tools import CallContext
from receptionist.agent.worker import ReceptionistAgent
from receptionist.models import CallRecord
from receptionist.profiles import get_profile
from receptionist.services.calendar import FakeCalendarService
from tests.fakes import CALLER, ScriptedModel, calls, says


@dataclass
class Turn:
    """One entry of LiveKit's history, as `llm_node` reads it."""

    role: str
    text_content: str
    id: str = "item_1"


class ChatContext:
    def __init__(self, *turns: Turn) -> None:
        self._turns = turns

    def messages(self) -> tuple[Turn, ...]:
        return self._turns


async def spoken_by(agent: ReceptionistAgent, *turns: Turn) -> str:
    chunks = [
        chunk async for chunk in agent.llm_node(ChatContext(*turns), tools=[], model_settings=None)
    ]
    return "".join(chunks)


def hvac_agent(model: ScriptedModel) -> ReceptionistAgent:
    call = CallContext(
        calendar=FakeCalendarService(),
        record=CallRecord(profile_id="hvac", caller_number=CALLER),
    )
    return ReceptionistAgent(get_profile("hvac"), call, model)


async def test_the_caller_hears_the_answer_and_never_the_tool_output(next_week: str) -> None:
    """Tool results travel the same stream as the words to speak. Left unfiltered, the
    caller is read a raw list of times before the actual reply — which is exactly what
    the stock LangChain adapter does, and the reason llm_node is overridden at all.
    """
    agent = hvac_agent(
        ScriptedModel(
            replies=[
                calls("check_availability", day=next_week),
                says("I have nine or ten in the morning. Which suits you?"),
            ]
        )
    )

    said = await spoken_by(agent, Turn("user", "when could someone come out?"))

    assert said == "I have nine or ten in the morning. Which suits you?"
    assert "Open on" not in said
    assert "9:00 AM" not in said


async def test_a_stuck_loop_still_says_something(next_week: str) -> None:
    """Yielding nothing would leave the caller listening to silence."""
    agent = hvac_agent(
        ScriptedModel(replies=[calls("check_availability", day=next_week)], loop=True)
    )

    assert await spoken_by(agent, Turn("user", "hello?")) == STUCK
