"""A booking field is just a label plus whether the agent should read it back.

No validator framework — for a PoC the LLM collects fields per the prompt, and the
`book` tool records them. `confirm=True` is a prompt hint (spell it back), not code.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Field:
    key: str
    label: str
    confirm: bool = False


NAME = Field("name", "name")
# Required everywhere: the caller's email is what the Google Calendar invite is sent to.
EMAIL = Field("email", "email", confirm=True)

# Phone is never a collected field — it comes from the call itself (SIP caller ID)
# and lives on record.caller_number.
