# AI Receptionist — Backend

A caller phones a small business. The agent answers, books / reschedules / cancels on the
same call, answers questions about the business, or takes a message — then texts the
caller a confirmation with a link to the transcript and an add-to-calendar button.

**One brain, two drivers.** A LangGraph agent owns the prompt and the tools. A text REPL
and the LiveKit voice worker both drive that same graph, so what you iterate on by typing
is what answers the phone.

```
START ─▶ model ─▶ (tools ─▶ model)* ─▶ END
```

That's the whole control flow, in `src/receptionist/agent/graph.py`. Everything
business-specific lives in the prompt and the tools.

## Quickstart

```bash
uv sync
uv run pytest -q                                    # no network, no API key

export GOOGLE_API_KEY=...                           # or put it in .env
uv run python scripts/chat.py hvac --fake-calendar   # also: restaurant
```

Type as the caller; `quit` ends the call and prints the resulting `CallRecord` plus the
confirmation text that would be sent:

```
caller> my furnace quit, can someone come tomorrow morning?
agent>  We can help with that. Tomorrow we have 9:00 AM or 10:00 AM open. What's your
        name and address?
...
────────────────────────────────────────────────────────────────
  outcome: booked
  booking: furnace repair @ Thu Jul 30, 9:00 AM  (evt_3c409385)
  details: name='Sam Lee', address='12 Oak St, Burnaby', issue='no heat'
  decision timeline:
    • availability_checked: Thursday, July 30: 9:00 AM, 10:00 AM, ...
    • booking_created: furnace repair on Thursday, July 30 at 9:00 AM
    • sms_skipped: no Telnyx credentials for this number
```

The fake calendar seeds **tomorrow's first opening as busy**, so ask for it and watch the
agent decline and offer real alternatives — it never claims a booking the tool didn't make.

## Running it

| Command | What it does | Needs |
|---|---|---|
| `uv run pytest -q` | 122 offline tests | — |
| `uv run python scripts/chat.py hvac` | Text REPL — type as the caller | `GOOGLE_API_KEY` |
| `uv run python serve.py` | The call-detail page texts link to | — |
| `uv run agent.py console --text` | Whole voice pipeline, typed | Google (key + JSON) |
| `uv run agent.py console` | Local mic and speakers | Google (key + JSON) |
| `uv run agent.py dev` / `start` | Against your LiveKit server | Google + `LIVEKIT_*` |

**`--fake-calendar` matters.** With `RECEPTIONIST_CALENDAR_IDS` set, the REPL books into
that *real* Google Calendar; the flag keeps bookings in memory. The REPL prints which
backend it is using on startup. Note `agent.py` has no such flag — a console call that
reaches `book` will create a real event.

**Local voice on WSL2** works through WSLg's PulseAudio. Wear headphones: the Python
console has no echo cancellation, so on speakers the agent interrupts itself.
`uv run agent.py console --list-devices`, then `--input-device pulse` if it picks wrong.

### Docker

```bash
SA_JSON=/abs/path/to/service-account.json \
  docker compose -f deploy/docker-compose.yml up -d --build
```

Two services from one image: the voice `worker` (dials out, no inbound ports) and `web`
(serves the page). They share a SQLite volume, because the worker writes each call and the
web process resolves the link that was texted about it. See
[`deploy/README.md`](deploy/README.md).

## How a call becomes a text

1. `agent/worker.py` answers, reads the profile from the SIP dispatch metadata and the
   caller's number from `sip.phoneNumber`.
2. Every turn runs the graph. Tools are the only way the agent changes anything, and each
   one records what it did on the `CallRecord`.
3. On hang-up, `finish.py` composes the text, sends it, and saves the call.
4. The text carries one short link. `web/page.py` renders the transcript, the decision
   timeline, and an **Add to Google Calendar** button.

The confirmation text is split by what can be trusted with what: Gemini writes the opening
sentence or two and is *forbidden* from stating the date or time; the appointment facts and
the link are rendered from the record. If the model call fails, the facts go out alone.

## Environment

Local runs read `.env`; copy [`.env.example`](.env.example).

| Var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini — the reasoning model |
| `GOOGLE_CREDENTIALS_FILE_PATH` | Service-account JSON: Cloud STT/TTS + Calendar |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Your LiveKit server |
| `TELNYX_API_KEY` / `TELNYX_FROM_NUMBER` | The confirmation text. Unset ⇒ printed, not sent |
| `RECEPTIONIST_CALENDAR_IDS` | JSON map `profile_id → Google Calendar ID`; omitted ⇒ fake |
| `RECEPTIONIST_TIMEZONE` | Where all booking arithmetic happens |
| `RECEPTIONIST_PUBLIC_BASE_URL` | Goes into the text, so it must be reachable from a phone |
| `RECEPTIONIST_LINK_SECRET` | Signs those links — worker and web must share it |
| `RECEPTIONIST_DATABASE_PATH` | The SQLite file both processes use |
| `RECEPTIONIST_PROFILE` | Which profile `agent.py console` answers as |

The two Google credentials are **not** interchangeable: Gemini uses the API key, Cloud
STT/TTS and Calendar use the service-account JSON. Voice needs both.

Model and voice parameters (model id, thinking level, STT/TTS voices) are code constants
in `agent/graph.py` and `agent/providers.py` — deliberately not env-configurable, because a
wrong value there is a broken call, not a preference.

## Add a profile

One module, one registry line. A profile is data plus the tools it picks:

```python
# src/receptionist/profiles/dental.py
@tool(parse_docstring=True)
async def book(
    service: str, day: str, time: str, name: str, reason: str, runtime: ToolRuntime[CallContext]
) -> str:
    """Book an appointment. ...

    Args:
        ...
    """
    return await save_booking(
        runtime, service=service, day=day, time=time, details={"name": name, "reason": reason}
    )


DENTAL = Profile(
    id="dental",
    business="Riverside Dental",
    greeting="Thanks for calling Riverside Dental!",
    does="You book cleanings and checkups. ...",
    knowledge="Hours are ...",
    tools=(check_availability, book, reschedule, cancel, take_message, end_call),
    opens=9,
    closes=17,
)
```

Then one line in `profiles/__init__.py`. `book`'s parameters *are* the details that
profile collects — that signature is the schema the model sees. `tools` is the whole
capability list, so leaving a tool out is how you say this profile can't do that.

To answer a real number with it, add one SIP (trunk, dispatch-rule) pair — see
[`deploy/README.md`](deploy/README.md).

## Layout

```
agent.py            LiveKit voice worker      (console | dev | start)
serve.py            the call-detail web page
scripts/chat.py     the text REPL
src/receptionist/
  agent/
    graph.py        THE BRAIN — the two-node graph and the text driver
    tools.py        what the agent can do, and save_booking
    prompt.py       the one system prompt
    worker.py       LiveKit entrypoint; llm_node is the whole integration
    providers.py    STT / TTS / VAD — the only place a speech vendor is named
  profiles/         Profile + hvac + restaurant + registry
  services/
    calendar.py     CalendarService protocol + the in-memory fake
    google_calendar.py
    when.py         turning what a caller said about time into datetimes
    sms.py          Telnyx — one POST
    summary.py      composing the confirmation text
  web/              app.py (routes) + page.py (server-rendered HTML)
  models.py         CallRecord — the one shape everything reads
  store.py          SQLite
  links.py          signed call links + add-to-calendar links
  finish.py         everything that happens when a call ends
  settings.py
tests/              17 tests that state the guarantees — read these
  ai_generated/     105 more for coverage — not required reading
```

## Quality

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest -q
```

Requires Python 3.12+. `mypy --strict` over `src`; the vendor boundaries treated as opaque
are listed with reasons in `pyproject.toml`.
