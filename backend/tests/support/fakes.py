"""Doubles: a chat model you can script, and a call store that is a dict.

`ScriptedModel` replays the `AIMessage`s you hand it, in order. Build them with
`says(...)` for a spoken reply and `calls(...)` for a tool call — that's enough to
drive any path through the graph deterministically.

`FakeCallStore` stands in for CockroachDB, the same way `FakeCalendarService` stands in
for Google Calendar. Persistence itself is SQLAlchemy's and Alembic's problem, so no test
opens a database; what the suite still has to prove is that `finish_call` saves at all,
and saves *after* it has recorded whether the text went out.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from langchain_core.callbacks import CallbackManagerForLLMRun
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import PrivateAttr

from receptionist.core.models import CallRecord
from receptionist.worker.lib.datetimes import timezone

CALLER = "+16045550100"


class FakeCallStore:
    """An in-memory `CallStore`. `saved` is the write log, in order."""

    def __init__(self) -> None:
        self.calls: dict[UUID, CallRecord] = {}
        self.saved: list[CallRecord] = []

    async def save(self, record: CallRecord) -> None:
        # Deep-copied, so a test can assert on what was saved at the time rather than on
        # whatever the caller mutated the record into afterwards.
        stored = record.model_copy(deep=True)
        self.calls[record.id] = stored
        self.saved.append(stored)

    async def get(self, call_id: UUID) -> CallRecord | None:
        return self.calls.get(call_id)


def day_after(days: int) -> str:
    """An ISO date relative to today in the business timezone — the form tools expect."""
    return (datetime.now(timezone()) + timedelta(days=days)).date().isoformat()


def says(text: str) -> AIMessage:
    return AIMessage(content=text)


def calls(tool: str, /, **args: Any) -> AIMessage:
    """An AIMessage asking for one tool call. `tool` is positional-only so it can't
    collide with a tool argument of its own called `tool`."""
    return AIMessage(content="", tool_calls=[{"name": tool, "args": args, "id": f"call_{tool}"}])


class ScriptedModel(BaseChatModel):
    """Replays `replies` in order. Once exhausted it says a neutral closing line, so a
    test that under-scripts fails on an assertion rather than hanging.

    Set `loop=True` to repeat the script forever — used to prove the recursion cap.
    """

    replies: list[AIMessage] = []
    loop: bool = False
    prompts: list[list[BaseMessage]] = []

    _sent: int = PrivateAttr(default=0)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools: Any, **kwargs: Any) -> BaseChatModel:
        # The script decides what gets called; the real schemas are asserted elsewhere.
        return self

    def _next_reply(self) -> AIMessage:
        if self._sent < len(self.replies):
            return self.replies[self._sent]
        if self.loop and self.replies:
            return self.replies[self._sent % len(self.replies)]
        return says("Anything else I can help with?")

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        self.prompts.append(list(messages))
        reply = self._next_reply()
        self._sent += 1
        # A fresh id each time: `add_messages` merges by id, so replaying one message
        # object would overwrite the earlier copy instead of appending a new turn.
        return ChatResult(
            generations=[ChatGeneration(message=reply.model_copy(update={"id": None}))]
        )
