"""One LiveKit session: the graph, with a phone line attached.

One job is one call. LiveKit owns the real-time mechanics — voice activity, transcription,
barge-in, speech — and hands each caller turn to `llm_node`, which is the whole
integration: convert LiveKit's history into messages, run the graph, stream back the
words to speak.

`main()` and `prewarm()` live here too, small as they are: they configure the worker that
runs these sessions, and splitting three lines into their own module would only add a file
to open.

No tools are declared here. The graph already owns them, so the voice path and what the
tests exercise cannot drift apart.
"""

# `livekit.*` is an opaque vendor boundary under our mypy config, so `Agent` reads as
# `Any`: subclassing it is a "subclass Any" and the event decorators are untyped. Suppress
# exactly those two codes for this one file — the rest of the package stays strict.
# mypy: disable-error-code="misc, untyped-decorator"

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterable
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.errors import GraphRecursionError
from livekit.agents import Agent, AgentSession, JobContext, JobProcess, WorkerOptions, cli
from livekit.plugins import langchain

from receptionist.core.db.engine import require_database
from receptionist.core.models import CallRecord
from receptionist.worker.agent.graph import RECURSION_LIMIT, STUCK, build_graph
from receptionist.worker.agent.tools import CallContext
from receptionist.worker.booking.service import build_calendar, require_calendar_ids
from receptionist.worker.lib.phone import to_e164
from receptionist.worker.lifecycle import finish_call
from receptionist.worker.messaging.telnyx import require_credentials
from receptionist.worker.profiles import PROFILES, Profile, get_profile
from receptionist.worker.voice.speech import build_stt, build_tts, load_vad

logger = logging.getLogger("receptionist.worker")

AGENT_NAME = "receptionist"

_ROLES = {
    "user": HumanMessage,
    "assistant": AIMessage,
    "system": SystemMessage,
    "developer": SystemMessage,
}


class MissingProfile(RuntimeError):
    """The SIP dispatch rule did not say which business this call is for."""


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
    record = CallRecord(
        profile_id=profile.id,
        business_name=profile.business,
        caller_number=_caller_number(ctx),
        called_number=_called_number(ctx),
    )
    call = CallContext(calendar=build_calendar(profile), record=record)
    logger.info(
        "call started: id=%s profile=%s caller=%s dialled=%s",
        record.id,
        profile.id,
        record.caller_number or "—",
        record.called_number or "—",
    )

    session = AgentSession(vad=ctx.proc.userdata["vad"], stt=build_stt(), tts=build_tts())
    _wire_session(session, ctx, profile, call)

    await session.start(agent=ReceptionistAgent(profile, call), room=ctx.room)
    # A fixed greeting, spoken straight through TTS: no model round-trip, so it lands
    # inside a second and always names the business.
    record.said("agent", profile.greeting)
    await session.say(profile.greeting)


def _wire_session(
    session: AgentSession, ctx: JobContext, profile: Profile, call: CallContext
) -> None:
    """Everything that has to happen while the call runs, and once as it ends."""
    record = call.record

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
        await finish_call(profile, record)
        # One line per call, and the event types say whether the text actually went.
        logger.info(
            "call finished: id=%s profile=%s outcome=%s events=[%s]",
            record.id,
            profile.id,
            record.outcome.value if record.outcome else "none",
            ", ".join(event.type for event in record.events),
        )

    ctx.add_shutdown_callback(_finalize)


def prewarm(proc: JobProcess) -> None:
    """Load the voice-activity model before any call arrives, once per worker process."""
    proc.userdata["vad"] = load_vad()


def _profile_id(ctx: JobContext) -> str:
    """Which business this call is for, from the SIP dispatch rule's metadata.

    There is no fallback. One worker answers several numbers as different businesses, so
    a job that doesn't name one cannot be guessed at — answering as the wrong business is
    worse than not answering at all.
    """
    try:
        metadata = json.loads(ctx.job.metadata or "{}")
    except ValueError as exc:
        raise MissingProfile(f"job metadata is not JSON: {exc}") from exc
    profile_id = metadata.get("profile_id") if isinstance(metadata, dict) else None
    if not profile_id:
        raise MissingProfile(
            "the SIP dispatch rule supplied no profile_id — see deploy/sip/provision.py"
        )
    return str(profile_id)


def _sip_attribute(ctx: JobContext, key: str) -> str:
    """One attribute off the SIP participant, or "" when there isn't one."""
    for participant in ctx.room.remote_participants.values():
        value = participant.attributes.get(key, "").strip()
        if value:
            return str(value)
    return ""


def _caller_number(ctx: JobContext) -> str:
    """The caller's number, which is how reschedule and cancel find their booking and
    where the confirmation text goes.

    Normalised here, at the edge: Telnyx hands the caller ID over as bare digits with no
    `+`, and this value is matched exactly against what a previous call stored. Empty when
    the caller withheld their number — the call is still answered, and the confirmation
    text is skipped with a recorded reason."""
    return to_e164(_sip_attribute(ctx, "sip.phoneNumber"))


def _called_number(ctx: JobContext) -> str:
    """The DID the caller dialled, which the confirmation text is sent *from* — so the
    caller sees the business they rang rather than an unrelated number.

    One trunk per DID (see deploy/sip/provision.py), so the trunk's number is the dialled
    one."""
    return to_e164(_sip_attribute(ctx, "sip.trunkPhoneNumber"))


def main() -> None:
    # Before the first call, not during it. A caller listening to the agent fall over is
    # the worst place to discover a profile has no calendar, and a confirmation text that
    # never goes out is worse still — nobody notices that one at all. A database the
    # worker cannot reach is the same failure again: the call goes fine, the text goes
    # out, and the link in it resolves to nothing.
    require_calendar_ids(PROFILES)
    require_credentials()
    require_database()
    cli.run_app(
        WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=AGENT_NAME)
    )


if __name__ == "__main__":
    main()
