"""Shared fixtures. The offline suite runs with no network and no API key."""

from __future__ import annotations

import pytest

from receptionist.models import CallRecord
from receptionist.services.calendar import FakeCalendarService
from tests.fakes import CALLER, day_after


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
