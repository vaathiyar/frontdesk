# frontdesk

A proof-of-concept **AI receptionist** for small businesses. A caller phones in; the agent
books, reschedules or cancels on the call, answers questions about the business, or takes a
message — then texts the caller a confirmation with a link to the transcript and an
add-to-calendar button.

**One brain.** A LangGraph agent owns the prompt and the tools; the LiveKit voice worker
drives it on a real call and the test suite drives the same compiled graph by text, so
what the tests prove is what answers the phone. Gemini reasons, Google Cloud does speech,
LiveKit carries the call (self-hosted `livekit-server` + `livekit-sip`, not LiveKit
Cloud), Telnyx sends the text, and CockroachDB holds the record it points at.

Two profiles ship — HVAC and restaurant — and adding a vertical is one module plus one
registry line.

## Repository

```
backend/     the agent, the voice worker, and the JSON API
frontend/    a React SPA: the landing page, and the call record a texted link opens
docs/        lld.md (the design as built), the P0 requirements, config reference
```

- **Backend** — runnable and tested. Start at [`backend/README.md`](backend/README.md).
- **Design** — [`docs/lld.md`](docs/lld.md) describes what exists, including the parts
  that were hard to get right.
- **Config** — every environment variable and where to obtain it:
  [`docs/config.md`](docs/config.md).
- **Frontend** — a separate React SPA on its own origin, reaching the backend over JSON.
  The backend serves data, never markup. Start at [`frontend/README.md`](frontend/README.md).

## Quickstart

```bash
cd backend
uv sync
uv run pytest -q     # 171 tests, offline: no network, no API key, no database
```

The suite is how you exercise the agent without telephony: it drives the real graph and
the real tools against an in-memory calendar, so a booking that "happened" actually took a
slot. Start with `tests/test_call_flow.py` — those state the guarantees.

Every real call arrives over SIP, and the worker needs a Google Calendar configured for
each profile before it will start. For phone calls and Docker, see
[`backend/README.md`](backend/README.md) and
[`backend/deploy/README.md`](backend/deploy/README.md).
