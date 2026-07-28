"""The LiveKit voice worker: an entrypoint that wires the STT -> LLM -> TTS session to
our `Receptionist` brain, plus `main()` that runs the worker CLI.

One job == one call. We resolve the profile, build its brain over a fresh `CallRecord`,
wrap it as a `ReceptionistAgent`, start an `AgentSession` with the provider stack, and
speak the profile's fixed greeting. A shutdown callback finalizes the record on hang-up
and prints the same summary as `scripts/chat.py` (outcome, booking, captured fields,
decision timeline) so a local `console` run shows the result.

Confirmed against livekit-agents 1.6.7:
- `await ctx.connect()`; `ctx.job.metadata` (str); `ctx.room`; `ctx.add_shutdown_callback(cb)`
  (accepts a zero-arg coroutine).
- `AgentSession(vad=, stt=, llm=, tts=)`; `await session.start(agent=, room=)`.
- `session.say(text)` returns an awaitable `SpeechHandle` — used for the fixed greeting
  (no LLM round-trip), which is why it is not itself a coroutine function.
- `WorkerOptions(entrypoint_fnc=, agent_name=)`; `cli.run_app(opts)`.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import UTC, datetime
from typing import cast

from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

from receptionist.agent.livekit_agent import ReceptionistAgent
from receptionist.core.models import CallRecord, Outcome
from receptionist.profiles.factory import create_profile
from receptionist.providers.factory import (
    build_calendar,
    build_llm,
    build_stt,
    build_tts,
    build_vad,
)
from receptionist.services.calendar import CalendarService

logger = logging.getLogger("receptionist.worker")

_DEFAULT_PROFILE = "hvac"


def _read_profile_id(ctx: JobContext) -> str:
    """profile_id from the job's JSON metadata, else `$RECEPTIONIST_PROFILE`, else the
    default. Never raises — a malformed metadata string just falls through."""
    try:
        metadata = json.loads(ctx.job.metadata or "{}")
        if isinstance(metadata, dict) and metadata.get("profile_id"):
            return str(metadata["profile_id"])
    except (ValueError, TypeError):
        pass
    return os.getenv("RECEPTIONIST_PROFILE") or _DEFAULT_PROFILE


def _read_caller_number(ctx: JobContext) -> str:
    """Best-effort caller ID from the SIP participant's `sip.phoneNumber` attribute.

    Falls back to "local-console" when there is no SIP participant (e.g. `console`/`dev`
    mode). Never raises — console mode must always work.
    """
    try:
        for participant in ctx.room.remote_participants.values():
            number = participant.attributes.get("sip.phoneNumber")
            if number:
                return str(number)
    except Exception:  # pragma: no cover - defensive; console mode must never break
        pass
    return "local-console"


def _log_summary(record: CallRecord) -> None:
    """Print the resulting CallRecord — mirrors `scripts/chat.py` so a local console test
    shows the outcome, booking, captured fields, and decision timeline on hang-up."""
    line = "─" * 64
    out = [
        line,
        f"  CallRecord {record.id}",
        f"  profile: {record.profile_id}   caller: {record.caller_number}",
        f"  outcome: {record.outcome.value if record.outcome else '—'}",
    ]
    if record.booking:
        b = record.booking
        out.append(f"  booking: {b.service} @ {b.slot}  ({b.calendar_event_id})")
    if record.fields:
        out.append("  fields:  " + ", ".join(f"{f.label}={f.value!r}" for f in record.fields))
    out.append("  decision timeline:")
    for event in record.events:
        out.append(f"    • {event.type}: {event.summary}")
    out.append(line)
    print("\n".join(out))


async def entrypoint(ctx: JobContext) -> None:
    await ctx.connect()

    profile_id = _read_profile_id(ctx)
    caller_number = _read_caller_number(ctx)
    logger.info("call started: profile=%s caller=%s", profile_id, caller_number)

    record = CallRecord(profile_id=profile_id, caller_number=caller_number)
    # `build_calendar()` is typed `object` (the vendor seam); it returns a CalendarService.
    # Profiles with a Google Calendar id configured get the real backend; the rest get the fake.
    calendar = cast(CalendarService, build_calendar(profile_id))
    brain = create_profile(profile_id, calendar, record)

    session = AgentSession(vad=build_vad(), stt=build_stt(), llm=build_llm(), tts=build_tts())

    async def _finalize() -> None:
        record.ended_at = datetime.now(UTC)
        if record.outcome is None:
            record.outcome = Outcome.ABANDONED
        logger.info("call ended: outcome=%s", record.outcome.value)
        _log_summary(record)

    ctx.add_shutdown_callback(_finalize)

    await session.start(agent=ReceptionistAgent(brain), room=ctx.room)
    # Fixed, deterministic greeting spoken straight through TTS (no LLM round-trip).
    # `say` returns an awaitable SpeechHandle; awaiting lets the greeting play before
    # we hand the turn to the caller.
    await session.say(brain.greeting)


def main() -> None:
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="receptionist"))


if __name__ == "__main__":
    main()
