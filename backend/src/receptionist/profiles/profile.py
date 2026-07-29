"""What makes one business different from another.

A profile is data: what the business is called, what it does, what it may state, when it
takes appointments, and which tools its agent may call. Each profile lists its own tools
outright — the shared ones it wants plus whatever it defines itself — so one file tells
you everything that business's agent can do, and a profile that should not, say, cancel
bookings can simply leave that tool out.

How booking actually works is deliberately not here. That lives behind
`CalendarService`, chosen per profile by `build_calendar`, so this stays a description of
a business rather than an implementation of slot arithmetic.

Adding a vertical: write one module like `hvac.py`, add one line to `__init__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class Profile:
    id: str
    business: str
    greeting: str  # spoken on pickup, no model round-trip, names the business
    does: str  # what this business does — goes into the system prompt
    knowledge: str  # facts the agent may state: hours, pricing, menu
    # Everything this profile's agent can do. A tuple, not a list: frozen dataclasses
    # generate __hash__ from their fields, and a list would make Profile unhashable.
    tools: tuple[BaseTool, ...]
    # When this business takes appointments, as 24-hour clock hours. The last appointment
    # must END by `closes`, so 8..18 means a final start at 5pm. These have to match the
    # hours stated in `knowledge`, or the agent offers times the calendar then refuses.
    opens: int = 8
    closes: int = 18
