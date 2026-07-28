"""What the agent can actually do.

Tools are the safety boundary: the model changes the world only by calling one, and
each validates before acting and records what it did on the `CallRecord`. Per-call
dependencies arrive through `ToolRuntime`, so these stay plain module-level functions.

`save_booking` is shared by every profile's own `book` tool — see `profiles/hvac.py`.
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from receptionist.models import Booking, CallRecord, Message, Outcome
from receptionist.services.calendar import CalendarService, NoBooking, SlotUnavailable
from receptionist.services.when import pretty_day


@dataclass
class CallContext:
    """Everything a tool needs about the call it is running inside."""

    calendar: CalendarService
    record: CallRecord


def explain_to_model(exc: Exception) -> str:
    """Turn a tool's rejected input into something the model can recover from.

    A raised exception would abort the turn, which on a phone call is dead air. Only
    ValueError — "I couldn't understand what the caller said" — is recoverable;
    anything else is a real bug and should surface.
    """
    if isinstance(exc, ValueError):
        return f"That didn't work: {exc} Ask the caller to clarify, then try again."
    raise exc


async def save_booking(
    runtime: ToolRuntime[CallContext],
    *,
    service: str,
    day: str,
    time: str,
    details: dict[str, str],
) -> str:
    """Create the appointment and record it. Every profile's `book` tool ends here."""
    call = runtime.context
    if call.record.booking is not None:
        existing = call.record.booking
        # Between turns the model sees only what it said out loud, not its own earlier
        # tool calls, so it can forget it already booked. Confirm rather than double-book.
        return (
            f"This caller is already booked: {existing.service} on "
            f"{existing.starts_at:%A, %B %d} at {existing.starts_at:%I:%M %p}. "
            "Read that back instead of booking again."
        )

    try:
        booked = await call.calendar.create_event(
            call.record.caller_number, service=service, day=day, time=time
        )
    except SlotUnavailable:
        still_open = await call.calendar.available_slots(day)
        spoken_day = pretty_day(day)
        call.record.emit("slot_declined", f"{time} on {spoken_day} was not available")
        # "isn't available" rather than "already taken": the time may simply be outside
        # bookable hours, and claiming someone booked it would be inventing a fact.
        return (
            f"{time} on {spoken_day} isn't available. "
            f"Open on {spoken_day}: {', '.join(still_open) or 'nothing'}."
        )

    call.record.booking = Booking(
        service=booked.service,
        starts_at=booked.starts_at,
        ends_at=booked.ends_at,
        calendar_event_id=booked.event_id,
        details=details,
    )
    call.record.outcome = Outcome.BOOKED
    call.record.emit("booking_created", f"{booked.spoken()} for {_describe(details)}")
    return f"Booked: {booked.spoken()}. Confirmation {booked.event_id}."


@tool(parse_docstring=True)
async def check_availability(day: str, runtime: ToolRuntime[CallContext]) -> str:
    """List the appointment times still open on a given day.

    Args:
        day: The day to check, as an absolute calendar date in YYYY-MM-DD form.
    """
    call = runtime.context
    times = await call.calendar.available_slots(day)
    spoken_day = pretty_day(day)
    call.record.emit("availability_checked", f"{spoken_day}: {', '.join(times) or 'none'}")
    if not times:
        return f"Nothing is open on {spoken_day}."
    return f"Open on {spoken_day}: {', '.join(times)}."


@tool(parse_docstring=True)
async def reschedule(day: str, time: str, runtime: ToolRuntime[CallContext]) -> str:
    """Move the caller's existing appointment to a new day and time.

    Args:
        day: The new day, as an absolute calendar date in YYYY-MM-DD form.
        time: The new time, e.g. "10:00 AM".
    """
    call = runtime.context
    try:
        moved = await call.calendar.reschedule(call.record.caller_number, day=day, time=time)
    except NoBooking:
        return "I don't see an appointment under this number to move."
    except SlotUnavailable:
        still_open = await call.calendar.available_slots(day)
        spoken_day = pretty_day(day)
        return (
            f"{time} on {spoken_day} isn't available. "
            f"Open on {spoken_day}: {', '.join(still_open) or 'nothing'}."
        )

    was = call.record.booking
    call.record.booking = Booking(
        service=moved.service,
        starts_at=moved.starts_at,
        ends_at=moved.ends_at,
        calendar_event_id=moved.event_id,
        details=was.details if was else {},
    )
    call.record.outcome = Outcome.RESCHEDULED
    call.record.emit("booking_rescheduled", moved.spoken())
    return f"Moved to {moved.spoken()}."


@tool
async def cancel(runtime: ToolRuntime[CallContext]) -> str:
    """Cancel the caller's existing appointment."""
    call = runtime.context
    try:
        cancelled = await call.calendar.cancel(call.record.caller_number)
    except NoBooking:
        return "I don't see an appointment under this number to cancel."
    call.record.booking = None
    call.record.outcome = Outcome.CANCELLED
    call.record.emit("booking_cancelled", cancelled)
    return f"Cancelled: {cancelled}."


@tool(parse_docstring=True)
async def take_message(name: str, reason: str, runtime: ToolRuntime[CallContext]) -> str:
    """Take a message when you cannot help, or the caller asks for a person.

    Args:
        name: The caller's name.
        reason: What the message is about, in one line.
    """
    call = runtime.context
    call.record.message = Message(name=name, reason=reason)
    call.record.outcome = Outcome.MESSAGE_TAKEN
    call.record.emit("message_taken", f"{name}: {reason[:60]}")
    return "Got it, I'll pass that along. Anything else?"


SHARED_TOOLS = [check_availability, reschedule, cancel, take_message]


def _describe(details: dict[str, str]) -> str:
    return ", ".join(f"{key}={value}" for key, value in details.items()) or "no details"
