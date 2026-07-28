"""Adapter: expose our vendor-neutral `Receptionist` brain as a LiveKit `Agent`.

The brain owns the behaviour — the system prompt, the six tools, and the decision
timeline. This class is a thin translation layer so the LiveKit voice stack
(STT -> LLM -> TTS) can drive it: each `@function_tool` method mirrors one brain tool,
collects the LLM-supplied arguments, and hands them to `brain.dispatch(...)`, which
validates and acts. Tool and parameter descriptions live in the docstrings — LiveKit
feeds them to the LLM (parsed with `docstring_parser`), so the model relies on them to
call tools correctly.

Confirmed against livekit-agents 1.6.7:
- `Agent.__init__(*, instructions=...)`.
- `@function_tool`-decorated methods on an `Agent` subclass are auto-registered as tools
  (`Agent.__init__` calls `find_function_tools(self)`); no explicit wiring is needed.
- Each parameter's description is read from the Google-style `Args:` docstring section.
"""

# Under our pyproject mypy override the `livekit.*` package is opaque
# (ignore_missing_imports + follow_imports = "skip"), so `Agent` and `function_tool` both
# read as `Any`. That makes subclassing `Agent` a "subclass Any" and every `@function_tool`
# method an "untyped decorator". Suppress just those two codes for this adapter file — it is
# the intentional vendor boundary; the rest of the package stays fully strict-checked.
# mypy: disable-error-code="misc, untyped-decorator"

from __future__ import annotations

from typing import Any

from livekit.agents import Agent, function_tool

from receptionist.profiles.base import Receptionist


class ReceptionistAgent(Agent):
    """A LiveKit `Agent` whose tools delegate to a `Receptionist` brain."""

    def __init__(self, brain: Receptionist) -> None:
        self._brain = brain
        super().__init__(instructions=brain.system_prompt())

    @function_tool
    async def check_availability(self, day: str) -> str:
        """List open appointment times on a given day. Call before offering any time.

        Args:
            day: The day to check, e.g. 'tomorrow' or 'Tuesday'.
        """
        return await self._brain.dispatch("check_availability", {"day": day})

    @function_tool
    async def book(
        self,
        service: str,
        day: str,
        time: str,
        name: str | None = None,
        email: str | None = None,
        address: str | None = None,
        issue: str | None = None,
        party_size: str | None = None,
    ) -> str:
        """Create the booking once you have every required detail and a confirmed time.

        Args:
            service: What the caller needs (the service to book).
            day: The day for the appointment, e.g. 'tomorrow' or 'Tuesday'.
            time: The time for the appointment, e.g. '10:00 AM'.
            name: The caller's name.
            email: The caller's email address (needed to send the calendar invite).
            address: The caller's service address.
            issue: A short description of the caller's issue.
            party_size: The number of people in the party.
        """
        # Pass only non-None values so the brain reads what its profile needs and
        # ignores the rest (the union of all profiles' booking fields is offered here).
        args: dict[str, Any] = {"service": service, "day": day, "time": time}
        for key, value in (
            ("name", name),
            ("email", email),
            ("address", address),
            ("issue", issue),
            ("party_size", party_size),
        ):
            if value is not None:
                args[key] = value
        return await self._brain.dispatch("book", args)

    @function_tool
    async def reschedule(self, day: str, time: str) -> str:
        """Move the caller's existing booking to a new day and time.

        Args:
            day: The new day, e.g. 'tomorrow' or 'Tuesday'.
            time: The new time, e.g. '10:00 AM'.
        """
        return await self._brain.dispatch("reschedule", {"day": day, "time": time})

    @function_tool
    async def cancel(self) -> str:
        """Cancel the caller's existing booking."""
        return await self._brain.dispatch("cancel", {})

    @function_tool
    async def answer_question(self, question: str) -> str:
        """Answer a question about the business (hours, pricing, services, menu, etc.).

        Args:
            question: The caller's question.
        """
        return await self._brain.dispatch("answer_question", {"question": question})

    @function_tool
    async def take_message(self, name: str, reason: str) -> str:
        """Take a message when you can't help or the caller asks for a person.

        Args:
            name: The caller's name.
            reason: What the message is about.
        """
        return await self._brain.dispatch("take_message", {"name": name, "reason": reason})
