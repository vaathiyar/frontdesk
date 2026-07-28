"""The brain: a two-node graph that lets the model use tools until it has an answer.

    START -> model -> (tools -> model)* -> END

That's the whole control flow. `model` decides; `tools` acts; the edge back to `model`
is what makes it recursive. Everything domain-specific lives in the prompt and the
tools, not here — which is why adding a profile never touches this file.

Two drivers share it: `Conversation` below (the REPL and the tests) and the LiveKit
voice worker (see voice/worker.py). Both feed it a text-only history, so what you
iterate on in text is what answers the phone.
"""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.errors import GraphRecursionError
from langgraph.graph import START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode, tools_condition

from receptionist.models import CallRecord
from receptionist.profiles import Profile
from receptionist.prompt import render
from receptionist.services.calendar import CalendarService
from receptionist.settings import settings
from receptionist.tools import SHARED_TOOLS, CallContext, explain_to_model

CHAT_MODEL = "gemini-3.5-flash-lite"
CHAT_EFFORT = "medium"  # thinking_level — Google's recommendation for agentic tool use
CHAT_MAX_TOKENS = 4096

MAX_TOOL_ROUNDS = 8
# LangGraph counts node executions, not tool rounds, and its default is effectively
# unlimited (10007) — so this has to be passed on every run to cap a stuck loop.
RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 1

STUCK = "Sorry, I'm having trouble with that. Let me take a message instead."


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def chat_model() -> BaseChatModel:
    # No temperature: this model uses fixed sampling and warns if you pass one.
    model: BaseChatModel = ChatGoogleGenerativeAI(
        model=CHAT_MODEL,
        google_api_key=settings.google_api_key or None,
        thinking_level=CHAT_EFFORT,
        max_tokens=CHAT_MAX_TOKENS,
    )
    return model


def build_graph(profile: Profile, model: BaseChatModel | None = None) -> Any:
    """Compile the graph for one profile. `model` is the seam tests inject a fake into."""
    tools = [*SHARED_TOOLS, profile.book, *profile.extra_tools]
    llm = (model or chat_model()).bind_tools(tools)

    async def call_model(state: State) -> dict[str, list[AnyMessage]]:
        # Rendered per turn so the prompt's "today" never goes stale in a long-lived worker.
        system = SystemMessage(render(profile))
        return {"messages": [await llm.ainvoke([system, *state["messages"]])]}

    builder = StateGraph(State, context_schema=CallContext)
    builder.add_node("model", call_model)
    builder.add_node("tools", ToolNode(tools, handle_tool_errors=explain_to_model))
    builder.add_edge(START, "model")
    builder.add_conditional_edges("model", tools_condition)
    builder.add_edge("tools", "model")
    return builder.compile()


class Conversation:
    """One call, driven by text. The REPL and the offline tests both talk to this.

    History is deliberately text-only — the caller said this, the agent said that. The
    voice path can't offer more than that (LiveKit replays only spoken turns), so
    matching it here keeps the two drivers honestly comparable.
    """

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
