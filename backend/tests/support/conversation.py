"""Driving the graph by text, so the suite exercises it without LiveKit.

Lives here rather than in `src/` because production has exactly one driver: the voice
worker. This is the offline equivalent — feed it what the caller said, get back what the
agent would say.

History is deliberately text-only — the caller said this, the agent said that. The voice
path can't offer more than that (LiveKit replays only spoken turns), so matching it here
keeps what the tests prove honest about what happens on a real call.
"""

from __future__ import annotations

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage
from langgraph.errors import GraphRecursionError

from receptionist.core.models import CallRecord
from receptionist.worker.agent.graph import RECURSION_LIMIT, STUCK, build_graph
from receptionist.worker.agent.tools import CallContext
from receptionist.worker.booking.service import CalendarService
from receptionist.worker.profiles import Profile


class Conversation:
    """One call, driven by text."""

    def __init__(
        self,
        profile: Profile,
        calendar: CalendarService,
        record: CallRecord,
        model: BaseChatModel | None = None,
    ) -> None:
        self.profile = profile
        self.call = CallContext(calendar=calendar, record=record)
        self._graph = build_graph(profile, model)
        self._history: list[AnyMessage] = []

    @property
    def over(self) -> bool:
        """True once the agent has hung up — read it after the reply has been delivered."""
        return self.call.over

    def greet(self) -> str:
        self.call.record.said("agent", self.profile.greeting)
        self._history.append(AIMessage(self.profile.greeting))
        return self.profile.greeting

    async def say(self, caller_text: str) -> str:
        self.call.record.said("caller", caller_text)
        self._history.append(HumanMessage(caller_text))
        try:
            result = await self._graph.ainvoke(
                {"messages": self._history},
                context=self.call,
                config={"recursion_limit": RECURSION_LIMIT},
            )
            reply = str(result["messages"][-1].text).strip()
        except GraphRecursionError:
            reply = STUCK
        self.call.record.said("agent", reply)
        self._history.append(AIMessage(reply))
        return reply
