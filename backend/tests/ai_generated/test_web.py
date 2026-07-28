"""Every section of the call-detail page, and each way of failing to produce one.

The two guarantees that matter — the signed link works, and every rejection looks
identical — are in `tests/test_call_page.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from receptionist.links import sign
from receptionist.models import Booking, CallRecord, Message, Outcome
from receptionist.settings import settings
from receptionist.store import CallStore
from receptionist.web import app as web
from tests.fakes import CALLER

STARTS = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CallStore:
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "calls.db"))
    web.store.cache_clear()
    yield CallStore(tmp_path / "calls.db")
    web.store.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(web.app)


def booked_call() -> CallRecord:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.BOOKED
    record.booking = Booking(
        service="furnace repair",
        starts_at=STARTS,
        ends_at=STARTS + timedelta(hours=1),
        calendar_event_id="evt_1",
        details={"name": "Sam Lee", "address": "12 Oak St, Burnaby"},
    )
    record.said("caller", "my furnace quit")
    record.said("agent", "I can get someone out tomorrow")
    record.emit("booking_created", "furnace repair")
    record.ended_at = record.started_at + timedelta(seconds=252)
    return record


def visit(client: TestClient, record: CallRecord) -> object:
    return client.get(f"/c/{record.id}?t={sign(record.id)}")


async def test_healthz_is_answerable(client: TestClient) -> None:
    assert client.get("/healthz").json() == {"ok": True}


async def test_the_page_shows_the_details_timeline_and_transcript(
    store: CallStore, client: TestClient
) -> None:
    record = booked_call()
    await store.save(record)

    body = visit(client, record).text

    assert "12 Oak St, Burnaby" in body
    assert "Booking created" in body
    assert "my furnace quit" in body
    assert "4:12" in body  # duration


async def test_a_taken_message_is_shown_without_a_calendar_button(
    store: CallStore, client: TestClient
) -> None:
    record = CallRecord(profile_id="hvac", caller_number=CALLER)
    record.outcome = Outcome.MESSAGE_TAKEN
    record.message = Message(name="Dana", reason="commercial boiler quote")
    await store.save(record)

    body = visit(client, record).text

    assert "commercial boiler quote" in body
    assert "Add to Google Calendar" not in body


async def test_the_page_escapes_what_a_caller_said(store: CallStore, client: TestClient) -> None:
    record = booked_call()
    record.said("caller", "<script>alert('x')</script>")
    await store.save(record)

    body = visit(client, record).text

    assert "<script>alert" not in body
    assert "&lt;script&gt;" in body


# --- every failure looks identical ---------------------------------------------


async def test_a_wrong_token_is_not_found(store: CallStore, client: TestClient) -> None:
    record = booked_call()
    await store.save(record)

    response = client.get(f"/c/{record.id}?t={'0' * 16}")

    assert response.status_code == 404
    assert "Helpdesk" not in response.text


async def test_a_missing_token_is_not_found(store: CallStore, client: TestClient) -> None:
    record = booked_call()
    await store.save(record)
    assert client.get(f"/c/{record.id}").status_code == 404


async def test_an_unknown_call_is_not_found(store: CallStore, client: TestClient) -> None:
    unknown = uuid4()
    assert client.get(f"/c/{unknown}?t={sign(unknown)}").status_code == 404


async def test_a_malformed_id_is_not_found(store: CallStore, client: TestClient) -> None:
    assert client.get("/c/not-a-uuid?t=whatever").status_code == 404
