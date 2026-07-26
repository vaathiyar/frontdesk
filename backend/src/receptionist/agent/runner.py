"""Drives the tool-use loop over a Receptionist.

This is the documented Anthropic manual loop (call → if stop_reason == tool_use,
run tools, append tool_result, repeat → else return text). The voice agent will use
the same loop later with audio in/out; here it runs over typed text so the whole
brain is exercisable without LiveKit, STT, or TTS.

`messages_api` is `AsyncAnthropic().messages` in production and a scripted fake in
tests — the one seam that needs the network.
"""

from __future__ import annotations

from typing import Any, Protocol

from receptionist.core.models import TranscriptTurn
from receptionist.core.settings import settings
from receptionist.profiles.base import Receptionist

_MAX_TOOL_ROUNDS = 8  # guard against a tool-call loop that never resolves


class MessagesAPI(Protocol):
    async def create(self, **kwargs: Any) -> Any: ...


class ConversationRunner:
    def __init__(
        self,
        receptionist: Receptionist,
        messages_api: MessagesAPI,
        *,
        model: str | None = None,
        max_tokens: int | None = None,
        effort: str | None = None,
    ) -> None:
        self._agent = receptionist
        self._messages_api = messages_api
        self._model = model or settings.llm_model
        self._max_tokens = max_tokens or settings.llm_max_tokens
        self._effort = effort or settings.llm_effort
        self._history: list[dict[str, Any]] = []

    async def send(self, caller_text: str) -> str:
        """Feed one caller utterance; run the agent's turn to completion (tools and
        all) and return its spoken reply."""
        self._agent.record.transcript.append(TranscriptTurn(role="caller", text=caller_text))
        self._history.append({"role": "user", "content": caller_text})

        for _ in range(_MAX_TOOL_ROUNDS):
            resp = await self._messages_api.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=self._agent.system_prompt(),
                tools=self._agent.tool_schemas(),
                messages=self._history,
                output_config={"effort": self._effort},
            )
            self._history.append({"role": "assistant", "content": resp.content})

            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            if not tool_uses:
                reply = "".join(
                    getattr(b, "text", "")
                    for b in resp.content
                    if getattr(b, "type", None) == "text"
                ).strip()
                self._agent.record.transcript.append(TranscriptTurn(role="agent", text=reply))
                return reply

            results = []
            for tu in tool_uses:
                output = await self._agent.dispatch(tu.name, dict(tu.input))
                results.append({"type": "tool_result", "tool_use_id": tu.id, "content": output})
            self._history.append({"role": "user", "content": results})

        fallback = "Sorry — I'm having trouble with that. Let me take a message instead."
        self._agent.record.transcript.append(TranscriptTurn(role="agent", text=fallback))
        return fallback
