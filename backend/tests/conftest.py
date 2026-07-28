"""Shared fixtures. The offline suite runs with no network and no API key."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from receptionist.models import Booking, CallRecord, Outcome
from receptionist.services.calendar import FakeCalendarService
from receptionist.settings import settings
from tests.fakes import CALLER, day_after


@pytest.fixture(autouse=True)
def never_text_anyone(monkeypatch: pytest.MonkeyPatch) -> None:
    """Blank the Telnyx credentials for every single test.

    `settings` is a module-level singleton loaded from `.env`, so on a machine with real
    credentials any test that reached `send_sms` would post to Telnyx for real. That
    happened once, to a number invented for a fixture. The suite must be incapable of it,
    not merely unlikely to do it — so this is autouse and not opt-out. A test that needs
    the configured path sets the credentials itself and supplies a stub transport.
    """
    monkeypatch.setattr(settings, "telnyx_api_key", "")
    monkeypatch.setattr(settings, "telnyx_from_number", "")


@pytest.fixture
def tomorrow() -> str:
    return day_after(1)


@pytest.fixture
def next_week() -> str:
    return day_after(7)


@pytest.fixture
def calendar() -> FakeCalendarService:
    return FakeCalendarService()


@pytest.fixture
def record() -> CallRecord:
    return CallRecord(profile_id="hvac", caller_number=CALLER)


@pytest.fixture
def booked_record(record: CallRecord) -> CallRecord:
    """A call that booked something, at the moment the caller hangs up.

    A fixed date, so the tests can name the day and time the caller was told. `ended_at`
    is left unset: stamping it is `finish_call`'s job.
    """
    starts_at = datetime(2026, 7, 29, 10, 0, tzinfo=UTC)
    record.outcome = Outcome.BOOKED
    record.booking = Booking(
        service="furnace repair",
        starts_at=starts_at,
        ends_at=starts_at + timedelta(hours=1),
        calendar_event_id="evt_1",
        details={"name": "Sam Lee", "address": "12 Oak St, Burnaby"},
    )
    record.said("caller", "my furnace quit")
    record.said("agent", "I can get someone out Wednesday morning")
    record.emit("booking_created", "furnace repair on Wednesday, July 29 at 10:00 AM")
    return record
