"""Restaurant — reservations. Owns its own data file, the menu."""

from __future__ import annotations

import json
from pathlib import Path

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from receptionist.agent.tools import CallContext, save_booking
from receptionist.profiles.profile import Profile

_MENU_PATH = Path(__file__).parent / "restaurant_menu.json"


def _menu() -> str:
    items = json.loads(_MENU_PATH.read_text())["items"]
    return "; ".join(f"{item['name']} (${item['price']})" for item in items)


@tool(parse_docstring=True)
async def book(
    service: str,
    day: str,
    time: str,
    name: str,
    party_size: str,
    runtime: ToolRuntime[CallContext],
) -> str:
    """Book a table. Call this only once you have every detail below and a time you have
    confirmed is open.

    Args:
        service: The reservation, e.g. "table for 4".
        day: The reservation day, as an absolute calendar date in YYYY-MM-DD form.
        time: The reservation time, e.g. "7:00 PM".
        name: The name to hold the table under.
        party_size: How many people are coming.
    """
    return await save_booking(
        runtime,
        service=service,
        day=day,
        time=time,
        details={"name": name, "party_size": party_size},
    )


RESTAURANT = Profile(
    id="restaurant",
    business="Helpdesk Kitchen",
    greeting="Thanks for calling Helpdesk Kitchen!",
    does=(
        "You take table reservations. Treat the reservation as the table itself, e.g. "
        "'table for 4'. For parties larger than 8, take a message for the manager "
        "instead of booking."
    ),
    knowledge=f"Hours are Tuesday to Sunday, 5pm to 10pm. On the menu: {_menu()}.",
    book=book,
    # Dinner service only, matching the hours above. Without this the calendar would
    # offer a trades-hours grid and refuse every evening table a caller asked for.
    opens=17,
    closes=22,
)
