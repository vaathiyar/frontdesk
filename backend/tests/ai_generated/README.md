# ai_generated

Machine-written exhaustive coverage — a regression net, not required reading: date and
time parsing tables, business-hours internals, the Google Calendar adapter against a
stub client, the JSONB round trip, URL encoding, tool-schema introspection, and every
individual branch of the confirmation text.

Nothing here opens a database or a socket. `test_db.py` exercises the projection into
columns and back out of the blob as plain object conversion; `test_api.py` overrides the
`CallStore` dependency with a dict. Whether CockroachDB then stores the row is
SQLAlchemy's and Alembic's problem — read the DDL with `uv run alembic upgrade head --sql`.

The guarantees worth a human's attention are the twenty-one tests one directory up. These
run by default and must stay green; fixtures come from `tests/conftest.py`, the scripted
model and fake store from `tests/support/fakes.py`, and the in-memory calendar from
`tests/support/fake_calendar.py`.
