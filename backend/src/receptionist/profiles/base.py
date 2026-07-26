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
from typing import Any, ClassVar

from receptionist.core.models import Booking, CallRecord, CapturedField, Outcome
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

Call check_availability before offering a time, and only offer times it returns. Never \
claim something is booked, moved, or cancelled unless the tool confirmed it — read the \
tool's confirmation back. You can reschedule or cancel the caller's existing booking. \
Use answer_question for questions about the business. If you can't help, or the caller \
asks for a person, use take_message. Keep every reply short and spoken-friendly."""


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
            business=self.business_name, domain=self.domain_prompt(), fields=fields
        )

    # --- Tool schemas the LLM sees (Anthropic tool definitions) ---
    def tool_schemas(self) -> list[dict[str, Any]]:
        def obj(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
            return {"type": "object", "properties": props, "required": required}

        day = {"type": "string", "description": "day, e.g. 'tomorrow' or 'Tuesday'"}
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
        return await handler(args)

    # --- Tools (the safety boundary) ---
    async def _tool_check_availability(self, args: dict[str, Any]) -> str:
        day = str(args.get("day", ""))
        slots = await self.calendar.available_slots(day)
        self.record.emit("availability_checked", f"{day}: {', '.join(slots) or 'none'}")
        if not slots:
            return f"No times are open on {day}."
        return f"Open times on {day}: {', '.join(slots)}."

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
                self.record.caller_number, service=service, day=day, time=time
            )
        except SlotUnavailable:
            open_ = await self.calendar.available_slots(day)
            self.record.emit("slot_declined", f"{time} on {day} was taken")
            return (
                f"{time} on {day} is already taken. "
                f"Open times on {day}: {', '.join(open_) or 'none'}."
            )
        slot = f"{day} {time}"
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
            return f"{time} on {day} is taken. Open times: {', '.join(open_) or 'none'}."
        if self.record.booking is not None:
            self.record.booking.slot = f"{day} {time}"
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
