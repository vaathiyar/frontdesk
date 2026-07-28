# frontdesk

A proof-of-concept **AI receptionist** — one engine, swappable call profiles (HVAC
and restaurant). A caller books/reschedules/cancels on the call, gets questions
answered, or leaves a message; every call yields one `CallRecord` that the owner
notification and the web view both render.

The same brain answers two ways: a **text** dev REPL for fast iteration and testing,
and a **voice** worker that takes real phone calls over **LiveKit** — self-hosted
(`livekit-server` + `livekit-sip`, not LiveKit Cloud), with Gemini for reasoning and
Google Cloud for speech. Run modes and details: [`backend/README.md`](backend/README.md).

## Repository

```
backend/     Python engine, LiveKit voice worker, and text dev harness — the brain and its tools
frontend/    Web app: live "recent calls" dashboard + signed call-detail view (planned)
docs/        Design (lld.md), the P0 requirements, and the voice + LiveKit SIP delivery plan
```

- **Backend** — runnable and tested today (text + voice). See [`backend/README.md`](backend/README.md).
- **Frontend** — being specced; see the plan under `docs/` once available.
- **Design** — start with [`docs/lld.md`](docs/lld.md); voice/telephony in [`docs/voice_livekit_sip_plan.md`](docs/voice_livekit_sip_plan.md).

## Quickstart (backend)

```bash
cd backend
uv sync
uv run pytest -q                    # 36 tests, offline
export GOOGLE_API_KEY=...           # Gemini; or set it in .env
uv run python scripts/chat.py hvac  # text chat with the agent (no telephony)
```

For the voice path — `agent.py console` (local mic/speakers) or a self-hosted LiveKit
connection — see [`backend/README.md`](backend/README.md).
