"""Phone numbers in one shape: E.164, with the leading `+`.

The caller's number is not only where the confirmation text goes — it is the key that
`reschedule` and `cancel` find a booking by. `services/google_calendar.py` stores it as an
extended property and matches it *exactly*, and the fake keys a dict on it. So a caller who
books as `16045551234` and rings back as `+16045551234` is two different people, and their
booking has vanished.

That is why this normalises at the edge, where SIP hands the number over, rather than in
the one consumer that noticed first. Telnyx delivers caller ID as bare digits with no `+`,
which is the case this exists for.
"""

from __future__ import annotations

import re

# 8-15 digits, the first of them non-zero. The `+` is what makes it E.164 rather than a
# guess about whose national dialling plan applies.
E164 = re.compile(r"^\+[1-9]\d{7,14}$")


def to_e164(raw: str) -> str:
    """Give a bare international number its `+` back; leave anything else untouched.

    **This assumes the digits already carry a country code**, which is what SIP hands over.
    Nothing can tell a country-coded string from a national one, so `6045551234` becomes
    `+6045551234` — Malaysia — and not `+16045551234`. Guessing a country instead would be
    worse: it would write a real stranger's number onto the record and text them. Telnyx
    sends full international numbers, so this holds for the path that matters.

    Non-numbers pass straight through, keeping `local-console` working off the phone path.
    """
    number = raw.strip()
    if number.isdigit() and E164.match(f"+{number}"):
        return f"+{number}"
    return number
