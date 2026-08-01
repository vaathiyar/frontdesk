# ai_generated

Machine-written exhaustive coverage — a regression net, not required reading: date and
time parsing tables, business-hours internals, the Google Calendar adapter against a
stub client, SQLite round-trips, URL encoding, tool-schema introspection, and every
individual branch of the confirmation text.

The guarantees worth a human's attention are the twenty-one tests one directory up. These
run by default and must stay green; fixtures come from `tests/conftest.py`, the scripted
model from `tests/support/fakes.py`, and the in-memory calendar from `tests/support/fake_calendar.py`.
