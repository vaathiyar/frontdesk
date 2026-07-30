# frontdesk

A proof-of-concept **AI receptionist** for small businesses. A caller phones in; the agent
books, reschedules or cancels on the call, answers questions about the business, or takes a
message — then texts the caller a confirmation with a link to the transcript and an
add-to-calendar button.

**One brain, two drivers.** A LangGraph agent owns the prompt and the tools; a text REPL
and a LiveKit voice worker both drive that same graph, so what you iterate on by typing is
what answers the phone. Gemini reasons, Google Cloud does speech, LiveKit carries the call
(self-hosted `livekit-server` + `livekit-sip`, not LiveKit Cloud), and Telnyx sends the text.

Two profiles ship — HVAC and restaurant — and adding a vertical is one module plus one
registry line.

## Repository

```
backend/     the agent, the voice worker, the call API, and the dev REPL
frontend/    a React SPA on CloudFront (specced, not built)
docs/        lld.md (the design as built), the P0 requirements, config reference
```

- **Backend** — runnable and tested. Start at [`backend/README.md`](backend/README.md).
- **Design** — [`docs/lld.md`](docs/lld.md) describes what exists, including the parts
  that were hard to get right.
- **Config** — every environment variable and where to obtain it:
  [`docs/config.md`](docs/config.md).
- **Frontend** — a separate React SPA, deployed to CloudFront and reaching the backend over
  JSON on its own origin. Not built yet; `docs/frontend_spec.md` has the shape. The backend
  serves data, never markup.

## Quickstart

```bash
cd backend
uv sync
uv run pytest -q                                     # 122 tests, offline, no API key

export GOOGLE_API_KEY=...                            # Gemini; or set it in .env
uv run python scripts/chat.py hvac --fake-calendar   # talk to it, no telephony
```

Ask for tomorrow's first opening to watch it decline a taken slot and offer real
alternatives. `quit` prints the resulting call record and the text it would send.

To hear it: `uv run agent.py console` (local mic and speakers, no server needed — wear
headphones, there's no echo cancellation). For real phone calls and Docker, see
[`backend/README.md`](backend/README.md) and
[`backend/deploy/README.md`](backend/deploy/README.md).
