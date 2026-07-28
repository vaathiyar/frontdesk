"""The call-detail page, rendered server-side.

Single column and mobile-first on purpose: almost everyone who opens this arrived from
a link in a text message, on a phone. No JavaScript, no build step, no framework —
one function per section, so the page reads top to bottom like the page it produces.
"""

from __future__ import annotations

from html import escape

from receptionist.links import google_calendar_url
from receptionist.models import Booking, CallRecord, Outcome
from receptionist.profiles import Profile
from receptionist.services.when import fmt_time

STYLE = """
:root { --ink:#12151a; --muted:#666f7a; --line:#e4e7ec; --bg:#fbfcfd; --accent:#1b5e9c; }
* { box-sizing:border-box; }
body { margin:0; padding:24px 18px 64px; background:var(--bg); color:var(--ink);
       font:16px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }
main { max-width:640px; margin:0 auto; }
h1 { font-size:1.4rem; margin:0 0 4px; }
h2 { font-size:.8rem; text-transform:uppercase; letter-spacing:.08em; color:var(--muted);
     margin:32px 0 10px; }
.meta { color:var(--muted); font-size:.9rem; margin:0 0 20px; }
.badge { display:inline-block; padding:3px 10px; border-radius:999px; font-size:.75rem;
         font-weight:600; text-transform:uppercase; letter-spacing:.05em; }
.badge.booked, .badge.rescheduled { background:#e3f3e8; color:#1d6b39; }
.badge.cancelled, .badge.abandoned { background:#f1f2f4; color:#5b6470; }
.badge.message_taken, .badge.answered { background:#e6eff8; color:#1b5e9c; }
.card { background:#fff; border:1px solid var(--line); border-radius:12px; padding:18px; }
.card .what { font-weight:600; font-size:1.05rem; }
.card .when { color:var(--muted); }
.cta { display:block; margin-top:16px; padding:13px; border-radius:10px; text-align:center;
       background:var(--accent); color:#fff; font-weight:600; text-decoration:none; }
dl { display:grid; grid-template-columns:auto 1fr; gap:8px 16px; margin:0; }
dt { color:var(--muted); font-size:.9rem; }
dd { margin:0; }
ol { list-style:none; margin:0; padding:0; }
.timeline li { padding-left:18px; border-left:2px solid var(--line); padding-bottom:14px;
               position:relative; }
.timeline li:before { content:""; position:absolute; left:-5px; top:6px; width:8px;
                      height:8px; border-radius:50%; background:var(--accent); }
.timeline .what { font-weight:600; font-size:.92rem; }
.timeline .detail { color:var(--muted); font-size:.88rem; }
.turn { padding:10px 0; border-bottom:1px solid var(--line); }
.turn:last-child { border-bottom:0; }
.who { font-size:.75rem; text-transform:uppercase; letter-spacing:.06em; color:var(--muted); }
.turn.agent .who { color:var(--accent); }
.note { color:var(--muted); font-size:.85rem; margin:-4px 0 10px; }
"""


def render(profile: Profile, record: CallRecord) -> str:
    sections = [
        _header(profile, record),
        _booking(profile, record.booking) if record.booking else "",
        _message(record),
        _details(record.booking),
        _timeline(record),
        _transcript(record),
    ]
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>{escape(profile.business)}</title><style>{STYLE}</style></head>"
        f"<body><main>{''.join(s for s in sections if s)}</main></body></html>"
    )


def _header(profile: Profile, record: CallRecord) -> str:
    outcome = record.outcome or Outcome.ABANDONED
    started = f"{record.started_at.astimezone():%a %b %d, %-I:%M %p}"
    meta = " · ".join(filter(None, [escape(record.caller_number), started, _duration(record)]))
    return (
        f"<h1>{escape(profile.business)}</h1>"
        f"<p class=meta>{meta}</p>"
        f'<span class="badge {outcome.value}">{_words(outcome.value)}</span>'
    )


def _booking(profile: Profile, booking: Booking) -> str:
    add_to_calendar = google_calendar_url(
        title=f"{booking.service} - {profile.business}",
        starts_at=booking.starts_at,
        ends_at=booking.ends_at,
        details=f"Booked by phone with {profile.business}.",
        location=booking.details.get("address", ""),
    )
    return (
        "<h2>Your appointment</h2>"
        "<div class=card>"
        f"<div class=what>{escape(booking.service)}</div>"
        f"<div class=when>{booking.starts_at:%A, %B %-d} at {fmt_time(booking.starts_at)}</div>"
        f'<a class=cta href="{escape(add_to_calendar)}">Add to Google Calendar</a>'
        "</div>"
    )


def _message(record: CallRecord) -> str:
    if record.message is None:
        return ""
    return (
        "<h2>Message taken</h2><div class=card>"
        f"<div class=what>{escape(record.message.name)}</div>"
        f"<div class=when>{escape(record.message.reason)}</div></div>"
    )


def _details(booking: Booking | None) -> str:
    if booking is None or not booking.details:
        return ""
    rows = "".join(
        f"<dt>{_words(key)}</dt><dd>{escape(value)}</dd>" for key, value in booking.details.items()
    )
    return f"<h2>Details you gave us</h2><dl>{rows}</dl>"


def _timeline(record: CallRecord) -> str:
    if not record.events:
        return ""
    rows = "".join(
        "<li>"
        f"<div class=what>{_words(event.type)}</div>"
        f"<div class=detail>{escape(event.summary)}</div>"
        "</li>"
        for event in record.events
    )
    return (
        "<h2>What happened</h2>"
        "<p class=note>Recorded automatically as the call ran.</p>"
        f"<ol class=timeline>{rows}</ol>"
    )


def _transcript(record: CallRecord) -> str:
    if not record.transcript:
        return ""
    rows = "".join(
        f'<div class="turn {escape(turn.role)}">'
        f"<div class=who>{_words(turn.role)}</div>"
        f"<div>{escape(turn.text)}</div></div>"
        for turn in record.transcript
    )
    return f"<h2>Transcript</h2>{rows}"


def _duration(record: CallRecord) -> str:
    if record.ended_at is None:
        return "in progress"
    seconds = int((record.ended_at - record.started_at).total_seconds())
    return f"{seconds // 60}:{seconds % 60:02d}"


def _words(slug: str) -> str:
    return escape(slug.replace("_", " ").capitalize())


def not_found() -> str:
    """One identical page for every failure: bad token, unknown call, malformed id.

    It must reveal nothing — not even that a call exists — or it becomes an oracle for
    guessing call ids.
    """
    return (
        "<!doctype html><html lang=en><head><meta charset=utf-8>"
        '<meta name=viewport content="width=device-width,initial-scale=1">'
        f"<title>Not found</title><style>{STYLE}</style></head>"
        "<body><main><h1>Not found</h1>"
        "<p class=meta>This link isn't valid. If it came from a text message, "
        "try opening it again from the original message.</p>"
        "</main></body></html>"
    )
