"""Turning what a caller said about time into datetimes, and back into words."""

from __future__ import annotations

from datetime import date, datetime

import pytest

from receptionist.worker.lib.datetimes import fmt_time, pretty_day, resolve_date, resolve_time


@pytest.mark.parametrize(
    ("said", "expected"),
    [("today", 0), ("tomorrow", 1)],
)
def test_relative_days(said: str, expected: int) -> None:
    assert resolve_date(said, date(2026, 7, 27)) == date(2026, 7, 27 + expected)


def test_a_weekday_means_the_next_one_never_today() -> None:
    monday = date(2026, 7, 27)  # a Monday
    assert resolve_date("monday", monday) == date(2026, 8, 3)
    assert resolve_date("next tuesday", monday) == date(2026, 7, 28)


def test_iso_dates_pass_straight_through() -> None:
    assert resolve_date("2026-08-14", date(2026, 7, 27)) == date(2026, 8, 14)


@pytest.mark.parametrize(
    ("said", "hour", "minute"),
    [("10:00 AM", 10, 0), ("10am", 10, 0), ("14:00", 14, 0), ("2:30 pm", 14, 30)],
)
def test_times_people_actually_say(said: str, hour: int, minute: int) -> None:
    parsed = resolve_time(said)
    assert (parsed.hour, parsed.minute) == (hour, minute)


@pytest.mark.parametrize("said", ["", "whenever", "the usual"])
def test_unreadable_input_is_rejected_so_the_agent_can_ask_again(said: str) -> None:
    with pytest.raises(ValueError):
        resolve_date(said, date(2026, 7, 27))
    with pytest.raises(ValueError):
        resolve_time(said)


def test_dates_are_spoken_as_words_never_digits() -> None:
    assert pretty_day("2026-07-29") == "Wednesday, July 29"
    # Anything not an ISO date is passed through untouched.
    assert pretty_day("tomorrow") == "tomorrow"


def test_times_have_no_leading_zero() -> None:
    assert fmt_time(datetime(2026, 7, 29, 9, 5)) == "9:05 AM"
    assert fmt_time(datetime(2026, 7, 29, 13, 0)) == "1:00 PM"
    assert fmt_time(datetime(2026, 7, 29, 0, 30)) == "12:30 AM"
