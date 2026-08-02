"""The call link, and the add-to-calendar link."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from receptionist.settings import settings
from receptionist.worker.lib.links import call_url, google_calendar_url

CALL = uuid4()


def test_the_call_link_is_the_bare_id_and_nothing_else() -> None:
    """No query string: the link is unauthenticated, and every character it doesn't
    carry is one more the confirmation text can spend on the appointment."""
    url = urlparse(call_url(CALL))
    assert url.path == f"/c/{CALL}"
    assert url.query == ""


def test_call_url_does_not_double_the_slash_on_a_trailing_base(
    monkeypatch: object,
) -> None:
    original = settings.public_base_url
    try:
        settings.public_base_url = "https://example.com/"
        assert call_url(CALL).startswith("https://example.com/c/")
    finally:
        settings.public_base_url = original


def test_calendar_link_sends_local_wall_time_with_a_timezone() -> None:
    """Wall time plus ctz, never UTC: the caller must see the hour they were told."""
    starts = datetime(2026, 7, 29, 10, 0)
    query = parse_qs(
        urlparse(
            google_calendar_url(
                title="Furnace repair",
                starts_at=starts,
                ends_at=datetime(2026, 7, 29, 11, 0),
                location="12 Oak St, Burnaby",
            )
        ).query
    )

    assert query["action"] == ["TEMPLATE"]
    assert query["dates"] == ["20260729T100000/20260729T110000"]
    assert query["ctz"] == [settings.timezone]
    assert query["text"] == ["Furnace repair"]
    assert query["location"] == ["12 Oak St, Burnaby"]


def test_calendar_link_omits_empty_optional_parts() -> None:
    query = parse_qs(
        urlparse(
            google_calendar_url(
                title="Table for 4",
                starts_at=datetime(2026, 7, 29, 19, 0),
                ends_at=datetime(2026, 7, 29, 20, 0),
            )
        ).query
    )

    assert "location" not in query
    assert "details" not in query


def test_calendar_link_escapes_what_would_break_the_query_string() -> None:
    url = google_calendar_url(
        title="Repair & service",
        starts_at=datetime(2026, 7, 29, 10, 0),
        ends_at=datetime(2026, 7, 29, 11, 0),
    )
    # A raw ampersand would split the parameter and lose half the title.
    assert "Repair%20%26%20service" in url
    assert parse_qs(urlparse(url).query)["text"] == ["Repair & service"]
