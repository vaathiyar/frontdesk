"""The engine, built once. `Receptionist` owns the shared behaviour — the prompt
scaffold and the six tools every profile uses — via Template Method + Strategy:
subclasses fill three hooks (`domain_prompt`, `booking_fields`, `knowledge`) and
set three class attributes. Adding a vertical touches nothing here.

Tools are the safety boundary: the model changes the world only by calling them,
and each one validates before acting and records a decision-timeline event.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from datetime import date, datetime
from typing import Any, ClassVar
from zoneinfo import ZoneInfo

from receptionist.core.models import Booking, CallRecord, CapturedField, Outcome
from receptionist.core.settings import settings
from receptionist.profiles.fields import Field
from receptionist.services.calendar import CalendarService, NoBooking, SlotUnavailable

BASE_PROMPT = """You are the receptionist for {business}. Be warm, concise, and sound \
natural on a phone call. Never invent facts. {domain}

To book, find out what service they need and their preferred day and time, then \
collect: {fields}. Ask only for what you still need, group related questions into one \
turn, and keep it to a couple of quick questions — never interrogate the caller. You \
already know the caller's phone number from the call, so never ask for it. Always take \
an email (it's needed to send the calendar invite) and read it back, spelled out, to \
confirm.

Today is {today}. Whenever a tool takes a `day`, work out the actual calendar date \
yourself and pass it as YYYY-MM-DD — never a phrase like "tomorrow" or "the day after \
next". Speak dates back to the caller in words ("Wednesday the 29th"), never as digits.

Call check_availability before offering a time, and only offer times it returns. Never \
claim something is booked, moved, or cancelled unless the tool confirmed it — read the \
tool's confirmation back. You can reschedule or cancel the caller's existing booking. \
Use answer_question for questions about the business. If you can't help, or the caller \
asks for a person, use take_message. Keep every reply short and spoken-friendly."""


def _fmt_clock(when: datetime) -> str:
    """`"2:05 PM"` — no leading zero, matching how the calendars format their slots."""
    suffix = "AM" if when.hour < 12 else "PM"
    return f"{when.hour % 12 or 12}:{when.minute:02d} {suffix}"


def _describe_now(now: datetime | None = None) -> str:
    """The prompt's date anchor. Without it the model has no idea what "today" is, so it
    can't turn "the day after tomorrow" into a date — the whole reason we ask for ISO."""
    tz = ZoneInfo(settings.timezone)
    current = now or datetime.now(tz)
    return (
        f"{current:%A}, {current:%B} {current.day}, {current.year} "
        f"at {_fmt_clock(current)} ({settings.timezone})"
    )


def _pretty_day(day: str) -> str:
    """`"2026-07-29"` -> `"Wednesday, July 29"`, so nothing reads a date out as digits.

    Anything that isn't an ISO date passes straight through — the fake calendar (and its
    tests) still speak in "tomorrow" / "Tuesday".
    """
    try:
        parsed = date.fromisoformat(day.strip())
    except ValueError:
        return day
    return f"{parsed:%A}, {parsed:%B} {parsed.day}"


def _pretty_slot(day: str, time: str) -> str:
    """Human-readable slot for `Booking.slot` and for what the agent reads back."""
    pretty = _pretty_day(day)
    return f"{pretty} at {time}" if pretty != day else f"{day} {time}"


class Receptionist(ABC):
    profile_id: ClassVar[str]
    business_name: ClassVar[str]
    greeting: ClassVar[str]

    def __init__(self, calendar: CalendarService, record: CallRecord) -> None:
        self.calendar = calendar
        self.record = record

    # --- Strategy hooks: subclasses override these ---
    @abstractmethod
    def domain_prompt(self) -> str: ...

    @abstractmethod
    def booking_fields(self) -> list[Field]: ...

    def knowledge(self) -> str:
        return ""

    # --- Template Method: assemble the prompt from the hooks ---
    def system_prompt(self) -> str:
        fields = ", ".join(f.label for f in self.booking_fields())
        return BASE_PROMPT.format(
            business=self.business_name,
            domain=self.domain_prompt(),
            fields=fields,
            # Resolved per call (and per turn) so a long-running worker never goes stale.
            today=_describe_now(),
        )

    # --- Tool schemas the LLM sees (Anthropic tool definitions) ---
    def tool_schemas(self) -> list[dict[str, Any]]:
        def obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "object", "properties": props, "required": required}

        # Absolute dates only: the model does the "day after tomorrow" arithmetic (it has
        # today's date from the prompt), so no phrase-parsing is needed on our side.
        day = {
            "type": "string",
            "description": "absolute calendar date as YYYY-MM-DD — work it out from what "
            "the caller says, e.g. 'the day after tomorrow' or 'next Tuesday'",
        }
        time = {"type": "string", "description": "time, e.g. '10:00 AM'"}

        booking_props: dict[str, Any] = {
            "service": {"type": "string", "description": "what the caller needs"},
            "day": day,
            "time": time,
        }
        for f in self.booking_fields():
            booking_props[f.key] = {"type": "string", "description": f"the caller's {f.label}"}
        book_required = ["service", "day", "time", *[f.key for f in self.booking_fields()]]

        return [
            {
                "name": "check_availability",
                "description": "List open appointment times on a given day. "
                "Call before offering any time.",
                "input_schema": obj({"day": day}, ["day"]),
            },
            {
                "name": "book",
                "description": "Create the booking once you have every required detail "
                "and confirmed an available time.",
                "input_schema": obj(booking_props, book_required),
            },
            {
                "name": "reschedule",
                "description": "Move the caller's existing booking to a new day/time.",
                "input_schema": obj({"day": day, "time": time}, ["day", "time"]),
            },
            {
                "name": "cancel",
                "description": "Cancel the caller's existing booking.",
                "input_schema": obj({}, []),
            },
            {
                "name": "answer_question",
                "description": "Answer a question about the business (hours, pricing, "
                "services, menu, etc.).",
                "input_schema": obj(
                    {"question": {"type": "string", "description": "the caller's question"}},
                    ["question"],
                ),
            },
            {
                "name": "take_message",
                "description": "Take a message when you can't help or the caller wants a person.",
                "input_schema": obj(
                    {
                        "name": {"type": "string", "description": "caller's name"},
                        "reason": {"type": "string", "description": "what the message is about"},
                    },
                    ["name", "reason"],
                ),
            },
        ]

    # --- Dispatch: route a tool call to its handler ---
    async def dispatch(self, name: str, args: dict[str, Any]) -> str:
        handlers: dict[str, Callable[[dict[str, Any]], Awaitable[str]]] = {
            "check_availability": self._tool_check_availability,
            "book": self._tool_book,
            "reschedule": self._tool_reschedule,
            "cancel": self._tool_cancel,
            "answer_question": self._tool_answer_question,
            "take_message": self._tool_take_message,
        }
        handler = handlers.get(name)
        if handler is None:
            return f"Unknown tool: {name}"
        try:
            return await handler(args)
        except ValueError as exc:
            # A tool rejected its input (e.g. a day/time it couldn't parse). Hand the reason
            # back as a tool *result* so the model can ask the caller to clarify and retry.
            # Letting it escape would abort the turn — on a real call, that's dead air.
            self.record.emit("tool_input_rejected", f"{name}: {exc}")
            return f"That didn't work: {exc} Ask the caller to clarify, then try again."

    # --- Tools (the safety boundary) ---
    async def _tool_check_availability(self, args: dict[str, Any]) -> str:
        day = str(args.get("day", ""))
        slots = await self.calendar.available_slots(day)
        spoken = _pretty_day(day)
        self.record.emit("availability_checked", f"{spoken}: {', '.join(slots) or 'none'}")
        if not slots:
            return f"No times are open on {spoken}."
        return f"Open times on {spoken}: {', '.join(slots)}."

    async def _tool_book(self, args: dict[str, Any]) -> str:
        service = str(args.get("service", ""))
        day, time = str(args.get("day", "")), str(args.get("time", ""))
        fields = [
            CapturedField(
                key=f.key, label=f.label, value=str(args.get(f.key, "")), confirmed=f.confirm
            )
            for f in self.booking_fields()
        ]
        try:
            event_id = await self.calendar.create_event(
                self.record.caller_number,
                service=service,
                day=day,
                time=time,
                # Passed through so GoogleCalendarService can email the caller the invite;
                # the fake ignores it. Empty/missing email -> None (no attendee).
                attendee_email=str(args.get("email", "")) or None,
            )
        except SlotUnavailable:
            open_ = await self.calendar.available_slots(day)
            spoken = _pretty_day(day)
            self.record.emit("slot_declined", f"{time} on {spoken} was not available")
            # "not available" rather than "already taken": the time may simply be outside
            # the bookable grid, and claiming someone booked it would be a made-up fact.
            return (
                f"{time} on {spoken} isn't available. "
                f"Open times on {spoken}: {', '.join(open_) or 'none'}."
            )
        slot = _pretty_slot(day, time)
        self.record.booking = Booking(
            service=service, slot=slot, calendar_event_id=event_id, fields=fields
        )
        self.record.fields = fields
        self.record.outcome = Outcome.BOOKED
        self.record.emit("booking_created", f"{service} — {slot}")
        return f"Booked: {service} on {slot}. Confirmation {event_id}."

    async def _tool_reschedule(self, args: dict[str, Any]) -> str:
        day, time = str(args.get("day", "")), str(args.get("time", ""))
        try:
            desc = await self.calendar.reschedule(self.record.caller_number, day=day, time=time)
        except NoBooking:
            return "I don't see a booking under this number to move."
        except SlotUnavailable:
            open_ = await self.calendar.available_slots(day)
            spoken = _pretty_day(day)
            return f"{time} on {spoken} is taken. Open times: {', '.join(open_) or 'none'}."
        if self.record.booking is not None:
            self.record.booking.slot = _pretty_slot(day, time)
        self.record.outcome = Outcome.RESCHEDULED
        self.record.emit("booking_rescheduled", desc)
        return f"Moved to {desc}."

    async def _tool_cancel(self, args: dict[str, Any]) -> str:
        try:
            desc = await self.calendar.cancel(self.record.caller_number)
        except NoBooking:
            return "I don't see a booking under this number to cancel."
        self.record.outcome = Outcome.CANCELLED
        self.record.emit("booking_cancelled", desc)
        return f"Cancelled: {desc}."

    async def _tool_answer_question(self, args: dict[str, Any]) -> str:
        question = str(args.get("question", ""))
        self.record.emit("question_answered", question[:80])
        if self.record.outcome is None:
            self.record.outcome = Outcome.ANSWERED
        return self.knowledge() or "No additional information is available."

    async def _tool_take_message(self, args: dict[str, Any]) -> str:
        name, reason = str(args.get("name", "")), str(args.get("reason", ""))
        self.record.fields.append(
            CapturedField(key="name", label="name", value=name, confirmed=True)
        )
        self.record.fields.append(CapturedField(key="reason", label="reason", value=reason))
        self.record.outcome = Outcome.MESSAGE_TAKEN
        self.record.emit("message_taken", f"{name}: {reason[:60]}")
        return "Got it — I'll pass that along. Anything else?"
