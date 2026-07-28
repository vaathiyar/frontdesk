"""Chat with a receptionist profile as if you'd phoned it — no telephony, no audio.

    uv run python scripts/chat.py hvac
    uv run python scripts/chat.py restaurant --caller +16045550100

`--caller` is the number the call appears to come from: it's what reschedule and cancel
look bookings up by, and it's where the confirmation text goes when the call ends. Pass
your own mobile to actually receive it; the default is a test number, which prints the
message to the terminal instead of sending it.

Bookings hit a real Google Calendar when the profile has an id in
RECEPTIONIST_CALENDAR_IDS — pass --fake-calendar to keep them in memory instead. Needs
GOOGLE_API_KEY.
"""

from __future__ import annotations

import argparse
import asyncio
from textwrap import indent

import dotenv

dotenv.load_dotenv()

from receptionist.finish import finish_call, summarise  # noqa: E402
from receptionist.graph import Conversation  # noqa: E402
from receptionist.models import CallRecord  # noqa: E402
from receptionist.profiles import PROFILES, UnknownProfile, get_profile  # noqa: E402
from receptionist.services.calendar import FakeCalendarService, build_calendar  # noqa: E402

TEST_CALLER = "+15555550100"


async def call(profile_id: str, caller_number: str, fake_calendar: bool) -> None:
    try:
        profile = get_profile(profile_id)
    except UnknownProfile:
        print(f"Unknown profile {profile_id!r}. Choose one of: {', '.join(PROFILES)}")
        return

    calendar = (
        FakeCalendarService(profile.opens, profile.closes)
        if fake_calendar
        else build_calendar(profile)
    )
    record = CallRecord(profile_id=profile.id, caller_number=caller_number)
    chat = Conversation(profile, calendar, record)

    which = "in-memory" if isinstance(calendar, FakeCalendarService) else "Google Calendar"
    print(f"\n  {profile.business}   (profile: {profile.id}, caller: {caller_number})")
    print(f"  booking against: {which}")
    print("  Type as the caller. The agent hangs up when your business is done;")
    print("  'quit' or Ctrl-D hangs up from your end. Ctrl-C aborts without recording.\n")
    print(f"agent> {chat.greet()}")

    while True:
        try:
            said = (await asyncio.to_thread(input, "caller> ")).strip()
        except EOFError:
            # The caller hung up. Falling through to finish_call is the point: a dropped
            # call still has to be recorded, and still counts as abandoned.
            print()
            break
        if said.lower() in {"quit", "exit"}:
            break
        if not said:
            continue
        try:
            print(f"agent> {await chat.say(said)}")
        except Exception as exc:
            print(f"\n[error] {type(exc).__name__}: {exc}")
            if _looks_like_bad_credentials(exc):
                print("[hint] check GOOGLE_API_KEY / GOOGLE_CREDENTIALS_FILE_PATH in .env")
            return
        if chat.over:
            print("\n  [the agent ended the call]")
            break

    text = await finish_call(profile, record)
    print(summarise(record))
    if text:
        print(f"\n  confirmation text to {caller_number}:")
        print(indent(text, "  │ "))
        print()


def _looks_like_bad_credentials(exc: Exception) -> bool:
    text = str(exc).lower()
    return any(t in text for t in ("api key", "api_key", "credential", "unauthenticated", "403"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profile", nargs="?", default="hvac", help=" | ".join(PROFILES))
    parser.add_argument(
        "--caller",
        default=TEST_CALLER,
        help="the caller's number; where the confirmation text goes",
    )
    parser.add_argument(
        "--fake-calendar",
        action="store_true",
        help="book in memory even if this profile has a real Google Calendar configured",
    )
    args = parser.parse_args()
    try:
        asyncio.run(call(args.profile, args.caller, args.fake_calendar))
    except KeyboardInterrupt:
        # asyncio raises this inside the event loop, past the point where the call could
        # still be finalised. One line beats a traceback; use 'quit' for a clean hang-up.
        print("\n  [aborted — the call was not recorded]")


if __name__ == "__main__":
    main()
