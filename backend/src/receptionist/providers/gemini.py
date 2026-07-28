"""Gemini chat provider, exposed through the runner's Anthropic-shaped `MessagesAPI`.

`ConversationRunner` speaks one small dialect — `create(model, max_tokens, system,
tools, messages, output_config)` returning content blocks with `.type`/`.text`/
`.name`/`.input`/`.id`. That dialect is Anthropic-shaped (it's what the offline test
fake mimics). `GeminiMessages` implements the same surface on top of `google-genai`,
translating the request into `generate_content` and the response back into blocks — so
the runner, the tool-use loop, and the tests are all provider-agnostic and unchanged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types

from receptionist.core.settings import Settings, settings

# Anthropic JSON-schema primitive -> Gemini Schema type.
_JSON_TO_GEMINI: dict[str, types.Type] = {
    "object": types.Type.OBJECT,
    "array": types.Type.ARRAY,
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
}

# `output_config["effort"]` -> Gemini 3.x thinking_level (the current control; the old
# thinking_budget is legacy). Flash-Lite defaults to "minimal", which Google warns ends
# multi-step tool loops prematurely — so we always send a level and default to MEDIUM,
# Google's recommendation for agentic tool use.
_EFFORT_TO_LEVEL: dict[str, types.ThinkingLevel] = {
    "minimal": types.ThinkingLevel.MINIMAL,
    "low": types.ThinkingLevel.LOW,
    "medium": types.ThinkingLevel.MEDIUM,
    "high": types.ThinkingLevel.HIGH,
}


# `signature` carries Gemini 3's per-part thought_signature (an opaque bytes token)
# through the runner's history untouched. Gemini rejects a follow-up request whose
# echoed function_call parts are missing the signature it issued, so we must round-trip
# it exactly as received (see _from_response / _to_contents).
@dataclass
class _TextBlock:
    text: str
    type: str = "text"
    signature: bytes | None = None


@dataclass
class _ToolUseBlock:
    name: str
    input: dict[str, Any]
    id: str
    type: str = "tool_use"
    signature: bytes | None = None


@dataclass
class _Response:
    content: list[Any] = field(default_factory=list)
    stop_reason: str = "end_turn"


def _to_schema(node: dict[str, Any]) -> types.Schema:
    """Convert one Anthropic JSON-schema node into a Gemini `types.Schema`."""
    json_type = node.get("type", "string")
    kwargs: dict[str, Any] = {"type": _JSON_TO_GEMINI.get(json_type, types.Type.STRING)}
    if "description" in node:
        kwargs["description"] = node["description"]
    if "enum" in node:
        kwargs["enum"] = list(node["enum"])
    if json_type == "object":
        props = node.get("properties") or {}
        if props:
            kwargs["properties"] = {k: _to_schema(v) for k, v in props.items()}
        if node.get("required"):
            kwargs["required"] = list(node["required"])
    if json_type == "array" and "items" in node:
        kwargs["items"] = _to_schema(node["items"])
    return types.Schema(**kwargs)


def _to_declarations(tools: list[dict[str, Any]]) -> list[types.FunctionDeclaration]:
    decls: list[types.FunctionDeclaration] = []
    for t in tools:
        schema = t.get("input_schema") or {}
        # A no-argument tool (empty properties) gets `parameters=None`; Gemini rejects
        # an OBJECT schema with no properties.
        parameters = _to_schema(schema) if schema.get("properties") else None
        decls.append(
            types.FunctionDeclaration(
                name=t["name"], description=t.get("description", ""), parameters=parameters
            )
        )
    return decls


def _btype(block: Any) -> str | None:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _bget(block: Any, key: str) -> Any:
    return block.get(key) if isinstance(block, dict) else getattr(block, key, None)


def _to_contents(messages: list[dict[str, Any]]) -> list[types.Content]:
    """Translate the runner's Anthropic-shaped history into Gemini `contents`.

    Tool-use ids are mapped back to tool names within this single pass (a tool_use
    block always precedes its tool_result), so a tool_result turn can name the
    function it answers — Gemini matches responses to calls by name.
    """
    contents: list[types.Content] = []
    id_to_name: dict[str, str] = {}

    for msg in messages:
        content = msg["content"]
        if msg["role"] == "assistant":
            parts: list[types.Part] = []
            for block in content:
                if _btype(block) == "text":
                    if text := _bget(block, "text"):
                        parts.append(
                            types.Part(text=text, thought_signature=_bget(block, "signature"))
                        )
                elif _btype(block) == "tool_use":
                    name, bid = _bget(block, "name"), _bget(block, "id")
                    id_to_name[bid] = name
                    parts.append(
                        types.Part(
                            function_call=types.FunctionCall(
                                id=bid, name=name, args=dict(_bget(block, "input") or {})
                            ),
                            thought_signature=_bget(block, "signature"),
                        )
                    )
            contents.append(types.Content(role="model", parts=parts or [types.Part(text=" ")]))
        elif isinstance(content, str):
            contents.append(types.Content(role="user", parts=[types.Part(text=content)]))
        else:  # user turn carrying tool_result blocks
            parts = []
            for item in content:
                if item.get("type") == "tool_result":
                    tid = item.get("tool_use_id", "")
                    name = id_to_name.get(tid) or tid.split("::")[0]
                    parts.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                id=tid or None,
                                name=name,
                                response={"result": item.get("content", "")},
                            )
                        )
                    )
                elif item.get("type") == "text":
                    parts.append(types.Part(text=item.get("text", "")))
            contents.append(types.Content(role="user", parts=parts))
    return contents


def _thinking_config(output_config: dict[str, Any] | None) -> types.ThinkingConfig:
    effort = (output_config or {}).get("effort", "")
    return types.ThinkingConfig(
        thinking_level=_EFFORT_TO_LEVEL.get(effort, types.ThinkingLevel.MEDIUM)
    )


def _from_response(resp: types.GenerateContentResponse) -> _Response:
    """Turn a Gemini response into the runner's content-block shape."""
    blocks: list[Any] = []
    candidates = resp.candidates or []
    parts = (candidates[0].content.parts or []) if candidates and candidates[0].content else []
    for n, part in enumerate(parts, start=1):
        if getattr(part, "thought", False):
            continue  # never surface the model's private reasoning as the spoken reply
        sig = part.thought_signature  # opaque token we must echo back verbatim next turn
        if part.function_call is not None:
            fc = part.function_call
            blocks.append(
                _ToolUseBlock(
                    name=fc.name or "",
                    input=dict(fc.args) if fc.args else {},
                    id=fc.id or f"{fc.name}::{n}",
                    signature=sig,
                )
            )
        elif part.text:
            blocks.append(_TextBlock(text=part.text, signature=sig))
    stop = "tool_use" if any(b.type == "tool_use" for b in blocks) else "end_turn"
    return _Response(content=blocks, stop_reason=stop)


class GeminiMessages:
    """Adapter satisfying the runner's `MessagesAPI` protocol over `google-genai`."""

    def __init__(self, client: genai.Client) -> None:
        self._client = client

    @classmethod
    def from_settings(cls, config: Settings = settings) -> GeminiMessages:
        # A falsy key becomes None so the SDK can fall back to its own env resolution.
        return cls(genai.Client(api_key=config.google_api_key or None))

    async def create(self, **kwargs: Any) -> _Response:
        tools = kwargs.get("tools") or []
        config = types.GenerateContentConfig(
            system_instruction=kwargs.get("system"),
            max_output_tokens=kwargs.get("max_tokens"),
            tools=[types.Tool(function_declarations=_to_declarations(tools))] if tools else None,
            # We drive the tool-use loop ourselves; don't let the SDK auto-execute.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            thinking_config=_thinking_config(kwargs.get("output_config")),
        )
        resp = await self._client.aio.models.generate_content(
            model=kwargs["model"],
            contents=_to_contents(kwargs["messages"]),
            config=config,
        )
        return _from_response(resp)
