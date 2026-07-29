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
                              agent/worker.py  (LiveKit: VAD ▸ STT ▸ ? ▸ TTS)
                                          │  llm_node
                                          ▼
                              agent/graph.py   START ▸ model ▸ (tools ▸ model)* ▸ END
                                          │
                       ┌──────────────────┼──────────────────┐
                       ▼                  ▼                  ▼
              CalendarService        CallRecord          finish.py
              (fake | Google)      (the one shape)     text + persist
                                          │                  │
                                          ▼                  ▼
                                   store.py (SQLite) ◀── web/ (the linked page)
```

The same graph is driven by `scripts/chat.py` over stdin. **Two drivers, one brain** — what
you iterate on by typing is what answers the phone.

---

## 3. The brain (`agent/graph.py`)

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
than paper over that, the text driver keeps the same text-only history — the two paths are
then honestly comparable. The one real consequence is that the model can forget it already
booked, so `save_booking` confirms the existing appointment instead of creating a second.

---

## 4. Profiles (`profiles/`)

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

`profiles/` imports nothing from `agent/` except the tool functions themselves — the
description of a business stays independent of the machinery.

### Where per-business *behaviour* goes

Not in `Profile`. Booking policy lives behind `CalendarService`, chosen per profile by
`build_calendar(profile)`. Business hours already flow that way. When the restaurant needs
several reservations per slot where HVAC allows one, that is a second `CalendarService`
implementation — the Protocol and the factory already exist, and nothing above the service
layer changes.

**Known gap:** `save_booking` currently encodes "one booking per caller per call", which is
HVAC's rule, not the restaurant's. That decision belongs to the calendar too.

---

## 5. The shared shape (`models.py`)

`CallRecord` is produced by the tools and read by the store, the confirmation text and the
web page — one type, so those four never drift.

```python
class CallRecord(BaseModel):
    id: UUID
    profile_id: str
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

## 6. When a call ends (`finish.py`)

One place, called by both drivers, so they can't disagree about what a finished call means.

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
  characters — three SMS segments alone. The add-to-calendar button lives on the linked
  page instead, along with the transcript.
- **ASCII only.** A single em-dash or emoji flips the message from GSM-7 to UCS-2, cutting
  capacity from 160 characters per segment to 70.
- **Nothing sent without credentials.** Unset Telnyx config means the text is composed and
  recorded as `sms_skipped`. `+1 (xxx) 555-01xx` is refused outright — it's the reserved
  fictional range, and the dev REPL's default caller lives there.

---

## 7. Persistence and the page

**SQLite**, one file, no infrastructure — but a real file, because the worker and the web
server are separate processes. An in-memory store would leave every link in every text
pointing at nothing. The record is stored as JSON: `CallRecord` is already the one shared
shape and nothing queries inside it.

**`links.py`** signs each link with a truncated HMAC of the call id. 64 bits of secret on
top of a random UUID is far more than anyone will brute-force to read one appointment, and
it keeps the whole link inside a single SMS segment. No expiry, deliberately.

**`web/`** is FastAPI serving one server-rendered page, mobile-first because almost everyone
arrives from a text on a phone. No JavaScript, no build step. Every way of failing to
authorise — malformed id, missing token, wrong token, unknown call — returns **one
identical 404**, so the response can't be used to discover which call ids exist.

---

## 8. Voice (`agent/worker.py`)

`llm_node` is the entire integration: LiveKit's history in, the graph's spoken words out.
No tools are declared here.

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

---

## 9. Testing

`tests/` holds **17 tests that state the guarantees** — the happy path end to end, a taken
time being declined, never double-booking, reschedule and cancel, taking a message, a tool
failure becoming a question rather than dead air, the confirmation facts coming from the
record, and the signed link plus its uniform 404. Those are the ones to read.

`tests/ai_generated/` holds 105 more for coverage: date-parsing tables, the Google Calendar
adapter against a stub client, SQLite round-trips, URL encoding, schema introspection.

`tests/fakes.py::ScriptedModel` is how the graph runs with no network — it replays scripted
`AIMessage`s, so any path through the graph is deterministic. Tests drive tools **by name**,
which is why they doubled as proof that the tool-wiring refactor changed no behaviour.

An autouse fixture blanks the Telnyx credentials for every test. `settings` is a
module-level singleton loaded from `.env`, so on a machine with real credentials any test
reaching `send_sms` would post for real. The suite must be *incapable* of it.

---

## 10. Deployment

One image, two processes: the voice worker (dials out, no inbound ports) and the web page
(the only thing that needs to be reachable). They share a SQLite volume and must share
`RECEPTIONIST_LINK_SECRET`, or every link already texted 404s. Details in
[`../backend/deploy/README.md`](../backend/deploy/README.md).

The **DID → profile mapping is the SIP dispatch rule's metadata** — that JSON is the whole
routing table. Because the worker registers with an `agent_name`, dispatch is explicit:
joining a room does not summon it. That is what lets one worker serve several numbers as
different businesses.

---

## 11. Quality bar

`uv` · `ruff` · `mypy --strict` over `src` · `pytest`, all offline. Vendor boundaries
treated as opaque are listed with reasons in `pyproject.toml`. Python 3.12+.
