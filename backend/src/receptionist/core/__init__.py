"""What the worker and the web service both speak: the record, and where it lives.

    models.py   CallRecord & friends — the one shape, written by one process, read by the other
    store.py    SQLite; the worker saves, the API reads

Nothing in here may import from `worker/` or `api/`. That rule is what keeps the web
process from dragging LangGraph, LiveKit and Google Calendar in behind it, and a test
(`tests/ai_generated/test_api.py`) enforces the direction.

Both modules are worker-only by today's import graph, because `api/` is still a health
check. They are here on the contract in `frontend_spec.md` §7 — `GET /api/calls` needs
`store.list_recent`, and every response serialises a `CallRecord`. `links.py` belongs here
by the same argument and currently is not; see `worker/lib/links.py`.
"""
