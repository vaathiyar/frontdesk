"""Composing the confirmation text.

Split deliberately: the model writes the warm opening, code writes the facts. The
prompt forbids it from stating the date or time, because a hallucinated appointment
time in a message going out under the business's name is the one error that actually
costs someone a morning. If the model call fails, the facts go out on their own.
"""

from __future__ import annotations

import logging

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from receptionist.core.models import CallRecord, Outcome
from receptionist.worker.lib.datetimes import fmt_time
from receptionist.worker.lib.links import call_url
from receptionist.worker.profiles import Profile

logger = logging.getLogger(__name__)

PROSE_PROMPT = """Write the opening of a text message to someone who has just phoned \
{business}. One or two short sentences, warm and plain.

Say what they called about, and echo back one detail they gave you if it's worth \
confirming. Do NOT state the appointment date or time, and do not add a sign-off or a \
link: an exact confirmation line is appended after your text. Use plain ASCII only — no \
dashes, no emoji, no curly quotes."""

# Characters an LLM reaches for that would flip the whole SMS from GSM-7 (160 chars a
# segment) to UCS-2 (70), doubling the cost of every message.
SMART_CHARACTERS = {
    "—": "-",
    "–": "-",
    "‘": "'",
    "’": "'",
    "“": '"',
    "”": '"',
    "…": "...",
    " ": " ",
}


def plain(text: str) -> str:
    """ASCII only, so the message stays one segment per 160 characters."""
    for fancy, ascii_ in SMART_CHARACTERS.items():
        text = text.replace(fancy, ascii_)
    return text.encode("ascii", "ignore").decode().strip()


async def compose_sms(
    profile: Profile, record: CallRecord, model: BaseChatModel | None = None
) -> str:
    """The text to send, or "" when the call produced nothing worth texting about."""
    facts = confirmation(profile, record)
    if not facts:
        return ""
    prose = await _prose(profile, record, model)
    return plain(f"{prose}\n\n{facts}" if prose else facts)


def confirmation(profile: Profile, record: CallRecord) -> str:
    """The part that has to be exactly right, so it is built from the record, not written."""
    lines = [profile.business]

    if record.booking:
        booking = record.booking
        moved = record.outcome is Outcome.RESCHEDULED
        lines.append(f"{'Moved' if moved else 'Booked'}: {booking.service}")
        lines.append(f"{booking.starts_at:%a %b %d} at {fmt_time(booking.starts_at)}")
        if address := booking.details.get("address"):
            lines.append(address)
    elif record.outcome is Outcome.CANCELLED:
        lines.append("Your appointment is cancelled.")
    elif record.message:
        lines.append("We have your message and someone will call you back.")
    else:
        return ""

    label = "Details + add to calendar:" if record.booking else "Call details:"
    return "\n".join([*lines, "", label, call_url(record.id)])


async def _prose(profile: Profile, record: CallRecord, model: BaseChatModel | None) -> str:
    if not record.transcript:
        return ""
    try:
        chat = model or _default_model()
        said = "\n".join(f"{turn.role}: {turn.text}" for turn in record.transcript)
        written = await chat.ainvoke(
            [
                SystemMessage(PROSE_PROMPT.format(business=profile.business)),
                HumanMessage(said),
            ]
        )
        return plain(str(written.text))
    except Exception as exc:
        # The facts still go out on their own; a nicer opening isn't worth a lost text.
        logger.warning("could not write the SMS opening, sending facts only: %s", exc)
        return ""


def _default_model() -> BaseChatModel:
    from receptionist.worker.agent.graph import chat_model

    return chat_model()
