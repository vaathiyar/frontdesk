# AI Receptionist — Low-Level Design

> Companion to [`poc_requirements_p0.md`](./poc_requirements_p0.md). This describes what
> is **built**, not what is planned. It is a proof of concept for demos, so the design is
> trimmed to the path a caller actually walks.

---

## 1. What it does

A caller phones a small business. The agent answers, and can:

| | |
|---|---|
| **Book** | check availability, then create the appointment |
| **Reschedule / cancel** | found by the caller's own number, no reference codes |
| **Answer questions** | hours, pricing, menu — straight from the prompt |
| **Take a message** | anything off-script, or a request for a person |
| **Hang up** | once the caller's business is done |

Then it texts the caller a confirmation containing a link to the transcript and an
add-to-calendar button.

Two profiles ship: **HVAC** ("Helpdesk Heating and Cooling") and **Restaurant**
("Helpdesk Kitchen"). Deliberately deferred: urgency tiers, warm transfer to a human,
call recording, and a dashboard.

---

## 2. Shape of the thing

```
 caller ─dials DID─▶ LiveKit ─dispatch {profile_id}─▶ agent job
                                          │
                                          ▼
                              worker/voice/session.py (LiveKit: VAD ▸ STT ▸ ? ▸ TTS)
                                          │  llm_node
                                          ▼
                        worker/agent/graph.py  START ▸ model ▸ (tools ▸ model)* ▸ END
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
                 worker/booking/     core/models.py    worker/lifecycle.py
                    (Google)       CallRecord — the     text, then persist
                                       one shape
                                          │                  │
                                          ▼                  ▼
                                core/store.py (SQLite) ◀── api/ (the JSON the SPA reads)
```

The suite drives the same compiled graph by text (`tests/support/conversation.py`), so
what the tests prove is what answers the phone.

### Two processes, one narrow seam

The tree is organised by **which process owns what**, because the two ship from one image
but share almost nothing:

```
worker/      the voice agent   `agent.py start`   voice/ agent/ booking/ messaging/
                                                   profiles/ lib/ lifecycle.py
api/         the web service   `fastapi run`      serves finished calls back
core/        what both speak                      models.py · store.py
settings.py  the one place that reads the environment
```

**`core/` is deliberately two modules.** Everything the worker needs beyond them —
LangGraph, LiveKit, Google Calendar, Telnyx, date parsing, E.164 normalisation — lives
under `worker/` and is invisible to the web service.

Four things at the top level, and three of them are a process or the seam between them:
if a module is not in `core/`, exactly one process owns it. `profiles/` sits under
`worker/` for that reason — a profile carries its agent's tool tuple, so nothing outside
the worker can touch it.

Inside `worker/`, the same rule applies one level down. `voice/`, `agent/`, `booking/` and
`messaging/` each own a vendor or a decision; `lib/` holds the three primitives two or
three of them share (time, phone numbers, Google credentials), with the bar for living
there being *no domain state* — nothing in it knows what a `CallRecord` or a `Profile` is.
`lifecycle.py` is the only loose module, and deliberately so: it is the spine that
coordinates the rest once a call ends.

One thing nearly broke that: `business_name`. The API needs it on every row, and looking
it up meant importing the profile registry — but a profile carries its agent's tool tuple, so that
one string costs **188 langchain/langgraph modules and ~600 ms of boot**. The worker
stamps `CallRecord.business_name` at call start instead, which also makes the record a
better historical artifact: it shows the name the caller was actually told. A test
(`tests/ai_generated/test_api.py`) asserts the web process imports none of the agent.

Every package's `__init__.py` says what belongs in it and why.

---

## 3. The brain (`worker/agent/graph.py`)

A hand-written two-node graph, not a prebuilt agent:

```python
builder.add_node(MODEL, call_model)
builder.add_node(TOOLS, ToolNode(tools, handle_tool_errors=explain_to_model))
builder.add_edge(START, MODEL)
builder.add_conditional_edges(MODEL, route_from_model)
builder.add_edge(TOOLS, MODEL)
```

Explicit over `create_agent` because reaching parity costs **zero** middleware: a dynamic
prompt is one inline line, `handle_tool_errors=` restores tool-error recovery, and
`recursion_limit` caps a stuck loop. `create_react_agent` is already deprecated; these
primitives are not.

Two things that are easy to get wrong:

- **`recursion_limit` must be passed explicitly.** LangGraph's default is 10007 — that is
  effectively no cap. `RECURSION_LIMIT = 2 * MAX_TOOL_ROUNDS + 1`, because it counts node
  executions, not tool rounds.
- **`route_from_model`'s `Literal["tools", "__end__"]` annotation is load-bearing.**
  LangGraph reconstructs the routing map from it and validates the target at compile time.
  Without it, a wrong node name fails *silently at runtime* — the branch write is dropped
  with a log warning and the run halts.

### Tools are the safety boundary

The model changes the world only by calling a tool, and each one validates before acting
and records what it did. `explain_to_model` turns a `ValueError` — "I couldn't understand
what the caller said" — into a tool result the model can recover from, because a raised
exception aborts the turn, and on a phone call that is dead air. Anything else propagates,
because it's a bug.

The calendar enforces the key guarantee in code, not in the prompt: `create_event` refuses
a time that isn't open, so the agent cannot double-book even if the model skips checking.

### History is text-only, on purpose

LiveKit replays only spoken turns, so the graph never sees its own prior tool calls. Rather
than paper over that, the suite's text driver keeps the same text-only history, so what a
test proves is honestly comparable to a real call. The one real consequence is that the
model can forget it already booked, so `save_booking` confirms the existing appointment
instead of creating a second.

---

## 4. Profiles (`worker/profiles/`)

A profile is **data plus the tools it picks**:

```python
HVAC = Profile(
    id="hvac",
    business="Helpdesk Heating and Cooling",
    greeting="Thanks for calling Helpdesk Heating and Cooling. How can I help?",
    does=...,          # what this business does -> system prompt
    knowledge=...,     # facts the agent may state
    tools=(check_availability, book, reschedule, cancel, take_message, end_call),
    opens=8, closes=18,
)
```

Not a class hierarchy. The thing that varies most — `book`'s parameters — is a *signature*,
because that signature is the schema the model sees (HVAC needs a service address, a table
needs a party size). A subclass assigning a differently-shaped function to the same name
isn't an override, so inheritance would buy nothing here.

One list per profile, so a single file tells you everything that agent can do, and leaving
a tool out is how you say this profile can't do that. Two guard tests hold the line: every
profile must be able to offer times, book and take a message, and none may list a tool name
twice (`ToolNode` keys by name, so a duplicate would silently shadow).

`worker/profiles/` imports nothing from `worker/agent/` except the tool functions themselves — the
description of a business stays independent of the machinery.

### Where per-business *behaviour* goes

Not in `Profile`. Booking policy lives behind `CalendarService`, chosen per profile by
`build_calendar(profile)`. Business hours already flow that way. When the restaurant needs
several reservations per slot where HVAC allows one, that is a second `CalendarService`
implementation — the Protocol and the factory already exist, and nothing above `booking/`
changes.

A profile with no calendar in `RECEPTIONIST_CALENDAR_IDS` stops the worker at startup
(`require_calendar_ids`). There is no in-memory fallback in production: discovering a
missing calendar with a caller on the line is the failure this exists to prevent.

**Known gap:** `save_booking` currently encodes "one booking per caller per call", which is
HVAC's rule, not the restaurant's. That decision belongs to the calendar too.

---

## 5. The shared shape (`core/models.py`)

`CallRecord` is produced by the tools and read by the store, the confirmation text and the
web page — one type, so those four never drift.

```python
class CallRecord(BaseModel):
    id: UUID
    profile_id: str
    business_name: str          # stamped at call start; keeps profiles out of the API
    caller_number: str          # from the call itself; never asked for
    started_at / ended_at
    outcome: Outcome | None     # booked | rescheduled | cancelled | answered
                                # | message_taken | abandoned
    booking: Booking | None     # real datetimes, not strings
    message: Message | None
    transcript: list[TranscriptTurn]
    events: list[CallEvent]     # the decision timeline
```

`events` is emitted by **code**, never narrated by the model. That is what makes it usable
as evidence of what actually happened, as opposed to what the agent said happened.

---

## 6. When a call ends (`worker/lifecycle.py`)

One place, called by the worker on hang-up and by the suite, so what "finished" means is
stated once.

1. Stamp `ended_at`; infer the outcome if no tool set one (a caller who spoke and was
   answered is `ANSWERED`, not `ABANDONED` — recording otherwise would misreport the call).
2. Compose and send the text; record whether it went.
3. Save. **A failed text must never cost us the record.**

### The confirmation text

Split by what can be trusted with what. Gemini writes the opening sentence or two and is
explicitly **forbidden from stating the date or time**; the appointment facts and the link
are rendered from the record. A hallucinated time in a message going out under the
business's name is the one error that costs someone a morning. If the model call fails, the
facts go out alone.

Other decisions worth knowing:

- **One short link, not a calendar attachment.** A raw Google Calendar URL is 200–419
  characters — three SMS segments alone. The add-to-calendar button belongs on the linked
  page instead, along with the transcript.
- **ASCII only.** A single em-dash or emoji flips the message from GSM-7 to UCS-2, cutting
  capacity from 160 characters per segment to 70.
- **Credentials are a startup concern, not a per-call one.** `TELNYX_API_KEY` is checked
  by `require_credentials()` before the worker registers, because a text that never goes
  out is only ever a log line — and by the time one appears, the caller has hung up. What
  stays per-call is about the call: a withheld number, or `+1 (xxx) 555-01xx`, refused
  outright as the reserved fictional range the suite's default caller lives in.

---

## 7. Persistence and the link

**SQLite**, one file, no infrastructure — but a real file, because the worker and the web
server are separate processes. An in-memory store would leave every link in every text
pointing at nothing. The record is stored as JSON: `CallRecord` is already the one shared
shape and nothing queries inside it.

**`worker/lib/links.py`** signs each link with a truncated HMAC of the call id. 64 bits of
secret on top of a random UUID is far more than anyone will brute-force to read one
appointment, and it keeps the whole link inside a single SMS segment. No expiry,
deliberately.

**`api/` is a health check and nothing else right now.** The server-rendered page that used
to resolve these links has been retired, so a texted link 404s until the JSON API in
[`frontend_spec.md`](./frontend_spec.md) §7 lands as `api/routes/calls.py`. Nothing about
the record or the signing changed, so the link starts working the moment it does.

One property that has to survive that move: every way of failing to authorise — malformed
id, missing token, wrong token, unknown call — must return **one identical 404**, so the
response can't be used to discover which call ids exist.

---

## 8. Voice (`worker/voice/session.py`)

`llm_node` is the entire integration: LiveKit's history in, the graph's spoken words out.
No tools are declared here. `voice/` is kept apart from `agent/` because the two change for
different reasons — one when telephony changes, the other when the receptionist should
behave differently.

Filtering that stream is the whole reason for overriding it. Tool results travel it
alongside the words to speak, so `livekit-plugins-langchain`'s `LLMAdapter` left at its
defaults reads `"Open on Monday: 9:00 AM, 10:00 AM..."` aloud before the actual answer. The
adapter is still passed as `llm=` because LiveKit silently skips the caller's turn when
that is `None`.

The filter matches `AIMessage`, not `AIMessageChunk`: only a streaming model emits chunks,
and matching the chunk type left a non-streaming model's caller listening to silence.
`ToolMessage` is not an `AIMessage`, so it stays out either way.

Two more hard-won details:

- **Plugins must be imported at module scope.** They register themselves on import, and
  registration has to happen on the main thread; deferring it into the builders crashed
  every call with `RuntimeError: Plugins must be registered on the main thread`.
- **`end_call` only marks the call over.** The room closes once the agent has stopped
  speaking, because cutting the line mid-goodbye is worse than a caller waiting a beat.
- **No local no-telephony mode.** A job whose dispatch metadata names no profile is
  refused, not answered as a guessed business.

---

## 9. Testing

`tests/` holds **21 tests that state the guarantees** — the happy path end to end, a taken
time being declined, never double-booking, reschedule and cancel, taking a message, a tool
failure becoming a question rather than dead air, the confirmation facts coming from the
record, and a profile without a calendar stopping the worker. Those are the ones to read.

`tests/ai_generated/` holds 145 more for coverage: date-parsing tables, the Google Calendar
adapter against a stub client, SQLite round-trips, URL encoding, schema introspection.

`tests/support/` holds the doubles, and none of them ship:

- **`ScriptedModel`** replays scripted `AIMessage`s, so any path through the graph is
  deterministic with no network and no API key. Tests drive tools **by name**, which is why
  they doubled as proof that the tool-wiring refactor changed no behaviour.
- **`FakeCalendarService`** is an in-memory calendar built on the same `slot_grid` and the
  same profile hours as the real one. It lives in the suite precisely because production
  has no fallback — see §4.
- **`Conversation`** drives the compiled graph by text, which is how the suite exercises a
  whole call without LiveKit.

An autouse fixture blanks the Telnyx credentials for every test, and another blanks the
Google ones. `settings` is a module-level singleton loaded from `.env`, so on a machine with
real credentials any test reaching `send_sms` would post for real. The suite must be
*incapable* of it.

---

## 10. Deployment

One image, two processes: the voice worker (`agent.py start`, dials out, no inbound ports)
and the web process (`fastapi run`, the only thing that needs to be reachable). They share
a SQLite volume and must share `RECEPTIONIST_LINK_SECRET`, or every link already texted
404s. Details in
[`../backend/deploy/README.md`](../backend/deploy/README.md).

The **DID → profile mapping is the SIP dispatch rule's metadata** — that JSON is the whole
routing table. Because the worker registers with an `agent_name`, dispatch is explicit:
joining a room does not summon it. That is what lets one worker serve several numbers as
different businesses.

---

## 11. Quality bar

`uv` · `ruff` · `mypy --strict` over `src` · `pytest`, all offline. Vendor boundaries
treated as opaque are listed with reasons in `pyproject.toml`. Python 3.12+.
