"""What the processes refuse to start without.

None of these can be discovered safely at call time. A profile with no calendar fails with
a caller on the line; missing Telnyx credentials and an unreachable database fail *after*
they have hung up, as a log line nobody reads.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from receptionist.api.app import app
from receptionist.core.db.engine import DatabaseNotConfigured, require_database
from receptionist.settings import settings
from receptionist.worker.booking.service import (
    CalendarNotConfigured,
    build_calendar,
    require_calendar_ids,
)
from receptionist.worker.messaging.telnyx import TelnyxNotConfigured, require_credentials
from receptionist.worker.profiles import PROFILES, get_profile

# --- a calendar for every profile -------------------------------------------------


def test_a_profile_without_a_calendar_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "calendar_ids", {"hvac": "hvac@cal"})

    with pytest.raises(CalendarNotConfigured) as raised:
        require_calendar_ids(PROFILES)

    # It has to name what to fix; "misconfigured" alone sends you reading source.
    assert "restaurant" in str(raised.value)
    assert "hvac" not in str(raised.value)


def test_a_misspelled_profile_id_is_named_as_the_likely_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keys are matched exactly, so a typo is by far the likeliest failure here.

    Saying only "restaurant is missing" sends you to check the deployment. Saying it while
    pointing at the unrecognised key is the actual answer, and it cost one real deploy to
    learn that.
    """
    monkeypatch.setattr(settings, "calendar_ids", {"hvac": "hvac@cal", "restraunt": "oops@cal"})

    with pytest.raises(CalendarNotConfigured) as raised:
        require_calendar_ids(PROFILES)

    assert "restaurant" in str(raised.value)
    assert "restraunt" in str(raised.value)
    assert "check the spelling" in str(raised.value)
    # Keys, never the calendar ids themselves.
    assert "oops@cal" not in str(raised.value)


def test_startup_passes_once_every_profile_has_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        settings, "calendar_ids", {profile_id: f"{profile_id}@cal" for profile_id in PROFILES}
    )

    require_calendar_ids(PROFILES)  # does not raise


def test_building_a_calendar_refuses_rather_than_booking_nowhere(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The startup check is the guard; this is the backstop if a profile is added later."""
    monkeypatch.setattr(settings, "calendar_ids", {})

    with pytest.raises(CalendarNotConfigured):
        build_calendar(get_profile("hvac"))


# --- credentials to text the caller -----------------------------------------------


def test_no_telnyx_key_stops_startup() -> None:
    """`never_text_anyone` blanks the key, which is the unconfigured case exactly."""
    with pytest.raises(TelnyxNotConfigured, match="TELNYX_API_KEY"):
        require_credentials()


def test_a_malformed_fallback_number_stops_startup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bare digits are the usual slip, and Telnyx rejects them one call too late."""
    monkeypatch.setattr(settings, "telnyx_api_key", "KEY")
    monkeypatch.setattr(settings, "telnyx_from_number", "6045550000")

    with pytest.raises(TelnyxNotConfigured, match="E.164"):
        require_credentials()


def test_a_key_alone_is_enough_to_start(monkeypatch: pytest.MonkeyPatch) -> None:
    """The fallback is optional: a real call sends from the number it was dialled on."""
    monkeypatch.setattr(settings, "telnyx_api_key", "KEY")
    monkeypatch.setattr(settings, "telnyx_from_number", "")

    require_credentials()  # does not raise


# --- somewhere to put the call ------------------------------------------------------


def test_no_database_url_stops_startup() -> None:
    """`no_database` blanks the URL, which is the unconfigured case exactly."""
    with pytest.raises(DatabaseNotConfigured, match="RECEPTIONIST_DATABASE_URL"):
        require_database()


def test_the_web_process_refuses_to_start_without_a_database() -> None:
    """Checked in the lifespan, so a misconfigured web process never reports healthy —
    otherwise the only person who finds out is the caller who follows their link."""
    with pytest.raises(DatabaseNotConfigured), TestClient(app):
        pass  # pragma: no cover -- startup raises before the body runs
