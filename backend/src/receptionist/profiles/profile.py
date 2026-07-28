"""What makes one business different from another.

A profile is data, not a class hierarchy — except for `book`, which each profile owns
because the details worth collecting genuinely differ (an HVAC visit needs a service
address; a table needs a party size). Everything else is shared.

Adding a vertical: write one module like `hvac.py`, add one line to `__init__.py`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from langchain_core.tools import BaseTool


@dataclass(frozen=True)
class Profile:
    id: str
    business: str
    greeting: str  # spoken on pickup, no model round-trip, names the business
    does: str  # what this business does — goes into the system prompt
    knowledge: str  # facts the agent may state: hours, pricing, menu
    book: BaseTool  # this profile's booking tool; its parameters are its fields
    extra_tools: tuple[BaseTool, ...] = field(default=())
    # When this business takes appointments, as 24-hour clock hours. The last appointment
    # must END by `closes`, so 8..18 means a final start at 5pm. These have to match the
    # hours stated in `knowledge`, or the agent offers times the calendar then refuses.
    opens: int = 8
    closes: int = 18
