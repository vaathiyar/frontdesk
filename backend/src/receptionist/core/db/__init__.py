"""Where finished calls live: CockroachDB, reached over SQLAlchemy.

    engine.py   the connection — one pool per process, built on first use
    tables.py   the schema, and the two conversions to and from `CallRecord`
    store.py    what the rest of the app depends on: the `CallStore` seam

**The JSONB blob is the record; the columns beside it are a projection of it.** Every
read goes `CallRecord.model_validate(row.record)`, so a call round-trips through exactly
one format — the JSON pydantic itself wrote. Promoting `outcome`, `started_at` and the
rest into columns therefore cannot create a second, disagreeing source of truth: nothing
ever reads them back. They exist so a future query does not have to open the blob.

Nothing in here may import from `worker/` or `api/`, per `core/__init__.py`.
"""
