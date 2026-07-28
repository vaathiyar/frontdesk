"""Sending the confirmation text — one POST to Telnyx.

No vendor SDK: this is a single endpoint, `httpx` is already a dependency, and the
official package is a 250-release surface whose PyPI token was hijacked in March 2026.

With no credentials configured, or a number we shouldn't text, nothing is sent and the
caller gets `None` back — so the dev REPL and the test suite never message a real phone.
"""

from __future__ import annotations

import re

import httpx

from receptionist.settings import settings

TELNYX_MESSAGES = "https://api.telnyx.com/v2/messages"
TIMEOUT_SECONDS = 10

E164 = re.compile(r"^\+[1-9]\d{7,14}$")
# +1 (xxx) 555-01xx is reserved for fiction, and the dev REPL's default caller lives
# there — so a local run can't text a stranger even with real credentials loaded.
RESERVED_FOR_FICTION = re.compile(r"^\+1\d{3}55501\d{2}$")


class SmsError(RuntimeError):
    """Telnyx rejected the message."""


def can_send(to: str) -> bool:
    return bool(
        settings.telnyx_api_key
        and settings.telnyx_from_number
        and E164.match(to)
        and not RESERVED_FOR_FICTION.match(to)
    )


async def send_sms(to: str, text: str) -> str | None:
    """Send one SMS. Returns the Telnyx message id, or None if sending is not configured."""
    if not can_send(to):
        return None

    async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
        response = await client.post(
            TELNYX_MESSAGES,
            json={"from": settings.telnyx_from_number, "to": to, "text": text},
            headers={"Authorization": f"Bearer {settings.telnyx_api_key}"},
        )
    if response.is_error:
        raise SmsError(f"telnyx {response.status_code}: {_why(response)}")
    message_id: str = response.json()["data"]["id"]
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
