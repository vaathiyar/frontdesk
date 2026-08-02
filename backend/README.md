# AI Receptionist — Backend

A caller phones a small business. The agent answers, books / reschedules / cancels on the
same call, answers questions about the business, or takes a message — then texts the
caller a confirmation with a link to the transcript and an add-to-calendar button.

**One brain.** A LangGraph agent owns the prompt and the tools. The LiveKit voice worker
drives it on a real call, and the test suite drives the same compiled graph by text
(`tests/support/conversation.py`), so what the tests prove is what answers the phone.

```
START ─▶ model ─▶ (tools ─▶ model)* ─▶ END
```

That's the whole control flow, in `src/receptionist/worker/agent/graph.py`. Everything
business-specific lives in the prompt and the tools.

## Quickstart

```bash
uv sync
uv run pytest -q     # 171 tests, offline: no network, no API key, no database
```

The suite is the way to exercise the agent without telephony. Every guarantee it states
runs the real tools against an in-memory calendar, so a booking that "happened" actually
took a slot.

## Running it

| Command | What it does | Needs |
|---|---|---|
| `uv run pytest -q` | 171 offline tests | — |
| `uv run fastapi dev` | The JSON API the SPA reads | `RECEPTIONIST_DATABASE_URL` |
| `uv run agent.py dev` / `start` | The voice worker, against your LiveKit server | Google (key + JSON) + `LIVEKIT_*` |
| `uv run python deploy/sip/provision.py` | Point each DID at the right profile | `LIVEKIT_*` |
| `uv run alembic upgrade head` | Create/update the `calls` table | `RECEPTIONIST_DATABASE_URL` |

**Every call arrives over SIP.** The dispatch rule says which business a call is for, so
there is no local no-telephony mode and no default profile.

**The worker refuses to start on a bad config, rather than failing on a call.** Three
checks run before it registers: `RECEPTIONIST_CALENDAR_IDS` must name a Google Calendar for
*every* registered profile, `TELNYX_API_KEY` must be set, and `RECEPTIONIST_DATABASE_URL`
must be set. A missing calendar would otherwise surface with a caller on the line; the
other two are worse — they surface after the caller has hung up, as a log line nobody
reads. The web process checks the database URL in its lifespan for the same reason.

### Docker

```bash
docker compose up -d --build
```

Services from one image: a one-shot `migrate`, the voice `worker` (dials out, no inbound
ports), and `web`. They share a CockroachDB cluster rather than a volume — the worker
writes each call, and `web` serves the one a texted link refers to. The SPA is not here:
it is a separate origin, and this image serves JSON and never markup.

`docker-compose.yaml` sits here rather than in `deploy/` on purpose: Compose resolves the
build context against the project directory, which a platform sets for you, so a compose
file one level down builds correctly by hand and one directory too high on a deployment.

For credentials under Docker, set `GOOGLE_CREDENTIALS_JSON` — compose mounts no files. See
[`deploy/README.md`](deploy/README.md).

## How a call becomes a text

1. `worker/voice/session.py` answers, reads the profile from the SIP dispatch metadata and the
   caller's number from `sip.phoneNumber`.
2. Every turn runs the graph. Tools are the only way the agent changes anything, and each
   one records what it did on the `CallRecord`.
3. On hang-up, `worker/lifecycle.py` composes the text, sends it, and saves the call.
4. The text carries one short link, `{RECEPTIONIST_PUBLIC_BASE_URL}/c/{id}`. That is a
   route on the **SPA** (`frontend/`), which fetches `GET /api/calls/{id}` from this
   process and renders the record. Unauthenticated: the id is a random UUID and the link
   goes to the caller's own phone.

The confirmation text is split by what can be trusted with what: Gemini writes the opening
sentence or two and is *forbidden* from stating the date or time; the appointment facts and
the link are built from the record. If the model call fails, the facts go out alone.

## Environment

Local runs read `.env`; copy [`.env.example`](.env.example).

| Var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini — the reasoning model |
| `GOOGLE_CREDENTIALS_JSON` | Service-account key inline, on one line. Wins over the path |
| `GOOGLE_CREDENTIALS_FILE_PATH` | The same key as a file: Cloud STT/TTS + Calendar |
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | Your LiveKit server |
| `TELNYX_API_KEY` | Sends the confirmation text. **Required** — the worker won't start without it |
| `TELNYX_FROM_NUMBER` | Fallback sender, optional. Real calls send from the DID that was dialled. Must be E.164 if set |
| `RECEPTIONIST_CALENDAR_IDS` | JSON map `profile_id → Google Calendar ID`. **Required for every profile** — the worker won't start without them |
| `RECEPTIONIST_TIMEZONE` | Where all booking arithmetic happens |
| `RECEPTIONIST_DATABASE_URL` | **Required.** CockroachDB, pasted in as-is. Neither process starts without it |
| `RECEPTIONIST_PUBLIC_BASE_URL` | Goes into the text. Points at the **SPA**, and must be reachable from a phone |
| `RECEPTIONIST_CORS_ORIGINS` | Which origins the SPA may call the API from |

The two Google credentials are **not** interchangeable: Gemini uses the API key, Cloud
STT/TTS and Calendar use the service-account JSON. Voice needs both.

Model and voice parameters (model id, thinking level, STT/TTS voices) are code constants
in `worker/agent/graph.py` and `worker/voice/speech.py` — deliberately not env-configurable, because a
wrong value there is a broken call, not a preference.

## Add a profile

One module, one registry line. A profile is data plus the tools it picks:

```python
# src/receptionist/worker/profiles/dental.py
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

Then one line in `worker/profiles/__init__.py`. `book`'s parameters *are* the details that
profile collects — that signature is the schema the model sees. `tools` is the whole
capability list, so leaving a tool out is how you say this profile can't do that.

Registering it also makes it **required** in `RECEPTIONIST_CALENDAR_IDS`: the worker
checks every profile at startup, so a new one without a calendar stops the worker rather
than failing on its first call.

To answer a real number with it, add one SIP (trunk, dispatch-rule) pair — see
[`deploy/README.md`](deploy/README.md).

## Layout

Organised by **which of the two processes owns what**. They ship from one image and share
only `core/`. Four things at the top level, and three of them are a process or the seam
between them — if a module isn't in `core/`, exactly one process owns it.

```
agent.py            LiveKit worker entrypoint     (dev | start)
src/receptionist/
  core/             WHAT BOTH PROCESSES SPEAK
    models.py       CallRecord — the one shape, and the API's response model
    db/             CockroachDB over SQLAlchemy; the worker saves, the API reads
      engine.py     one pool per process, built on first use
      tables.py     the calls table: a JSONB record, plus the columns lifted out of it
      store.py      the CallStore seam, and its one implementation
  worker/           THE VOICE AGENT — `agent.py start`
    voice/          LiveKit
      session.py    the job entrypoint; llm_node is the whole graph integration
      speech.py     STT / TTS / VAD — the only place a speech vendor is named
    agent/          LangGraph
      graph.py      the two-node loop
      tools.py      what the agent can do, and save_booking
      prompt.py     the one system prompt
    booking/        service.py — the CalendarService seam, slot grid, startup check
                    google.py  — the one implementation
    messaging/      compose.py — what the confirmation text says
                    telnyx.py  — sending it
    profiles/       which businesses we answer as, and what each agent may do
    lib/            datetimes.py  phone.py  google_auth.py  links.py
                    no domain state; shared inside worker/ only
    lifecycle.py    what happens when a call ends — the spine, and the only
                    module at this level
  api/              THE WEB SERVICE — `fastapi run`
    app.py          the app, CORS, and the startup database check
    deps.py         the CallStore dependency
    routes/         health.py, calls.py — GET /api/calls/{id} is the whole API
migrations/         alembic; the calls table's schema history
  settings.py       the one place that reads the environment
tests/              21 tests that state the guarantees — read these
  support/          test doubles: ScriptedModel, the in-memory calendar and call store
  ai_generated/     147 more for coverage — not required reading
```

Every package's `__init__.py` says what belongs in it and why;
`src/receptionist/__init__.py` carries this map.

**The seam is narrow on purpose.** `core/` is two entries, and nothing under `api/`
imports `worker/` — a test enforces it. That is why
`CallRecord.business_name` is stamped at call start rather than looked up: fetching it
from the profile registry would drag 188 langchain/langgraph modules into the web process
to render one string.

## Quality

```bash
uv run ruff format --check . && uv run ruff check .
uv run mypy
uv run pytest -q
```

Requires Python 3.12+. `mypy --strict` over `src`; the vendor boundaries treated as opaque
are listed with reasons in `pyproject.toml`.
