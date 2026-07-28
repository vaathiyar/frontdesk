"""The URLs we hand out: the signed call page, and an add-to-calendar link.

The call page link goes to the caller in a text, so it has to be unguessable without
being long. The token is an HMAC of the call id, truncated: 64 bits of secret on top of
a random UUID is far more than someone will brute-force to read one appointment, and it
keeps the whole link inside a single SMS segment. There's no expiry, deliberately —
a stable link the caller can come back to.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime
from urllib.parse import quote, urlencode
from uuid import UUID

from receptionist.settings import settings

TOKEN_LENGTH = 16


def sign(call_id: UUID, secret: str | None = None) -> str:
    key = (secret or settings.link_secret).encode()
    digest = hmac.new(key, str(call_id).encode(), hashlib.sha256).hexdigest()
    return digest[:TOKEN_LENGTH]


def verify(call_id: UUID, token: str, secret: str | None = None) -> bool:
    """Constant-time, so a wrong token leaks nothing through timing."""
    return hmac.compare_digest(sign(call_id, secret), token)


def call_url(call_id: UUID) -> str:
    return f"{settings.public_base_url.rstrip('/')}/c/{call_id}?t={sign(call_id)}"


def google_calendar_url(
    *,
    title: str,
    starts_at: datetime,
    ends_at: datetime,
    details: str = "",
    location: str = "",
) -> str:
    """An "add to Google Calendar" link for one event.

    Times are sent as local wall-clock plus `ctz`, rather than converted to UTC, so the
    caller sees the hour they were actually told even if their device is elsewhere.
    """
    stamp = "%Y%m%dT%H%M%S"
    params = {
        "action": "TEMPLATE",
        "text": title,
        "dates": f"{starts_at.strftime(stamp)}/{ends_at.strftime(stamp)}",
        "ctz": settings.timezone,
    }
    if details:
        params["details"] = details
    if location:
        params["location"] = location
    return "https://calendar.google.com/calendar/render?" + urlencode(params, quote_via=quote)
