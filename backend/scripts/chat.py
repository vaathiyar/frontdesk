"""Text REPL to chat with a receptionist profile — no telephony, STT, or TTS.

    uv run python scripts/chat.py hvac

Type as the caller; watch the agent book/answer/take a message. Bookings hit a real
Google Calendar when the profile has an id in RECEPTIONIST_CALENDAR_IDS; otherwise a
seeded in-memory fake is used. On exit it prints the resulting CallRecord: outcome,
captured fields, the code-emitted decision timeline, and the signed share link — the
fastest way to iterate on prompts and tools before wiring the voice stack.

Needs GOOGLE_API_KEY (Gemini). Real calendar bookings also need
GOOGLE_CREDENTIALS_FILE_PATH (a service account with the Calendar API enabled) and
RECEPTIONIST_CALENDAR_IDS. See docs/config.md.
"""

from __future__ import annotations

import argparse
import asyncio

from receptionist.agent.runner import ConversationRunner
from receptionist.core.models import CallRecord, TranscriptTurn
from receptionist.profiles.factory import PROFILES, UnknownProfile, create_profile
from receptionist.providers.factory import build_calendar, build_chat

_AUTH_ERROR_TOKENS = (
    "api key",
    "api_key",
    "credential",
    "unauthenticated",
    "permission denied",
    "401",
    "403",
)


def _looks_like_auth_error(exc: Exception) -> bool:
    return any(token in str(exc).lower() for token in _AUTH_ERROR_TOKENS)


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
    try:
        # Real Google Calendar when this profile has an id in RECEPTIONIST_CALENDAR_IDS;
        # otherwise the in-memory fake — so this runs with or without calendar config.
        calendar = build_calendar(profile_id)
    except Exception as exc:  # e.g. missing/invalid service-account creds for a real calendar
        print(f"\n[error] couldn't initialize the calendar: {exc}")
        print("[hint] check GOOGLE_CREDENTIALS_FILE_PATH and RECEPTIONIST_CALENDAR_IDS")
        print("       (or unset RECEPTIONIST_CALENDAR_IDS to use the in-memory fake).")
        return
    try:
        agent = create_profile(profile_id, calendar, record)
    except UnknownProfile:
        print(f"Unknown profile {profile_id!r}. Choose one of: {', '.join(PROFILES)}")
        return

    try:
        messages_api = build_chat()  # names the vendor once; reads GOOGLE_API_KEY via settings
    except Exception as exc:  # most likely: no GOOGLE_API_KEY configured
        print(f"\n[error] couldn't initialize the chat model: {exc}")
        print("[hint] set GOOGLE_API_KEY (or add it to .env), then retry.")
        return

    runner = ConversationRunner(agent, messages_api)

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
        except Exception as exc:
            print(f"\n[error] {type(exc).__name__}: {exc}")
            # Only guess at credentials when the error actually looks like one — a blanket
            # "set GOOGLE_API_KEY" hint just sends you chasing the wrong thing.
            if _looks_like_auth_error(exc):
                print("[hint] check GOOGLE_API_KEY / GOOGLE_CREDENTIALS_FILE_PATH in .env.")
            return
        print(f"agent> {reply}")

    _print_summary(record)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", default="hvac", help="hvac | restaurant")
    parser.add_argument("--caller", default="+1-555-0100", help="caller ID to simulate")
    args = parser.parse_args()
    asyncio.run(_repl(args.profile, args.caller))


if __name__ == "__main__":
    main()
