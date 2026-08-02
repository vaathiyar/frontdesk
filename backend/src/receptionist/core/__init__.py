"""What the worker and the web service both speak: the record, and where it lives.

    models.py   CallRecord & friends — the one shape, written by one process, read by the other
    db/         CockroachDB, over SQLAlchemy; the worker saves, the API reads

Nothing in here may import from `worker/` or `api/`. That rule is what keeps the web
process from dragging LangGraph, LiveKit and Google Calendar in behind it, and a test
(`tests/ai_generated/test_api.py`) enforces the direction.

Two entries, which is the whole seam. `CallRecord` is also what `GET /api/calls/{id}`
returns, so the shape the agent writes and the shape the SPA renders are the same object
and cannot drift.
"""
