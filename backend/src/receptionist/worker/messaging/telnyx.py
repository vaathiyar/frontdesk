"""Sending the confirmation text — one POST to Telnyx.

No vendor SDK: this is a single endpoint, `httpx` is already a dependency, and the
official package is a 250-release surface whose PyPI token was hijacked in March 2026.

Credentials are settled at **startup** (`require_credentials`), not per call. A text that
silently never arrives is the hardest failure here to notice, and by the time it would be
noticed the caller has hung up — so a worker that cannot text refuses to run at all.

What is left per call is about the call itself: a number we shouldn't text, or a caller who
withheld theirs. Those are `SmsSkipped`, decided before any network call, and every path
logs its reason.

The message goes out **from the number that was dialled** when the call supplies one, so a
caller sees the business they rang. `TELNYX_FROM_NUMBER` is the fallback for when nobody
dialled anything.
"""

from __future__ import annotations

import logging
import re

import httpx

from receptionist.settings import settings
from receptionist.worker.lib.phone import E164

logger = logging.getLogger(__name__)

TELNYX_MESSAGES = "https://api.telnyx.com/v2/messages"
TIMEOUT_SECONDS = 10

# +1 (xxx) 555-01xx is reserved for fiction, and the suite's default caller lives there —
# so a test run can't text a stranger even with real credentials loaded.
RESERVED_FOR_FICTION = re.compile(r"^\+1\d{3}55501\d{2}$")


class SmsError(RuntimeError):
    """Telnyx rejected the message."""


class SmsSkipped(RuntimeError):
    """We declined to send this particular message, before any network call.

    Not a prediction of what Telnyx would say — a decision that we should not be asking
    it. A caller who withheld their number cannot be texted, and the reserved fictional
    range must never reach Telnyx at all, because Telnyx would happily deliver to it.

    Missing credentials are *not* one of these: they stop the worker at startup.
    """


class TelnyxNotConfigured(RuntimeError):
    """We could not text anyone, so there is no point answering the phone."""


def require_credentials() -> None:
    """Refuse to start without what it takes to text a caller.

    Checked once, at startup. Every call ends in a confirmation text, so discovering the
    key is missing on the first one means the caller has already hung up unnotified — and
    a skipped text is only ever a log line, which is exactly the failure nobody sees.
    """
    if not settings.telnyx_api_key.strip():
        raise TelnyxNotConfigured("TELNYX_API_KEY is not set.")
    # Only the *configured* fallback is a startup concern. The dialled number arrives with
    # the call, so a malformed one is call data and stays a per-call skip below.
    fallback = settings.telnyx_from_number.strip()
    if fallback and not E164.match(fallback):
        raise TelnyxNotConfigured(f"TELNYX_FROM_NUMBER {fallback!r} is not an E.164 number.")


def sender(from_number: str | None = None) -> str:
    """The number to send from: the one that was dialled, else the configured default."""
    return (from_number or settings.telnyx_from_number).strip()


def skip_reason(to: str, from_number: str | None = None) -> str | None:
    """Why *this* message cannot go out, or None if it can. Phrased for a log line.

    Only about the call: credentials were settled at startup by `require_credentials`.
    """
    outgoing = sender(from_number)
    if not outgoing:
        return "no from-number: the call supplied none and TELNYX_FROM_NUMBER is not set"
    if not E164.match(outgoing):
        return f"from-number {outgoing!r} is not an E.164 number"
    if not E164.match(to):
        return f"{to!r} is not an E.164 number"
    if RESERVED_FOR_FICTION.match(to):
        return f"{to} is in the +1 (xxx) 555-01xx range reserved for fiction"
    return None


async def send_sms(to: str, text: str, from_number: str | None = None) -> str:
    """Send one SMS and return the Telnyx message id.

    Three outcomes, each carrying its own reason: the id on success, `SmsSkipped` if we
    declined before the network, `SmsError` if Telnyx refused.

    `from_number` is the DID the caller dialled; omit it and the configured default is
    used. The message body is never logged — it carries a signed link.
    """
    skipped = skip_reason(to, from_number)
    if skipped:
        logger.warning("sms to %s not sent: %s", to, skipped)
        raise SmsSkipped(skipped)

    outgoing = sender(from_number)
    logger.info("sending sms %s -> %s (%d chars)", outgoing, to, len(text))
    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.post(
            TELNYX_MESSAGES,
            json={"from": outgoing, "to": to, "text": text},
            headers={"Authorization": f"Bearer {settings.telnyx_api_key}"},
        )
    if response.is_error:
        why = _why(response)
        logger.error("telnyx rejected %s -> %s: %s %s", outgoing, to, response.status_code, why)
        raise SmsError(f"telnyx {response.status_code}: {why}")
    message_id: str = response.json()["data"]["id"]
    logger.info("sms sent %s -> %s: %s", outgoing, to, message_id)
    return message_id


def _why(response: httpx.Response) -> str:
    """Telnyx returns {"errors": [{code, title, detail}]}; surface it for the log."""
    try:
        errors = response.json().get("errors", [])
    except ValueError:
        return response.text
    return (
        "; ".join(f"{e.get('code')} {e.get('title')}: {e.get('detail')}" for e in errors)
        or response.text
    )
