"""What the confirmation text says.

**Every word is built from the record; none of it is written.** A wrong time in a message
going out under the business's name is the one error that actually costs someone a
morning, so the text is assembled from `CallRecord` and cannot say anything the call did
not produce.

An earlier version had Gemini write a warm opening above these facts. It was dropped: the
model reliably repeated the business name and the address that the facts state directly
below it, in a second, different format ("twelve Oak Street" over "12 Oak St, Burnaby"),
and the duplication pushed an ordinary booking to three SMS segments. A confirmation is
not the place for prose — the caller wants to know when someone is coming.

Every variant has the same shape, so a caller who has had one text can read the next at a
glance:

    <business>

    <Label>: <subject>
    <specifics>

    Details: <link>
"""

from __future__ import annotations

from datetime import datetime

from receptionist.core.models import CallRecord, Outcome
from receptionist.worker.lib.datetimes import fmt_time
from receptionist.worker.lib.links import call_url
from receptionist.worker.profiles import Profile

# Characters an LLM reaches for that would flip the whole SMS from GSM-7 (160 chars a
# segment) to UCS-2 (70), doubling the cost of every message. Still needed with the prose
# gone: the service and the address reach the record as tool arguments, so they are the
# model's words even though these lines are not.
SMART_CHARACTERS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
}


def plain(text: str) -> str:
    """ASCII only, so the message stays one segment per 160 characters."""
    for fancy, ascii_ in SMART_CHARACTERS.items():
        text = text.replace(fancy, ascii_)
    return text.encode("ascii", "ignore").decode().strip()


def compose_sms(profile: Profile, record: CallRecord) -> str:
    """The text to send, or "" when the call produced nothing worth texting about."""
    lines = _outcome_lines(record)
    if not lines:
        return ""
    return plain("\n".join([profile.business, "", *lines, "", f"Details: {call_url(record.id)}"]))


def _outcome_lines(record: CallRecord) -> list[str]:
    """What happened, as a labelled line plus its specifics.

    Ordered by what the caller needs to see: a booking that exists outranks the outcome
    that produced it, which is why a reschedule is read off `booking` rather than off
    `Outcome.RESCHEDULED`.
    """
    if booking := record.booking:
        moved = record.outcome is Outcome.RESCHEDULED
        lines = [
            f"{'Moved' if moved else 'Booked'}: {_capitalised(booking.service)}",
            f"{_day(booking.starts_at)}, {fmt_time(booking.starts_at)}",
        ]
        if address := booking.details.get("address"):
            lines.append(address)
        return lines

    if record.outcome is Outcome.CANCELLED:
        # No service and no time: `worker/agent/tools.py` clears `booking` when it
        # cancels, because the appointment no longer exists. Naming it here would mean
        # reading it back out of an event summary, which is narration by another route.
        return ["Cancelled: your appointment"]

    if message := record.message:
        return [f"Message taken for {message.name}", "Someone will call you back."]

    return []


def _day(starts_at: datetime) -> str:
    """ "Wed Jul 9", not "Wed Jul 09" — and without `%-d`, which is glibc-only."""
    return f"{starts_at:%a %b} {starts_at.day}"


def _capitalised(service: str) -> str:
    """First letter only, so "AC tune-up" is not flattened to "Ac tune-up".

    The service is whatever the model passed to `book`, so its case is not ours to trust.
    """
    return service[:1].upper() + service[1:]
