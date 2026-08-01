"""Appointments.

    service.py  the CalendarService seam: the protocol, Booked, the slot grid, the
                startup check, and the factory that picks an implementation
    google.py   the one implementation, against Google Calendar v3

The split is policy from vendor. How long an appointment runs and when the last one may
start are ours; `google.py` only knows how to ask Google.
"""
