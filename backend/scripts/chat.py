"""Text REPL to chat with a receptionist profile — no telephony, STT, or TTS.

    uv run python scripts/chat.py hvac

Type as the caller; watch the agent book/answer/take a message against a seeded
fake calendar. On exit it prints the resulting CallRecord: outcome, captured
fields, the code-emitted decision timeline, and the signed share link. This is
the fastest way to iterate on prompts and tools before wiring the voice stack.

Needs an LLM credential (ANTHROPIC_API_KEY, or `ant auth login`).
"""

from __future__ import annotations

import argparse
import asyncio

from receptionist.agent.runner import ConversationRunner
from receptionist.core.models import CallRecord, TranscriptTurn
from receptionist.profiles.factory import PROFILES, UnknownProfile, create_profile
from receptionist.services.calendar import FakeCalendarService


def _print_summary(record: CallRecord) -> None:
    line = "─" * 64
    print(f"\n{line}")
    print(f"  CallRecord {record.id}")
    print(f"  profile: {record.profile_id}   caller: {record.caller_number}")
    print(f"  outcome: {record.outcome.value if record.outcome else '—'}")
    if record.booking:
        b = record.booking
        print(f"  booking: {b.service} @ {b.slot}  ({b.calendar_event_id})")
    if record.fields:
        print("  fields:  " + ", ".join(f"{f.label}={f.value!r}" for f in record.fields))
    print("  decision timeline:")
    for event in record.events:
        print(f"    • {event.type}: {event.summary}")
    print(f"  share link: {record.share_path()}")
    print(line)


async def _repl(profile_id: str, caller_number: str) -> None:
    record = CallRecord(profile_id=profile_id, caller_number=caller_number)
    calendar = FakeCalendarService()
    try:
        agent = create_profile(profile_id, calendar, record)
    except UnknownProfile:
        print(f"Unknown profile {profile_id!r}. Choose one of: {', '.join(PROFILES)}")
        return

    try:
        from anthropic import AsyncAnthropic
    except ModuleNotFoundError:
        print("The `anthropic` package isn't installed. Run: uv sync --extra dev")
        return

    client = AsyncAnthropic()  # resolves ANTHROPIC_API_KEY or an `ant auth login` profile
    runner = ConversationRunner(agent, client.messages)

    print(f"\n  {agent.business_name}   (profile: {profile_id})")
    print("  Type as the caller. Ctrl-D or 'quit' to end the call.\n")
    print(f"agent> {agent.greeting}")
    record.transcript.append(TranscriptTurn(role="agent", text=agent.greeting))

    while True:
        try:
            caller = (await asyncio.to_thread(input, "caller> ")).strip()
        except EOFError:
            print()
            break
        if caller.lower() in {"quit", "exit"}:
            break
        if not caller:
            continue
        try:
            reply = await runner.send(caller)
        except Exception as exc:  # most likely: missing/invalid credential
            print(f"\n[error] {type(exc).__name__}: {exc}")
            print("[hint] set ANTHROPIC_API_KEY or run `ant auth login`, then retry.")
            return
        print(f"agent> {reply}")

    _print_summary(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", default="hvac", help="hvac | restaurant | auto")
    parser.add_argument("--caller", default="+1-555-0100", help="caller ID to simulate")
    args = parser.parse_args()
    asyncio.run(_repl(args.profile, args.caller))


if __name__ == "__main__":
    main()
