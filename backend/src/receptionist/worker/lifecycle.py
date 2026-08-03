"""Everything that happens when a call ends, in one place.

The voice worker calls `finish_call` on hang-up, and the suite calls the same function,
so what "a finished call" means is stated once.

Order matters. The text goes out first and the outcome of sending is recorded on the
record, so the saved call says whether the caller was actually told. A failed text must
never cost us the record itself.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from receptionist.core.db.store import CallStore, SqlCallStore
from receptionist.core.models import CallRecord, Outcome
from receptionist.worker.messaging.compose import compose_sms
from receptionist.worker.messaging.telnyx import SmsError, SmsSkipped, send_sms
from receptionist.worker.profiles import Profile

logger = logging.getLogger(__name__)


async def finish_call(
    profile: Profile, record: CallRecord, *, store: CallStore | None = None
) -> str:
    """Close the call, text the caller, persist it. Returns the text that was composed."""
    record.ended_at = datetime.now(UTC)
    if record.outcome is None:
        record.outcome = _what_happened(record)

    text = compose_sms(profile, record)
    if text:
        await _notify(record, text)

    await (store or SqlCallStore()).save(record)
    return text


async def _notify(record: CallRecord, text: str) -> None:
    """Send the confirmation, and record on the call whether it went.

    Every outcome lands on the record, so the saved call says whether the caller was
    actually told. Nothing propagates: a failed text must not cost us the record.
    """
    # The text goes out from the number that was dialled, so the caller sees the
    # business they rang. None when the call supplied none, and the default takes over.
    from_number = record.called_number or None
    try:
        message_id = await send_sms(record.caller_number, text, from_number)
    except SmsSkipped as exc:
        # Expected off the phone path: no credentials, or a number we must not text.
        record.emit("sms_skipped", str(exc))
    except SmsError as exc:
        logger.warning("could not text %s: %s", record.caller_number, exc)
        record.emit("sms_failed", str(exc))
    else:
        record.emit("sms_sent", f"to {record.caller_number} ({message_id})")


def _what_happened(record: CallRecord) -> Outcome:
    """No tool set an outcome, so infer one from whether the caller got anywhere.

    A caller who asked something and was answered has been served — recording that as
    ABANDONED would misreport the call to the business owner. Nothing is texted either
    way: someone who only asked the opening hours does not want a follow-up message.
    """
    if any(turn.role == "caller" for turn in record.transcript):
        return Outcome.ANSWERED
    return Outcome.ABANDONED
