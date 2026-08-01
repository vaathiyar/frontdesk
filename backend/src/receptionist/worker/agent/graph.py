"""The brain: a two-node graph that lets the model use tools until it has an answer.

    START -> model -> (tools -> model)* -> END

That's the whole control flow. `model` decides; `tools` acts; the edge back to `model`
is what makes it recursive. Everything domain-specific lives in the prompt and the
tools, not here — which is why adding a profile never touches this file.

The LiveKit voice worker drives it in production; the suite drives the same compiled
graph by text (`tests/support/conversation.py`), so what the tests prove is what answers the phone.
"""

from __future__ import annotations

from typing import Annotated, Any, Final, Literal, TypedDict

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AnyMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.graph import END, START, StateGraph, add_messages
from langgraph.prebuilt import ToolNode

from receptionist.settings import settings
from receptionist.worker.agent.prompt import render
from receptionist.worker.agent.tools import CallContext, explain_to_model
from receptionist.worker.profiles import Profile

CHAT_MODEL = "gemini-3.5-flash-lite"
CHAT_EFFORT = "medium"  # thinking_level — Google's recommendation for agentic tool use
CHAT_MAX_TOKENS = 4096

MAX_TOOL_ROUNDS = 8
# LangGraph counts node executions, not tool rounds, and its default is effectively
# unlimited (10007) — so this has to be passed on every run to cap a stuck loop.
RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 1

STUCK = "Sorry, I'm having trouble with that. Let me take a message instead."


# The graph's two nodes. `Final` so these read as the literal strings the routing
# annotation below names, rather than as plain `str`.
MODEL: Final = "model"
TOOLS: Final = "tools"


class State(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def route_from_model(state: State) -> Literal["tools", "__end__"]:
    """Either the model asked for a tool, or it has an answer and the turn is over.

    The return annotation is load-bearing, not decoration: LangGraph builds the routing
    map from it and checks at compile time that the target node exists. Drop it and a
    wrong node name stops being a build error and becomes a silent runtime halt.
    """
    last = state["messages"][-1]
    return TOOLS if getattr(last, "tool_calls", None) else END


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
    tools = list(profile.tools)
    llm = (model or chat_model()).bind_tools(tools)

    async def call_model(state: State) -> dict[str, list[AnyMessage]]:
        # Rendered per turn so the prompt's "today" never goes stale in a long-lived worker.
        system = SystemMessage(render(profile))
        return {"messages": [await llm.ainvoke([system, *state["messages"]])]}

    builder = StateGraph(State, context_schema=CallContext)
    builder.add_node(MODEL, call_model)
    builder.add_node(TOOLS, ToolNode(tools, handle_tool_errors=explain_to_model))
    builder.add_edge(START, MODEL)
    builder.add_conditional_edges(MODEL, route_from_model)
    builder.add_edge(TOOLS, MODEL)
    return builder.compile()
