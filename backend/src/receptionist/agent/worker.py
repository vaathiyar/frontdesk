"""The LiveKit voice worker: the same graph, with a phone line attached.

One job is one call. LiveKit owns the real-time mechanics — voice activity, transcription,
barge-in, speech — and hands each caller turn to `llm_node`, which is the whole
integration: convert LiveKit's history into messages, run the graph, stream back the
words to speak.

No tools are declared here. The graph already owns them, so the voice path and the text
REPL cannot drift apart.
"""

# `livekit.*` is an opaque vendor boundary under our mypy config, so `Agent` reads as
# `Any`: subclassing it is a "subclass Any" and the event decorators are untyped. Suppress
# exactly those two codes for this one file — the rest of the package stays strict.
# mypy: disable-error-code="misc, untyped-decorator"

from __future__ import annotations

import json
import logging
import os
from collections.abc import AsyncIterable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli
from livekit.plugins import langchain

from receptionist.agent.graph import RECURSION_LIMIT, STUCK, build_graph
from receptionist.agent.providers import build_stt, build_tts, load_vad
from receptionist.agent.tools import CallContext
from receptionist.finish import finish_call, summarise
from receptionist.models import CallRecord
from receptionist.profiles import Profile, get_profile
from receptionist.services.calendar import build_calendar
from receptionist.settings import settings

logger = logging.getLogger("receptionist.worker")

AGENT_NAME = "receptionist"

_ROLES = {
    "user": HumanMessage,
    "assistant": AIMessage,
    "system": SystemMessage,
    "developer": SystemMessage,
}


class ReceptionistAgent(Agent):
    """A LiveKit agent whose every turn is one run of the graph."""

    def __init__(
        self, profile: Profile, call: CallContext, model: BaseChatModel | None = None
    ) -> None:
        self._graph = build_graph(profile, model)
        self._call = call
        # instructions="" because the system prompt lives in the graph; anything here
        # would be injected as a second, competing system message.
        #
        # llm= must be non-None or LiveKit silently skips the caller's turn. The adapter
        # is never actually driven — `llm_node` below replaces it — because at its default
        # settings it streams tool results straight to TTS, and the caller hears
        # "Open on Monday: 9:00 AM, 10:00 AM..." read aloud before the actual answer.
        super().__init__(instructions="", llm=langchain.LLMAdapter(self._graph))

    async def llm_node(self, chat_ctx: Any, tools: Any, model_settings: Any) -> AsyncIterable[str]:
        messages = [
            _ROLES[message.role](content=message.text_content, id=message.id)
            for message in chat_ctx.messages()
            if message.role in _ROLES and message.text_content
        ]
        try:
            async for chunk, _ in self._graph.astream(
                {"messages": messages},
                context=self._call,
                config={"recursion_limit": RECURSION_LIMIT},
                stream_mode="messages",
            ):
                # Only the model's own words are spoken. Tool results travel this same
                # stream, and reading them out is the one thing the plain adapter gets
                # wrong, so this filter is the point of overriding llm_node at all.
                #
                # AIMessage, not AIMessageChunk: a streaming model emits chunks but one
                # that isn't streaming emits a whole AIMessage, and matching only the
                # chunk type would leave the caller listening to silence. ToolMessage is
                # not an AIMessage, so it stays out either way.
                if isinstance(chunk, AIMessage) and chunk.text:
                    yield chunk.text
        except GraphRecursionError:
            yield STUCK


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    profile = get_profile(_profile_id(ctx))
    record = CallRecord(profile_id=profile.id, caller_number=_caller_number(ctx))
    call = CallContext(calendar=build_calendar(profile), record=record)
    logger.info("call started: profile=%s caller=%s", profile.id, record.caller_number)

    session = AgentSession(vad=_vad(ctx), stt=build_stt(), tts=build_tts())

    @session.on("conversation_item_added")
    def _remember(event: Any) -> None:
        """Keep the CallRecord's transcript in step with what was actually said."""
        role = getattr(event.item, "role", None)
        text = getattr(event.item, "text_content", None)
        if not text or role not in ("user", "assistant"):
            return
        said = "caller" if role == "user" else "agent"
        last = record.transcript[-1] if record.transcript else None
        if last and last.role == said and last.text == text:
            return  # the greeting is recorded directly; don't record it twice
        record.said(said, text)

    @session.on("agent_state_changed")
    def _hang_up_when_finished_speaking(event: Any) -> None:
        """`end_call` only marks the call over. Cutting the line mid-goodbye is worse
        than the caller waiting a beat, so wait until the words have actually played."""
        if call.over and event.old_state == "speaking" and event.new_state != "speaking":
            logger.info("agent hung up: outcome=%s", record.outcome)
            ctx.delete_room()

    async def _finalize() -> None:
        text = await finish_call(profile, record)
        print(summarise(record))
        if text:
            print(f"  confirmation text to {record.caller_number}:\n{text}\n")

    ctx.add_shutdown_callback(_finalize)

    await session.start(agent=ReceptionistAgent(profile, call), room=ctx.room)
    # A fixed greeting, spoken straight through TTS: no model round-trip, so it lands
    # inside a second and always names the business.
    record.said("agent", profile.greeting)
    await session.say(profile.greeting)


def prewarm(proc: JobProcess) -> None:
    """Load the voice-activity model before any call arrives, once per worker process."""
    proc.userdata["vad"] = load_vad()


def _vad(ctx: JobContext) -> Any:
    vad = ctx.proc.userdata.get("vad")
    return vad if vad is not None else load_vad()


def _profile_id(ctx: JobContext) -> str:
    """Which business this call is for: the SIP dispatch rule's metadata, else the
    configured default for a local `console` run."""
    try:
        metadata = json.loads(ctx.job.metadata or "{}")
        if isinstance(metadata, dict) and metadata.get("profile_id"):
            return str(metadata["profile_id"])
    except (ValueError, TypeError):
        logger.warning("could not read job metadata; falling back to the default profile")
    return os.getenv("RECEPTIONIST_PROFILE") or settings.profile


def _caller_number(ctx: JobContext) -> str:
    """The caller's number, which is how reschedule and cancel find their booking and
    where the confirmation text goes. Absent in `console` mode, which must still run."""
    try:
        for participant in ctx.room.remote_participants.values():
            number = participant.attributes.get("sip.phoneNumber")
            # Must be a real string: in console mode the room is a MagicMock, whose
            # every attribute is truthy, and a mock's repr was ending up on the record
            # as the caller's number.
            if isinstance(number, str) and number.strip():
                return number.strip()
    except Exception:  # pragma: no cover - console mode must never break on this
        pass
    return "local-console"


def main() -> None:
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=AGENT_NAME)
    )


if __name__ == "__main__":
    main()
