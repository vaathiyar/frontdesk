"""The SQLite store. A real file, because the worker and the web server are separate
processes and every confirmation text contains a link the web server has to resolve."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from receptionist.core.models import Booking, CallRecord, Message, Outcome
from receptionist.core.store import CallStore
from tests.support.fakes import CALLER


@pytest.fixture
def store(tmp_path: Path) -> CallStore:
    return CallStore(tmp_path / "calls.db")


def _record(**overrides: object) -> CallRecord:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    for key, value in overrides.items():
        setattr(record, key, value)
    return record


async def test_a_saved_call_comes_back_whole(store: CallStore) -> None:
    starts = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
    record = _record(
        outcome=Outcome.BOOKED,
        booking=Booking(
            service="furnace repair",
            starts_at=starts,
            ends_at=starts + timedelta(hours=1),
            calendar_event_id="evt_1",
            details={"name": "Sam Lee", "address": "12 Oak St"},
        ),
    )
    record.said("caller", "my furnace quit")
    record.said("agent", "I can help")
    record.emit("booking_created", "furnace repair")

    await store.save(record)
    loaded = await store.get(record.id)

    assert loaded is not None
    assert loaded.model_dump() == record.model_dump()


async def test_a_message_survives_the_round_trip(store: CallStore) -> None:
    record = _record(
        outcome=Outcome.MESSAGE_TAKEN,
        message=Message(name="Dana", reason="commercial boiler quote"),
    )
    await store.save(record)
    loaded = await store.get(record.id)

    assert loaded is not None
    assert loaded.message is not None
    assert loaded.message.name == "Dana"


async def test_an_unknown_call_is_simply_absent(store: CallStore) -> None:
    assert await store.get(uuid4()) is None


async def test_saving_twice_updates_rather_than_duplicates(store: CallStore) -> None:
    record = _record()
    await store.save(record)
    record.outcome = Outcome.BOOKED
    await store.save(record)

    assert len(await store.list_recent()) == 1
    loaded = await store.get(record.id)
    assert loaded is not None
    assert loaded.outcome is Outcome.BOOKED


async def test_recent_calls_come_back_newest_first(store: CallStore) -> None:
    now = datetime.now(UTC)
    for minutes in (0, 5, 10):
        await store.save(_record(started_at=now + timedelta(minutes=minutes)))

    recent = await store.list_recent()
    assert [r.started_at for r in recent] == sorted((r.started_at for r in recent), reverse=True)


async def test_recent_calls_respect_the_limit(store: CallStore) -> None:
    for _ in range(4):
        await store.save(_record())
    assert len(await store.list_recent(limit=2)) == 2


async def test_a_second_store_on_the_same_file_sees_the_same_calls(tmp_path: Path) -> None:
    """This is the whole point of using a file: the web server is a different process."""
    path = tmp_path / "calls.db"
    record = _record()
    await CallStore(path).save(record)

    assert await CallStore(path).get(record.id) is not None
