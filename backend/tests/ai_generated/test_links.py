"""Signed call links, and the add-to-calendar link."""

from __future__ import annotations

from datetime import datetime
from urllib.parse import parse_qs, urlparse
from uuid import uuid4

from receptionist.settings import settings
from receptionist.worker.lib.links import TOKEN_LENGTH, call_url, google_calendar_url, sign, verify

CALL = uuid4()


def test_signing_is_deterministic_and_short_enough_for_one_sms_segment() -> None:
    assert sign(CALL) == sign(CALL)
    assert len(sign(CALL)) == TOKEN_LENGTH


def test_a_matching_token_verifies() -> None:
    assert verify(CALL, sign(CALL))


def test_a_wrong_token_does_not_verify() -> None:
    assert not verify(CALL, "0" * TOKEN_LENGTH)
    assert not verify(CALL, "")


def test_a_token_for_another_call_does_not_verify() -> None:
    assert not verify(CALL, sign(uuid4()))


def test_a_different_secret_invalidates_the_token() -> None:
    assert not verify(CALL, sign(CALL, secret="one"), secret="two")


def test_call_url_carries_the_id_and_its_token() -> None:
    url = urlparse(call_url(CALL))
    assert url.path == f"/c/{CALL}"
    assert parse_qs(url.query)["t"] == [sign(CALL)]


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
