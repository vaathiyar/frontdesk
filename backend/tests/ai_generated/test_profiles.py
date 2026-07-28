"""The extension surface: every profile must be usable by the graph without special-casing.

Schema introspection, mostly. The behavioural version of this — a second profile booking
on the same engine — is in `tests/test_call_flow.py`.
"""

from __future__ import annotations

import pytest

from receptionist.agent.graph import build_graph
from receptionist.agent.prompt import render
from receptionist.agent.tools import SHARED_TOOLS
from receptionist.profiles import PROFILES, UnknownProfile, get_profile
from tests.fakes import ScriptedModel

PROFILE_IDS = list(PROFILES)


def test_registry_is_keyed_by_the_profiles_own_id() -> None:
    assert all(key == profile.id for key, profile in PROFILES.items())


def test_unknown_profile_fails_fast() -> None:
    with pytest.raises(UnknownProfile):
        get_profile("dental")


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_every_profile_builds_a_graph(profile_id: str) -> None:
    build_graph(get_profile(profile_id), ScriptedModel())


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_prompt_carries_the_business_its_work_and_its_facts(profile_id: str) -> None:
    profile = get_profile(profile_id)
    prompt = render(profile)

    assert profile.business in prompt
    assert profile.does in prompt
    assert profile.knowledge in prompt


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_prompt_anchors_today_and_demands_iso_dates(profile_id: str) -> None:
    prompt = render(get_profile(profile_id))

    assert "Today is" in prompt
    assert "YYYY-MM-DD" in prompt


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_prompt_never_asks_permission_to_text(profile_id: str) -> None:
    assert "Never ask permission to text" in render(get_profile(profile_id))


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_book_always_takes_a_service_a_day_and_a_time(profile_id: str) -> None:
    schema = get_profile(profile_id).book.tool_call_schema.model_json_schema()

    assert {"service", "day", "time"} <= set(schema["properties"])
    # Every field is required: a partial call must fail the schema, not book a half-booking.
    assert set(schema["required"]) == set(schema["properties"])


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_book_collects_a_name_and_describes_every_field_to_the_model(profile_id: str) -> None:
    properties = get_profile(profile_id).book.tool_call_schema.model_json_schema()["properties"]

    assert "name" in properties
    undocumented = [key for key, spec in properties.items() if not spec.get("description")]
    # `parse_docstring=True` silently skips params missing from the Args: block, so an
    # undocumented field would reach the model with no guidance at all.
    assert undocumented == []


@pytest.mark.parametrize("profile_id", PROFILE_IDS)
def test_the_per_call_runtime_is_never_exposed_to_the_model(profile_id: str) -> None:
    profile = get_profile(profile_id)
    for tool in [*SHARED_TOOLS, profile.book, *profile.extra_tools]:
        assert "runtime" not in tool.tool_call_schema.model_json_schema().get("properties", {})


def test_hvac_collects_where_to_send_the_technician() -> None:
    properties = get_profile("hvac").book.tool_call_schema.model_json_schema()["properties"]
    assert "address" in properties


def test_restaurant_collects_the_party_size_and_loads_its_own_menu() -> None:
    restaurant = get_profile("restaurant")
    properties = restaurant.book.tool_call_schema.model_json_schema()["properties"]

    assert "party_size" in properties
    assert "address" not in properties
    assert "Tiramisu" in restaurant.knowledge
