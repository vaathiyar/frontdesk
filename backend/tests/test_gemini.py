"""Translation-layer tests for the Gemini adapter (no network).

These exercise `_from_response`/`_to_contents` directly — the seam the fake-LLM
runner tests bypass. The signature round-trip is the regression guard for the
Gemini 3 rule that a follow-up request must echo back the thought_signature it
issued on every function_call part, or the API rejects the turn with a 400.
"""

from __future__ import annotations

from google.genai import types

from receptionist.providers.gemini import _from_response, _to_contents


def _response(parts: list[types.Part]) -> types.GenerateContentResponse:
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=parts))]
    )


def test_thought_signatures_survive_the_history_round_trip() -> None:
    resp = _response(
        [
            types.Part(text="Let me check that.", thought_signature=b"sig-text"),
            types.Part(
                function_call=types.FunctionCall(
                    name="check_availability", args={"day": "Tuesday"}
                ),
                thought_signature=b"sig-call",
            ),
        ]
    )

    blocks = _from_response(resp).content
    assert [b.type for b in blocks] == ["text", "tool_use"]
    assert blocks[0].signature == b"sig-text"
    assert blocks[1].signature == b"sig-call"

    # Echoing that assistant turn back must re-attach each signature to its own part.
    parts = _to_contents([{"role": "assistant", "content": blocks}])[0].parts
    assert parts is not None
    assert parts[0].thought_signature == b"sig-text"
    assert parts[1].thought_signature == b"sig-call"
    call = parts[1].function_call
    assert call is not None and call.name == "check_availability"


def test_missing_signature_stays_none() -> None:
    # No thinking → no signature; we must not invent one (None round-trips cleanly).
    blocks = _from_response(_response([types.Part(text="Hi!")])).content
    assert blocks[0].signature is None
    parts = _to_contents([{"role": "assistant", "content": blocks}])[0].parts
    assert parts is not None and parts[0].thought_signature is None
