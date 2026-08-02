"""The web process: the one route the texted link resolves to, and the seam.

No database anywhere in here. The route depends on the `CallStore` protocol, so the
suite overrides it with a dict — persisting a row is SQLAlchemy's and Alembic's job to
get right, not something worth a live CockroachDB in an offline test run.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from receptionist.api.app import app
from receptionist.api.deps import call_store
from receptionist.core.models import Booking, CallRecord, Outcome
from tests.support.fakes import CALLER, FakeCallStore

client = TestClient(app)


@pytest.fixture
def store() -> Iterator[FakeCallStore]:
    fake = FakeCallStore()
    app.dependency_overrides[call_store] = lambda: fake
    yield fake
    app.dependency_overrides.clear()


def _booked() -> CallRecord:
    starts_at = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
    return CallRecord(
        profile_id="hvac",
        business_name="Helpdesk Heating and Cooling",
        caller_number=CALLER,
        outcome=Outcome.BOOKED,
        booking=Booking(
            service="furnace repair",
            starts_at=starts_at,
            ends_at=starts_at.replace(hour=11),
            calendar_event_id="evt_1",
            details={"name": "Sam Lee", "address": "12 Oak St"},
        ),
    )


def test_healthz_is_answerable() -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


async def test_a_saved_call_comes_back_whole(store: FakeCallStore) -> None:
    """The response IS the CallRecord, so what the agent wrote is what the SPA renders."""
    record = _booked()
    record.said("caller", "my furnace quit")
    record.emit("booking_created", "furnace repair")
    await store.save(record)

    body = client.get(f"/api/calls/{record.id}").json()

    assert body == record.model_dump(mode="json")
    assert body["booking"]["details"] == {"name": "Sam Lee", "address": "12 Oak St"}
    assert [turn["role"] for turn in body["transcript"]] == ["caller"]


def test_an_unknown_call_is_not_found(store: FakeCallStore) -> None:
    assert client.get(f"/api/calls/{uuid4()}").status_code == 404


def test_a_call_id_that_is_not_a_uuid_is_rejected_before_the_store(
    store: FakeCallStore,
) -> None:
    assert client.get("/api/calls/not-a-uuid").status_code == 422


def test_the_link_from_an_older_text_still_resolves(store: FakeCallStore) -> None:
    """Links texted before the token was dropped carry a `?t=`. It is ignored, not an
    error — those messages are already on people's phones."""
    record = _booked()
    # Sync context, so drive the fake's dict directly rather than awaiting save().
    store.calls[record.id] = record

    assert client.get(f"/api/calls/{record.id}?t=deadbeefdeadbeef").status_code == 200


def test_an_unknown_route_is_not_found() -> None:
    """`/c/{id}` is a client-side route on the SPA; this process serves JSON only."""
    assert client.get(f"/c/{uuid4()}").status_code == 404


def test_the_web_process_does_not_import_the_agent() -> None:
    """`CallRecord.business_name` is stamped at call start precisely so this holds.

    Reaching into `worker/profiles/` for that one string costs ~600ms of boot and 188
    langchain/langgraph modules, because a profile carries its agent's tools. A failure
    here means something under `api/` reached into `worker/`.

    Run in a subprocess: this test session has already imported everything. It also
    proves the app imports with no RECEPTIONIST_DATABASE_URL — the engine is built on
    first use, not at import.
    """
    probe = (
        "import receptionist.api.app, sys;"
        "print('\\n'.join(sorted(m for m in sys.modules if m.startswith("
        "('langchain', 'langgraph', 'livekit', 'googleapiclient', 'receptionist.worker')"
        "))))"
    )
    leaked = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    ).stdout.strip()

    assert leaked == "", f"importing the api dragged in:\n{leaked}"
