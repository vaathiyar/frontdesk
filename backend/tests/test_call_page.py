"""The page the link in the confirmation text opens.

The link is unguessable but has no expiry, so the token is the whole access control:
either it verifies and you see the call, or you get one indistinguishable 404.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from receptionist.links import call_url, sign
from receptionist.models import CallRecord
from receptionist.settings import settings
from receptionist.store import CallStore
from receptionist.web import app as web


@pytest.fixture
def store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[CallStore]:
    monkeypatch.setattr(settings, "database_path", str(tmp_path / "calls.db"))
    web.store.cache_clear()
    yield CallStore(tmp_path / "calls.db")
    web.store.cache_clear()


@pytest.fixture
def client() -> TestClient:
    return TestClient(web.app)


async def test_the_link_from_the_text_shows_the_booking_and_a_calendar_button(
    booked_record: CallRecord, store: CallStore, client: TestClient
) -> None:
    """The URL asked for here is the exact one the caller receives by text."""
    await store.save(booked_record)

    response = client.get(call_url(booked_record.id))

    assert response.status_code == 200
    assert "Helpdesk Heating and Cooling" in response.text
    assert "furnace repair" in response.text
    assert "Wednesday, July 29 at 10:00 AM" in response.text
    assert "12 Oak St, Burnaby" in response.text
    assert "Add to Google Calendar" in response.text
    assert "calendar.google.com/calendar/render" in response.text


async def test_every_rejected_link_returns_the_identical_not_found_page(
    booked_record: CallRecord, store: CallStore, client: TestClient
) -> None:
    """Responses that differed would tell someone which call ids exist."""
    await store.save(booked_record)
    unknown = uuid4()

    wrong_token = client.get(f"/c/{booked_record.id}?t={'0' * 16}")
    no_token = client.get(f"/c/{booked_record.id}")
    unknown_call = client.get(f"/c/{unknown}?t={sign(unknown)}")
    malformed_id = client.get("/c/not-a-uuid?t=whatever")
    rejected = [wrong_token, no_token, unknown_call, malformed_id]

    assert [response.status_code for response in rejected] == [404, 404, 404, 404]
    assert len({response.text for response in rejected}) == 1
    assert "Helpdesk" not in wrong_token.text
