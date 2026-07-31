"""Sending the confirmation text — one POST to Telnyx.

No vendor SDK: this is a single endpoint, `httpx` is already a dependency, and the
official package is a 250-release surface whose PyPI token was hijacked in March 2026.

With no credentials configured, or a number we shouldn't text, nothing is sent and
`SmsSkipped` says why — so the dev REPL and the test suite never message a real phone,
and never touch the network to find that out. Every path logs, because a text that
silently never arrives is the hardest thing here to notice.

The message goes out **from the number that was dialled** when the call supplies one, so a
caller sees the business they rang. `TELNYX_FROM_NUMBER` is the fallback for the console
and the REPL, where nobody dialled anything.
"""

from __future__ import annotations

import logging
import re

import httpx

from receptionist.phone import E164
from receptionist.settings import settings

logger = logging.getLogger(__name__)

TELNYX_MESSAGES = "https://api.telnyx.com/v2/messages"
TIMEOUT_SECONDS = 10

# +1 (xxx) 555-01xx is reserved for fiction, and the dev REPL's default caller lives
# there — so a local run can't text a stranger even with real credentials loaded.
RESERVED_FOR_FICTION = re.compile(r"^\+1\d{3}55501\d{2}$")


class SmsError(RuntimeError):
    """Telnyx rejected the message."""


class SmsSkipped(RuntimeError):
    """We declined to send, before any network call.

    Not a prediction of what Telnyx would say — a decision that we should not be asking
    it. Unset credentials are a mode, not a failure: the REPL and the offline suite run
    that way deliberately. And the reserved fictional range must never reach Telnyx at
    all, because Telnyx would happily deliver to it.
    """


def sender(from_number: str | None = None) -> str:
    """The number to send from: the one that was dialled, else the configured default."""
    return (from_number or settings.telnyx_from_number).strip()


def skip_reason(to: str, from_number: str | None = None) -> str | None:
    """Why this message cannot go out, or None if it can. Phrased for a log line."""
    outgoing = sender(from_number)
    if not settings.telnyx_api_key:
        return "TELNYX_API_KEY is not set"
    if not outgoing:
        return "no from-number: the call supplied none and TELNYX_FROM_NUMBER is not set"
    if not E164.match(outgoing):
        return f"from-number {outgoing!r} is not an E.164 number"
    if not E164.match(to):
        return f"{to!r} is not an E.164 number"
    if RESERVED_FOR_FICTION.match(to):
        return f"{to} is in the +1 (xxx) 555-01xx range reserved for fiction"
    return None


def can_send(to: str, from_number: str | None = None) -> bool:
    return skip_reason(to, from_number) is None


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
