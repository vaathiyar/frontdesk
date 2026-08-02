"""The URLs we hand out: the call page, and an add-to-calendar link.

The call link goes to the caller in a text, so it stays short — a bare id, no query
string, comfortably inside one SMS segment. It is unauthenticated: the id is a random
UUID and the link goes to the caller's own phone, which is as far as a demo needs to go.
The link never expires, deliberately, so the caller can come back to it.

This stays under `worker/` because only the worker builds URLs — `messaging/compose.py`
puts `call_url` into the text. The web process resolves ids, and needs nothing from here.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import quote, urlencode
from uuid import UUID

from receptionist.settings import settings


def call_url(call_id: UUID) -> str:
    """Where the caller reads their call back.

    `public_base_url` is the SPA's origin, not this backend's: `/c/{id}` is a client-side
    route, and the page it renders is what calls `GET /api/calls/{id}` in turn.
    """
    return f"{settings.public_base_url.rstrip('/')}/c/{call_id}"


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
