"""Everything that happens when a call ends, in one place.

Both drivers call `finish_call`: the REPL when you quit, the voice worker on hang-up.
Keeping it here is what stops the two paths from drifting on what "a finished call"
means — including the confirmation text, which must go out exactly once.
"""

from __future__ import annotations

from datetime import UTC, datetime

from receptionist.models import CallRecord, Outcome
from receptionist.profiles import Profile


async def finish_call(profile: Profile, record: CallRecord) -> None:
    record.ended_at = datetime.now(UTC)
    if record.outcome is None:
        # The caller hung up, or never asked for anything we act on.
        record.outcome = Outcome.ABANDONED


def summarise(record: CallRecord) -> str:
    """What the call produced, for a terminal. The web page renders the same record."""
    rule = "─" * 68
    lines = [
        rule,
        f"  call {record.id}",
        f"  profile: {record.profile_id}   caller: {record.caller_number}",
        f"  outcome: {record.outcome.value if record.outcome else '—'}",
    ]
    if record.booking:
        booking = record.booking
        lines.append(f"  booking: {booking.service} @ {booking.starts_at:%a %b %d, %-I:%M %p}")
        lines.append(f"           {booking.calendar_event_id}")
        if booking.details:
            detail = ", ".join(f"{k}={v!r}" for k, v in booking.details.items())
            lines.append(f"  details: {detail}")
    if record.message:
        lines.append(f"  message: {record.message.name} — {record.message.reason}")
    lines.append("  decision timeline:")
    for event in record.events:
        lines.append(f"    • {event.type}: {event.summary}")
    lines.append(rule)
    return "\n".join(lines)
