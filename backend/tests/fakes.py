"""A scripted stand-in for the chat provider (the runner's `MessagesAPI`).

`FakeMessages` returns the next scripted response from an async `create(**kwargs)`;
`text(...)` and `tool(...)` build those responses. The block objects duck-type the
runner's expected shape (`.type`, `.text`, `.name`, `.input`, `.id`) — enough for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TextBlock:
    text: str
    type: str = "text"


@dataclass
class ToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str = "tool_1"
    type: str = "tool_use"


@dataclass
class FakeResponse:
    content: list[Any]
    stop_reason: str


def text(s: str, /) -> FakeResponse:
    return FakeResponse([TextBlock(s)], "end_turn")


def tool(name: str, /, *, tool_id: str = "tool_1", **inp: Any) -> FakeResponse:
    # `name` is positional-only so a tool argument literally called "name"
    # (e.g. the caller's name on a booking) lands in **inp, not here.
    return FakeResponse([ToolUseBlock(name=name, input=inp, id=tool_id)], "tool_use")


@dataclass
class FakeMessages:
    script: list[FakeResponse]
    calls: list[dict[str, Any]] = field(default_factory=list)
    _i: int = 0

    async def create(self, **kwargs: Any) -> FakeResponse:
        self.calls.append(kwargs)
        response = self.script[self._i]
        self._i += 1
        return response
