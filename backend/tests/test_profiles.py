from __future__ import annotations

import pytest

from receptionist.core.models import CallRecord
from receptionist.profiles.factory import PROFILES, UnknownProfile, create_profile
from receptionist.services.calendar import FakeCalendarService


def _make(profile_id: str):
    record = CallRecord(profile_id=profile_id, caller_number="+1-555-0100")
    return create_profile(profile_id, FakeCalendarService(), record)


def test_factory_creates_every_registered_profile() -> None:
    for pid in PROFILES:
        agent = _make(pid)
        assert agent.profile_id == pid
        assert agent.business_name  # set by the subclass


def test_factory_rejects_unknown_profile() -> None:
    with pytest.raises(UnknownProfile):
        _make("dental")


def test_business_names_are_the_helpdesk_brand() -> None:
    assert _make("hvac").business_name == "Helpdesk Heating and Cooling"
    assert _make("restaurant").business_name == "Helpdesk Kitchen"


def test_system_prompt_includes_business_and_fields() -> None:
    agent = _make("hvac")
    prompt = agent.system_prompt()
    assert agent.business_name in prompt
    for f in agent.booking_fields():
        assert f.label in prompt


def test_every_profile_exposes_the_six_tools() -> None:
    expected = {
        "check_availability",
        "book",
        "reschedule",
        "cancel",
        "answer_question",
        "take_message",
    }
    for pid in PROFILES:
        names = {t["name"] for t in _make(pid).tool_schemas()}
        assert names == expected


def test_book_schema_requires_service_time_and_every_booking_field() -> None:
    agent = _make("hvac")
    book = next(t for t in agent.tool_schemas() if t["name"] == "book")
    required = set(book["input_schema"]["required"])
    assert {"service", "day", "time"} <= required
    for f in agent.booking_fields():
        assert f.key in required


def test_email_is_a_required_booking_field_everywhere() -> None:
    for pid in PROFILES:
        keys = {f.key for f in _make(pid).booking_fields()}
        assert "email" in keys
        assert "phone" not in keys  # phone comes from caller ID, never collected


def test_restaurant_loads_its_own_menu() -> None:
    knowledge = _make("restaurant").knowledge()
    assert "Margherita Pizza" in knowledge
