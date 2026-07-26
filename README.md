# frontdesk

A proof-of-concept **AI receptionist** — one engine, swappable call profiles (HVAC,
restaurant, auto). A caller books/reschedules/cancels on the call, gets questions
answered, or leaves a message; every call yields one `CallRecord` that the owner
notification and the web view both render.

## Repository

```
backend/     Python engine + dev chat harness — the receptionist brain and its tools
frontend/    Web app: live "recent calls" dashboard + signed call-detail view (planned)
docs/        Design: low-level design (lld.md) and the P0 requirements
```

- **Backend** — runnable and tested today. See [`backend/README.md`](backend/README.md).
- **Frontend** — being specced; see the plan under `docs/` once available.
- **Design** — start with [`docs/lld.md`](docs/lld.md).

## Quickstart (backend)

```bash
cd backend
uv sync --extra dev
uv run pytest                       # 34 tests, offline
export ANTHROPIC_API_KEY=sk-ant-…   # or `ant auth login`
uv run python scripts/chat.py hvac  # chat with the agent (no telephony)
```
