"""Put a call in the database, so the connection, the API and the SPA can be exercised
without placing a real phone call.

Dev tooling: it lives outside `src/receptionist/` and adds nothing to either process.
Every type it touches is one the agent already writes — `CallRecord` and friends from
`core/models.py` — saved through the same `SqlCallStore` that `worker/lifecycle.py` uses
on hang-up, and linked with the same `call_url` that goes into the confirmation text. A
seeded call is therefore indistinguishable from a real one, which is the whole point.

    uv run python scripts/seed_call.py                # one booked HVAC call
    uv run python scripts/seed_call.py --kind all     # one of every shape the SPA renders
    uv run python scripts/seed_call.py --kind live    # a call still in progress

Needs `RECEPTIONIST_DATABASE_URL`, and the table to exist:
`uv run alembic upgrade head`.

Timestamps are laid out **relative to the call's start**, not stamped at insert time. That
matters for more than realism: the record page draws the call to scale, so a turn or an
event dated after `ended_at` would fall off the end of it.
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import UTC, datetime, timedelta

from psycopg.errors import UndefinedTable
from sqlalchemy.engine.url import make_url
from sqlalchemy.exc import ProgrammingError

from receptionist.core.db.engine import require_database
from receptionist.core.db.store import SqlCallStore
from receptionist.core.models import (
    Booking,
    CallEvent,
    CallRecord,
    Message,
    Outcome,
    TranscriptTurn,
)
from receptionist.settings import settings
from receptionist.worker.lib.datetimes import timezone
from receptionist.worker.lib.links import call_url

HVAC_NUMBER = "+16042969870"
KITCHEN_NUMBER = "+16042969871"


def _said(record: CallRecord, offset: int, role: str, text: str) -> None:
    """A turn `offset` seconds into the call."""
    record.transcript.append(
        TranscriptTurn(ts=record.started_at + timedelta(seconds=offset), role=role, text=text)
    )


def _did(record: CallRecord, offset: int, type: str, summary: str) -> None:
    """An event `offset` seconds into the call."""
    record.events.append(
        CallEvent(ts=record.started_at + timedelta(seconds=offset), type=type, summary=summary)
    )


def _tomorrow_at(hour: int) -> datetime:
    """Tomorrow at a whole hour, in the business timezone the agent books in."""
    tomorrow = datetime.now(timezone()) + timedelta(days=1)
    return tomorrow.replace(hour=hour, minute=0, second=0, microsecond=0)


def booked() -> CallRecord:
    """The hero path: a caller phones in and leaves with an appointment."""
    starts_at = _tomorrow_at(10)
    record = CallRecord(
        profile_id="hvac",
        business_name="Helpdesk Heating and Cooling",
        caller_number="+16045550100",
        called_number=HVAC_NUMBER,
        started_at=datetime.now(UTC) - timedelta(minutes=12),
        outcome=Outcome.BOOKED,
        booking=Booking(
            service="furnace repair",
            starts_at=starts_at,
            ends_at=starts_at + timedelta(hours=1),
            calendar_event_id="evt_seed_booked",
            details={
                "name": "Sam Lee",
                "address": "12 Oak St, Burnaby",
                "issue": "no heat upstairs since last night",
            },
        ),
    )
    record.ended_at = record.started_at + timedelta(seconds=224)
    _said(record, 0, "agent", "Thanks for calling Helpdesk Heating and Cooling. How can I help?")
    _said(record, 7, "caller", "My furnace quit overnight and the upstairs is freezing.")
    _said(record, 16, "agent", "Sorry to hear it. What day works for someone to come out?")
    _said(record, 24, "caller", "Tomorrow morning if you have anything.")
    _said(record, 38, "agent", "Nine is taken, but I can do ten tomorrow. Name and address?")
    _said(record, 52, "caller", "Sam Lee, twelve Oak Street in Burnaby.")
    _said(record, 61, "agent", "Booked you for ten tomorrow. You'll get a text with the details.")
    _did(record, 31, "availability_checked", "Tomorrow: 9:00 AM, 10:00 AM, 11:00 AM")
    _did(record, 34, "slot_declined", "9:00 AM was already taken")
    _did(record, 96, "booking_created", "furnace repair, tomorrow at 10:00 AM")
    _did(record, 210, "sms_sent", "to +16045550100 (msg_seed_booked)")
    return record


def message() -> CallRecord:
    """Nothing bookable, so the agent takes a message instead of guessing."""
    record = CallRecord(
        profile_id="restaurant",
        business_name="Helpdesk Kitchen",
        caller_number="+16045550177",
        called_number=KITCHEN_NUMBER,
        started_at=datetime.now(UTC) - timedelta(hours=3),
        outcome=Outcome.MESSAGE_TAKEN,
        message=Message(name="Dana", reason="private dining for 20 in October"),
    )
    record.ended_at = record.started_at + timedelta(seconds=51)
    _said(record, 0, "agent", "Thanks for calling Helpdesk Kitchen. How can I help you today?")
    _said(record, 6, "caller", "Do you do private events? I need a room for twenty in October.")
    _said(
        record, 15, "agent", "That's beyond what I can book. Can I take your name and pass it on?"
    )
    _said(record, 23, "caller", "Dana.")
    _said(record, 30, "agent", "Got it, Dana. Someone will call you back about October.")
    _did(record, 33, "message_taken", "Dana - private dining for 20 in October")
    _did(record, 44, "sms_sent", "to +16045550177 (msg_seed_message)")
    return record


def cancelled() -> CallRecord:
    """A deliberate cancellation — handled, but not a booking."""
    record = CallRecord(
        profile_id="hvac",
        business_name="Helpdesk Heating and Cooling",
        caller_number="+16045550133",
        called_number=HVAC_NUMBER,
        started_at=datetime.now(UTC) - timedelta(days=1, minutes=20),
        outcome=Outcome.CANCELLED,
    )
    record.ended_at = record.started_at + timedelta(seconds=39)
    _said(record, 0, "agent", "Thanks for calling Helpdesk Heating and Cooling. How can I help?")
    _said(record, 5, "caller", "I need to cancel my tune-up on Friday.")
    _said(record, 14, "agent", "Done, that's cancelled. Anything else?")
    _did(record, 12, "booking_cancelled", "AC tune-up on Friday was removed from the calendar")
    _did(record, 30, "sms_sent", "to +16045550133 (msg_seed_cancelled)")
    return record


def live() -> CallRecord:
    """A call still on the line: no `ended_at`, no outcome, nothing booked yet.

    The one shape a real call only holds for a couple of minutes, and the one most likely
    to be rendered wrong — hence worth being able to seed on demand.
    """
    record = CallRecord(
        profile_id="hvac",
        business_name="Helpdesk Heating and Cooling",
        caller_number="+16045550199",
        called_number=HVAC_NUMBER,
        started_at=datetime.now(UTC) - timedelta(seconds=47),
    )
    _said(record, 0, "agent", "Thanks for calling Helpdesk Heating and Cooling. How can I help?")
    _said(record, 9, "caller", "Hi, I think my AC is leaking water.")
    _did(record, 21, "availability_checked", "Tomorrow: 8:00 AM, 9:00 AM, 1:00 PM")
    return record


SHAPES = {"booked": booked, "message": message, "cancelled": cancelled, "live": live}


async def seed(kinds: list[str]) -> None:
    require_database()
    store = SqlCallStore()

    where = make_url(settings.database_url).render_as_string(hide_password=True)
    print(f"Seeding {len(kinds)} call(s) into {where}\n")

    for kind in kinds:
        record = SHAPES[kind]()
        try:
            await store.save(record)
        except ProgrammingError as exc:
            # Overwhelmingly this is an un-migrated database, and the raw SQLAlchemy
            # traceback buries the one line that says what to do about it.
            if isinstance(exc.orig, UndefinedTable):
                raise SystemExit(
                    "The `calls` table does not exist yet. Create it with:\n"
                    "    uv run alembic upgrade head"
                ) from exc
            raise
        outcome = record.outcome.value if record.outcome else "none (still on the line)"
        print(f"  {kind:<10} {record.id}")
        print(f"  {'':<10} {record.business_name} - {outcome}")
        print(f"  {'':<10} open  {call_url(record.id)}")
        print(f"  {'':<10} api   /api/calls/{record.id}\n")

    print(
        "The 'open' links use RECEPTIONIST_PUBLIC_BASE_URL, which must point at the SPA\n"
        f"(currently {settings.public_base_url}). The SPA reads /api/calls/{{id}} in turn."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--kind",
        choices=[*SHAPES, "all"],
        default="booked",
        help="which shape of call to store (default: booked)",
    )
    args = parser.parse_args()
    asyncio.run(seed(list(SHAPES) if args.kind == "all" else [args.kind]))


if __name__ == "__main__":
    main()
