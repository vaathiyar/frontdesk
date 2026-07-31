"""Normalising the number SIP hands over.

The bug this exists for: Telnyx delivers caller ID as `16727272720`, with no `+`. That
failed the E.164 check and no confirmation text went out — but the quieter half is that
`caller_number` is the exact-match key `reschedule` and `cancel` look a booking up by, so
the same caller arriving in two spellings loses their booking.
"""

from __future__ import annotations

import pytest

from receptionist.phone import to_e164


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("16727272720", "+16727272720"),  # what Telnyx actually sends
        ("+16727272720", "+16727272720"),  # already correct, left alone
        (" 16727272720 ", "+16727272720"),  # trimmed
        ("442071838750", "+442071838750"),  # not a NANP number
    ],
)
def test_a_bare_international_number_gets_its_plus_back(raw: str, expected: str) -> None:
    assert to_e164(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "local-console",  # the console path must survive untouched
        "",
        "not-a-number",
        "+1 604 555 1234",  # spaced; not our job to guess
        "0123456789",  # E.164 never starts with 0
        "123",  # too short to be E.164
    ],
)
def test_anything_that_is_not_a_bare_number_is_left_alone(raw: str) -> None:
    assert to_e164(raw) == raw


def test_digits_without_a_country_code_are_not_repaired() -> None:
    """The sharp edge, pinned so it stays visible.

    A country-coded string is indistinguishable from a national one, so ten NANP digits
    come out as `+60…` (Malaysia) rather than `+1…`. Inferring `+1` instead would be worse
    — it would put a real stranger's number on the record and text them. Everything on the
    phone path arrives country-coded from Telnyx, which is what makes this safe in practice.
    """
    assert to_e164("6045551234") == "+6045551234"


def test_normalising_is_idempotent() -> None:
    assert to_e164(to_e164("16727272720")) == "+16727272720"
