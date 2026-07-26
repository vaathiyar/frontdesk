"""Shared fixtures. Tests run with no network and no API key."""

from __future__ import annotations

import pytest

from receptionist.core.models import CallRecord
from receptionist.services.calendar import FakeCalendarService


@pytest.fixture
def calendar() -> FakeCalendarService:
    return FakeCalendarService()


@pytest.fixture
def record() -> CallRecord:
    return CallRecord(profile_id="hvac", caller_number="+1-555-0100")
