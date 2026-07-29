"""HVAC — the hero profile."""

from __future__ import annotations

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from receptionist.agent.tools import (
    CallContext,
    cancel,
    check_availability,
    end_call,
    reschedule,
    save_booking,
    take_message,
)
from receptionist.profiles.profile import Profile


@tool(parse_docstring=True)
async def book(
    service: str,
    day: str,
    time: str,
    name: str,
    address: str,
    issue: str,
    runtime: ToolRuntime[CallContext],
) -> str:
    """Book a service visit. Call this only once you have every detail below and a time
    you have confirmed is open.

    Args:
        service: What the caller needs, e.g. "furnace repair" or "AC tune-up".
        day: The appointment day, as an absolute calendar date in YYYY-MM-DD form.
        time: The appointment time, e.g. "10:00 AM".
        name: The caller's name.
        address: The service address including the city, written as a person would, e.g.
            "12 Oak St, Burnaby".
        issue: One line describing what is wrong.
    """
    return await save_booking(
        runtime,
        service=service,
        day=day,
        time=time,
        details={"name": name, "address": address, "issue": issue},
    )


HVAC = Profile(
    id="hvac",
    business="Helpdesk Heating and Cooling",
    greeting="Thanks for calling Helpdesk Heating and Cooling. How can I help?",
    does=(
        "You book service visits: furnace and AC repair, maintenance, and seasonal "
        "tune-ups, for all makes and models. The service area is Burnaby, New "
        "Westminster and Coquitlam. If a caller is outside it, take a message instead "
        "of booking."
    ),
    knowledge=(
        "Hours are Monday to Saturday, 8am to 6pm. The service area is Burnaby, New "
        "Westminster and Coquitlam. We repair and maintain furnaces and AC units of all "
        "makes and models, and do seasonal tune-ups. Estimates on new installations are "
        "free. Annual maintenance plans are available."
    ),
    tools=(check_availability, book, reschedule, cancel, take_message, end_call),
)
