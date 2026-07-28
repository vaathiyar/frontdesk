"""Everything that happens when a call ends, in one place.

Both drivers call `finish_call`: the REPL when you quit, the voice worker on hang-up.
Keeping it here is what stops the two paths from drifting on what a finished call means.

Order matters. The text goes out first and the outcome of sending is recorded on the
record, so the saved call says whether the caller was actually told. A failed text must
never cost us the record itself.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel

from receptionist.models import CallRecord, Outcome
from receptionist.profiles import Profile
from receptionist.services.sms import SmsError, send_sms
from receptionist.services.summary import compose_sms
from receptionist.store import CallStore

logger = logging.getLogger(__name__)


async def finish_call(
    profile: Profile,
    record: CallRecord,
    *,
    store: CallStore | None = None,
    model: BaseChatModel | None = None,
) -> str:
    """Close the call, text the caller, persist it. Returns the text that was composed."""
    record.ended_at = datetime.now(UTC)
    if record.outcome is None:
        record.outcome = _what_happened(record)

    text = await compose_sms(profile, record, model)
    if text:
        try:
            message_id = await send_sms(record.caller_number, text)
        except SmsError as exc:
            logger.warning("could not text %s: %s", record.caller_number, exc)
            record.emit("sms_failed", str(exc))
        else:
            if message_id:
                record.emit("sms_sent", f"to {record.caller_number} ({message_id})")
            else:
                record.emit("sms_skipped", "no Telnyx credentials for this number")

    await (store or CallStore()).save(record)
    return text


def _what_happened(record: CallRecord) -> Outcome:
    """No tool set an outcome, so infer one from whether the caller got anywhere.

    A caller who asked something and was answered has been served — recording that as
    ABANDONED would misreport the call to the business owner. Nothing is texted either
    way: someone who only asked the opening hours does not want a follow-up message.
    """
    if any(turn.role == "caller" for turn in record.transcript):
        return Outcome.ANSWERED
    return Outcome.ABANDONED


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
