"""The database seam, without a database.

Nothing here connects to anything. What is worth testing is the part we wrote — the
projection into columns, the round trip back out of the JSONB, the scheme rewrite that lets
a CockroachDB connection string be pasted in unedited, and the retry that keeps a
SERIALIZABLE abort from costing us a call. Whether CockroachDB then
stores the row is SQLAlchemy's and Alembic's problem, and the DDL is reviewable with
`alembic upgrade head --sql`. Refusing to start without a URL is in `test_startup_config.py`
with the other startup checks.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from sqlalchemy.exc import DBAPIError

from receptionist.core.db.store import _with_retry
from receptionist.core.db.tables import CallRow
from receptionist.core.models import Booking, CallRecord, Message, Outcome
from receptionist.settings import Settings
from tests.support.fakes import CALLER

STARTS_AT = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)


def _booked() -> CallRecord:
    record = CallRecord(
        profile_id="hvac",
        business_name="Helpdesk Heating and Cooling",
        caller_number=CALLER,
        called_number="+16042969870",
        ended_at=STARTS_AT + timedelta(minutes=4),
        outcome=Outcome.BOOKED,
        booking=Booking(
            service="furnace repair",
            starts_at=STARTS_AT,
            ends_at=STARTS_AT + timedelta(hours=1),
            calendar_event_id="evt_1",
            details={"name": "Sam Lee", "address": "12 Oak St"},
        ),
    )
    record.said("caller", "my furnace quit")
    record.emit("booking_created", "furnace repair")
    return record


# --- the round trip -------------------------------------------------------------


def test_a_record_survives_the_round_trip_whole() -> None:
    """The blob is the record. Everything the columns don't carry has to come back."""
    record = _booked()

    loaded = CallRow.of(record).to_record()

    assert loaded.model_dump() == record.model_dump()


def test_a_message_survives_the_round_trip() -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.message = Message(name="Dana", reason="commercial boiler quote")

    loaded = CallRow.of(record).to_record()

    assert loaded.message is not None
    assert loaded.message.reason == "commercial boiler quote"


def test_the_columns_are_a_faithful_projection_of_the_blob() -> None:
    """They are written and never read, so nothing else would catch them drifting."""
    record = _booked()

    row = CallRow.of(record)

    assert row.id == record.id
    assert row.profile_id == "hvac"
    assert row.caller_number == CALLER
    assert row.started_at == record.started_at
    assert row.ended_at == record.ended_at
    assert row.outcome == "booked"


def test_an_unfinished_call_projects_nulls_rather_than_failing() -> None:
    """A record saved at call start has no outcome and no end; both columns are nullable
    precisely so that write does not have to wait for the caller to hang up."""
    row = CallRow.of(CallRecord(profile_id="hvac", caller_number=CALLER))

    assert row.ended_at is None
    assert row.outcome is None


def test_the_blob_is_json_types_only() -> None:
    """`mode="json"` matters: a raw model_dump leaves datetimes and the UUID as Python
    objects, which the JSONB serialiser refuses."""
    blob = CallRow.of(_booked()).record

    assert isinstance(blob["id"], str)
    assert isinstance(blob["started_at"], str)
    assert blob["outcome"] == "booked"


# --- the connection string --------------------------------------------------------


def test_a_cockroach_connection_string_is_pasted_in_unchanged() -> None:
    """Only the scheme is rewritten. Host, credentials and sslmode pass through, so the
    string CockroachDB hands you is the string that goes in the environment."""
    tail = "user:pw@free-tier.gcp.cockroachlabs.cloud:26257/defaultdb?sslmode=verify-full"

    assert (
        Settings(database_url=f"postgresql://{tail}").database_url
        == f"cockroachdb+psycopg://{tail}"
    )
    assert (
        Settings(database_url=f"postgres://{tail}").database_url == f"cockroachdb+psycopg://{tail}"
    )


def test_a_url_that_already_names_the_dialect_is_left_alone() -> None:
    url = "cockroachdb+psycopg://user:pw@localhost:26257/defaultdb"

    assert Settings(database_url=url).database_url == url


# --- retrying a serialization failure -----------------------------------------------


def _aborted() -> DBAPIError:
    """What CockroachDB raises when it aborts a transaction for the client to retry."""
    orig = psycopg.errors.SerializationFailure("restart transaction: TransactionRetryError")
    return DBAPIError("UPSERT", {}, orig)


async def test_a_serialization_failure_is_retried_rather_than_losing_the_call() -> None:
    """CockroachDB is SERIALIZABLE: under contention it aborts and expects a retry.
    Not retrying loses a record after the caller has already hung up."""
    attempts = 0

    async def flaky() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise _aborted()
        return "written"

    assert await _with_retry("saving", flaky) == "written"
    assert attempts == 3


async def test_retries_are_bounded_rather_than_hanging_on_a_wedged_cluster() -> None:
    attempts = 0

    async def always_aborts() -> None:
        nonlocal attempts
        attempts += 1
        raise _aborted()

    with pytest.raises(DBAPIError):
        await _with_retry("saving", always_aborts)
    assert attempts == 3


async def test_any_other_database_error_is_raised_at_once() -> None:
    """A bad password or a missing table is not going to fix itself in 100ms, and the
    caller is owed the real error rather than three of them."""
    attempts = 0

    async def undefined_table() -> None:
        nonlocal attempts
        attempts += 1
        raise DBAPIError("SELECT", {}, psycopg.errors.UndefinedTable("no such table: calls"))

    with pytest.raises(DBAPIError):
        await _with_retry("reading", undefined_table)
    assert attempts == 1
