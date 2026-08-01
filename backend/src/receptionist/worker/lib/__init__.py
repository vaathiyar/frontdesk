"""The worker's vocabulary: how it talks about time, phone numbers and credentials.

    datetimes.py     "tomorrow at 10" -> a datetime, and datetimes -> speech
    phone.py         E.164, normalised where SIP hands a number over
    google_auth.py   which Google service-account credential, in what shape
    links.py         the signed call link, and the add-to-calendar URL

Each is imported by two or three sibling packages, so none of them belongs to one. What
they have in common is the bar for living here: **no domain state** — nothing in this
package knows what a CallRecord, a Profile or a booking is, and nothing does I/O of its
own beyond reading `settings`.

Not the same thing as `core/`, one level up: that is the seam between the two *processes*.
This is shared within the worker only, and the web service imports none of it.

`links.py` is the one module here with a foot in both camps — the worker signs, the API
will verify. It sits here while the worker is its only caller; its docstring says what
happens when that changes.
"""
