# Backend Refactor Plan — for review

> **Status: implemented.** Kept as the record of what was decided and why — §10 lists the
> calls taken. For the design as it now stands, read [`lld.md`](./lld.md).
>
> **Goal:** readability for someone reading the whole codebase for the first time.
> **Constraint:** move and rename freely; change behaviour only where explicitly flagged
> in §7, and only with approval.

---

## 1. Principles

1. **The directory tree should tell the story of a call.** A reader who opens
   `src/receptionist/` should be able to guess what happens, in order, without opening a
   file.
2. **Separate policy from vendor.** What we decide (bookable hours, what the text says)
   should not live in the same module as how a vendor is called.
3. **One reason to change per package.** LangGraph churn shouldn't touch LiveKit files.
4. **Proportionate.** This is ~1,900 lines of application code. Seven packages is
   organisation; fifteen is bureaucracy. Every directory below earns its place by holding
   at least two files that belong together.
5. **Name things for what they are.** `when.py`, `finish.py`, `providers.py` are cute;
   they cost a reader a file-open each.

---

## 2. What's there now, and what each file does

**`src/receptionist/` — 1,927 lines across 20 modules**

| File | Lines | What it does | Verdict |
|---|---|---|---|
| `settings.py` | 48 | The one place that reads the environment | Keep, unmoved |
| `models.py` | 76 | `CallRecord`, `Booking`, `Message`, `Outcome`, `TranscriptTurn`, `CallEvent` — the shape every consumer reads | **Rename** — "models of what?" |
| `finish.py` | 68 | `finish_call()` — stamp, compose text, send, persist. The end-of-call orchestrator | **Rename** — sounds like a helper, is control flow |
| `store.py` | 67 | SQLite, record-as-JSON | Keep, unmoved |
| `phone.py` | 38 | E.164 normalisation at the SIP edge | **Move** — a primitive, not a peer of `models.py` |
| `links.py` | 62 | HMAC-signed call links + add-to-calendar URL | **Move** — same |
| `google_auth.py` | 98 | Which service-account credential, in what shape | **Move** — its only callers are in two other packages |
| `agent/graph.py` | 88 | The two-node LangGraph loop | Keep |
| `agent/prompt.py` | 62 | The one system prompt | Keep |
| `agent/tools.py` | 181 | The six tools + `CallContext` | Keep |
| `agent/worker.py` | 223 | LiveKit job entrypoint, `llm_node`, SIP attribute reading | **Move** — LiveKit, not LangGraph |
| `agent/providers.py` | 57 | STT / TTS / VAD construction | **Move + rename** — LiveKit, and "providers" of what? |
| `services/calendar.py` | 114 | `CalendarService` protocol, `Booked`, slot grid, `build_calendar`, `require_calendar_ids` | **Move** |
| `services/google_calendar.py` | 212 | The one implementation, against Calendar v3 | **Move** |
| `services/sms.py` | 111 | One POST to Telnyx, plus the refusal rules | **Move + rename** |
| `services/summary.py` | 107 | Composing the confirmation text (model writes prose, code writes facts) | **Move + rename** — not a "service"; it does no I/O of its own |
| `services/when.py` | 129 | "tomorrow at 10" → a datetime, and datetimes → speech | **Move + rename** — zero I/O, pure library |
| `profiles/profile.py` | 37 | The `Profile` dataclass | Keep |
| `profiles/hvac.py` `restaurant.py` `__init__.py` | 167 | Two businesses + the registry | Keep |
| `web/app.py` | 18 | FastAPI, health check only (post-checkpoint-1) | **Move + expand** |

**`tests/` — 2,254 lines.** 18 guarantee tests at top level, 142 coverage tests in
`ai_generated/`, plus three support modules (`fakes.py`, `fake_calendar.py`,
`conversation.py`) that are currently siblings of the tests themselves.

---

## 3. What's wrong with the current shape

**a. The package root is a junk drawer.** Seven loose modules sit side by side with no
shared theme and wildly different importance: `models.py` (the core contract everything
reads) is a peer of `phone.py` (a 38-line regex). A reader can't tell the spine from the
plumbing.

**b. `services/` conflates four different kinds of thing.** It holds a pure zero-I/O date
library (`when.py`), a protocol plus business policy (`calendar.py`), two real vendor
adapters (`google_calendar.py`, `sms.py`), and a text composer that calls an LLM
(`summary.py`). "Service" has stopped meaning anything.

**c. `agent/` mixes the brain with the phone line.** `graph`/`prompt`/`tools` are
LangGraph and change when the agent's behaviour changes. `worker`/`providers` are LiveKit
and change when telephony changes. They're 280 lines of vendor code hiding inside the
package named after the product's core idea.

**d. Names cost a file-open.** `when.py`, `finish.py`, `providers.py`, `summary.py`,
`store.py` — you have to open each to learn what it is.

**e. `google_auth.py` is orphaned.** It sits at root; its only two callers live in
`services/` and `agent/`.

**f. `web/` has no room for what's coming.** One module with a health check, and a
specced JSON API (`frontend_spec.md` §7) with three endpoints, response schemas, and a
token dependency that needs somewhere to go.

**g. Test support is mixed in with tests.** `fakes.py`, `fake_calendar.py` and
`conversation.py` look like test modules in a directory listing but contain no tests.

---

## 4. Proposed structure

```
src/receptionist/
│
│   ── the spine: what a call is, and what happens to it ──
├── settings.py            the one place that reads the environment
├── call.py                CallRecord & friends — the shape everything reads
├── lifecycle.py           finish_call() — stamp, text, persist
├── store.py               SQLite
│
│   ── the brain ──
├── agent/
│   ├── graph.py           the two-node LangGraph loop
│   ├── prompt.py          the one system prompt
│   └── tools.py           the six tools + CallContext
│
│   ── the phone line ──
├── voice/
│   ├── worker.py          LiveKit job entrypoint; llm_node is the integration
│   └── speech.py          STT / TTS / VAD
│
│   ── acting on the world ──
├── booking/
│   ├── service.py         CalendarService, Booked, the slot grid, the startup check
│   └── google.py          the one implementation
├── messaging/
│   ├── compose.py         what the confirmation text says
│   └── telnyx.py          sending it
│
│   ── who we're answering as ──
├── profiles/
│   ├── profile.py  hvac.py  restaurant.py
│   └── data/restaurant_menu.json
│
│   ── serving it back ──
├── api/
│   ├── app.py             FastAPI app + router wiring
│   ├── deps.py            Annotated dependency aliases
│   └── routes/health.py   (calls.py, stats.py land here next)
│
│   ── small, shared, dependency-light ──
└── shared/
    ├── datetimes.py       "tomorrow at 10" -> a datetime, and back into speech
    ├── phone.py           E.164
    ├── links.py           signed call links + add-to-calendar
    └── google_auth.py     which service-account credential, in what shape
```

Read top to bottom that says: *a call arrives over `voice/`, is handled by `agent/`, which
acts through `booking/`; `call.py` records it; `lifecycle.py` ends it using `messaging/`
and `store.py`; `api/` serves it back; `profiles/` says which business; `settings.py`
reads the env; `shared/` is plumbing.*

**Why `shared/` and not another root dump:** the four modules in it are the only ones with
no domain opinion — pure functions and credential resolution, imported from three or more
packages. Keeping the root to four files makes the spine visible.

---

## 5. Every move, in one table

| From | To | Why |
|---|---|---|
| `models.py` | `call.py` | One aggregate, named for it. `from receptionist.call import CallRecord` |
| `finish.py` | `lifecycle.py` | It is the end-of-call control flow, not a utility |
| `agent/worker.py` | `voice/worker.py` | LiveKit, not LangGraph |
| `agent/providers.py` | `voice/speech.py` | Names what it builds |
| `services/calendar.py` | `booking/service.py` | Policy + the seam |
| `services/google_calendar.py` | `booking/google.py` | Vendor adapter behind that seam |
| `services/sms.py` | `messaging/telnyx.py` | Names the vendor, mirrors `booking/google.py` |
| `services/summary.py` | `messaging/compose.py` | It composes; it isn't a service |
| `services/when.py` | `shared/datetimes.py` | Pure library, plainly named |
| `phone.py` | `shared/phone.py` | Primitive |
| `links.py` | `shared/links.py` | Primitive |
| `google_auth.py` | `shared/google_auth.py` | Shared by `booking/` and `voice/` |
| `web/app.py` | `api/app.py` + `api/routes/health.py` | Room for the JSON API |
| `profiles/restaurant_menu.json` | `profiles/data/restaurant_menu.json` | Data beside data |
| `settings.py` `store.py` `profiles/*` `agent/{graph,prompt,tools}.py` | unchanged | Already right |

**Import churn:** every module's imports change, but nothing else does. Verified by the
160 tests, which are behaviour-level and don't assert on module paths (except imports).

---

## 6. The API layer

Only `health.py` exists now, but the structure is what `frontend_spec.md` §7 needs, so
adding `/api/calls` is dropping in one file rather than restructuring.

```python
# api/app.py
app = FastAPI(title="Receptionist", docs_url=None, redoc_url=None)
app.include_router(health.router)
# app.include_router(calls.router)   <- next

# api/routes/health.py
router = APIRouter(tags=["health"])

@router.get("/healthz")
async def healthz() -> Health: ...
```

Conventions to follow when the API lands (from the FastAPI skill):

- **Router-level `prefix`, `tags`, `dependencies`** declared on the `APIRouter`, not in
  `include_router()`. `/api/calls` gets `APIRouter(prefix="/api/calls", tags=["calls"])`.
- **`Annotated[...]` everywhere** for params and dependencies, with reusable aliases in
  `api/deps.py` — e.g. `StoreDep = Annotated[CallStore, Depends(get_store)]`. This
  replaces the `@lru_cache def store()` that `web/app.py` used to carry.
- **Return types, not `response_model`**, unless the public schema differs from what's
  returned — which it will for `CallListItem` (a trimmed record) and `CallDetail`
  (record + `business_name`). Those get explicit response models in `api/schemas/`.
- **`def` not `async def`** for anything doing blocking work. `CallStore` is already
  `asyncio.to_thread`-wrapped, so its routes stay `async`.
- **No `ORJSONResponse`** (deprecated); Pydantic serialises on the Rust side.

**Optional, needs a nod:** replace `serve.py` (22 lines) with the `fastapi` CLI —
`fastapi run` in the container, `fastapi dev` locally, entrypoint declared in
`pyproject.toml` under `[tool.fastapi]`. Costs a dependency change (`fastapi` →
`fastapi[standard]`) and a compose `command:` edit. See §9.

---

## 7. Logic changes — each needs approval

Nothing here changes behaviour. All four are "split a function", the kind you said was
fine. Listed separately so you can approve or veto individually.

| # | Where | Change | Why |
|---|---|---|---|
| 1 | `agent/tools.py` | Extract the duplicated "*X on Y isn't available. Open on Y: …*" construction from `save_booking` and `reschedule` into one helper | The same 4-line message is built twice; they must not drift |
| 2 | `booking/google.py` | Extract the repeated `await asyncio.to_thread(lambda: …execute())` into one `_execute()` | Five copies of the same lambda-wrapping obscure what each call actually does |
| 3 | `lifecycle.py` | Split the SMS try/except block out of `finish_call` into `_notify(record, text)` | `finish_call` currently does four things in 30 lines; the ordering comment applies to the whole, the error handling to one part |
| 4 | `voice/worker.py` | Extract the three `@session.on` handlers out of `entrypoint` into a small `_wire_session(...)` | `entrypoint` is 50 lines with three nested closures |

**Explicitly not doing:** the `save_booking` "one booking per caller per call" rule that
`lld.md` §4 flags as belonging to the calendar. That's a real behaviour change and a
product decision, not a refactor.

---

## 8. Tests

Mirror the source layout, and separate helpers from tests:

```
tests/
├── support/              (no tests in here)
│   ├── fakes.py          ScriptedModel
│   ├── fake_calendar.py  the in-memory calendar
│   └── conversation.py   drives the graph by text
├── conftest.py
├── test_call_flow.py         the guarantees — read these first
├── test_confirmation.py
├── test_voice.py
├── test_calendar_config.py
└── ai_generated/         renamed to follow the modules they cover:
                          test_providers.py       -> test_speech.py
                          test_sms.py             -> test_messaging.py
                          test_google_calendar.py -> test_booking_google.py
                          test_calendar.py        -> test_booking.py
                                                   + test_datetimes.py
                          (others unchanged)
```

`test_calendar.py` was **split** rather than just renamed: half of it tested the calendar
and half tested date parsing, which now live in different packages
(`booking/service.py` and `shared/datetimes.py`), so the tests follow.

---

## 9. Execution order

Each step ends green (`pytest` + `ruff` + `mypy --strict`), so any step can be the place
you stop and review.

1. `shared/` — move the four primitives, fix imports.
2. `voice/` — split LiveKit out of `agent/`.
3. `booking/` + `messaging/` — dissolve `services/`.
4. `call.py` + `lifecycle.py` — the two root renames.
5. `api/` — restructure the web layer into routers.
6. Tests — `support/`, renames.
7. **Docs rewrite.** `lld.md` is now wrong in four places (fake calendar, "two drivers",
   the server-rendered page, the layout tree) and gets rewritten against the new
   structure. `frontend_spec.md` / `frontend_plan.md` get their stale backend paths fixed
   (they already reference `core/models.py` and `core/links.py`, which never existed).
   Both READMEs get their layout sections updated.

---

## 10. Decisions taken

| Question | Decision |
|---|---|
| Scope | **Structure only.** The JSON API (`frontend_spec.md` §7) is separate work; this pass ships `api/` with the health router alone |
| `models.py` → `call.py` | **Rejected** — `models.py` stays. §5's first row does not apply |
| `shared/` package | **Adopted** as proposed |
| `serve.py` → `fastapi` CLI | **Adopted** — `serve.py` deleted, `fastapi[standard]`, entrypoint in `pyproject.toml` |
| §7 split 1 — `tools.py` duplicate message | **Adopted** |
| §7 split 2 — `google.py` `to_thread` lambdas | **Rejected** — left as-is |
| §7 split 3 — `lifecycle.py` SMS block | **Adopted** |
| §7 split 4 — `worker.py` session handlers | **Adopted** |

---

## 11. Addendum — the second structural pass

The layout in §4 shipped, then a follow-up review asked the question §4 had not: *if the
tree is the story of a call, which parts does the **web process** actually need?*

Measuring the transitive import closure of each process answered it:

| | modules |
|---|---|
| Worker only | 8 — `voice/*`, `agent/graph`, `agent/prompt`, `messaging/*`, `lifecycle`, `phone` |
| Shared | 13 — but 9 of those only via a single contaminating edge (below) |
| API only | 3 |

Two findings:

1. **`lifecycle.py` is worker-only** — the API never ends a call — so root was the wrong
   place for it. `store.py` and `models.py` genuinely are shared.
2. **`shared/` was misnamed.** Only `links.py` was truly shared. `datetimes.py` and
   `google_auth.py` appeared shared purely because `profiles/hvac.py` imports
   `agent/tools.py` for its tool tuple — so fetching a `business_name` for the API pulled
   in **188 langchain/langgraph modules and ~600 ms of boot**.

Fixing (2) was the precondition for a clean split. `CallRecord.business_name` is now
stamped at call start, so the web process imports no agent code at all — enforced by
`test_the_web_process_does_not_import_the_agent`. It is also the better record: a call
shows the business name the caller was actually told.

The tree is now organised by **process ownership** rather than by call sequence:

```
core/        models.py  store.py  links.py        ← the entire seam
worker/      voice/ agent/ booking/ messaging/ lifecycle.py + 3 local helpers
api/         app.py  routes/
profiles/    worker-only code, top level because it is product configuration
settings.py
```

`voice/worker.py` became `worker/voice/session.py` — `worker.voice.worker` read badly, and
the module's real subject is the `AgentSession`.

### 11a. Where the three primitives ended up

A follow-up review asked why `datetimes.py`, `phone.py` and `google_auth.py` were dangling
at `worker/` root, and proposed folding `phone.py` into `messaging/` and `lifecycle.py`
into `voice/`. The importer data said otherwise:

| Module | Imported by | |
|---|---|---|
| `phone.py` | `voice/session` (`to_e164`), `messaging/telnyx` (`E164`) | `messaging/` would invert a dependency — voice normalises at the SIP edge, messaging only borrows the regex |
| `datetimes.py` | `agent/prompt`, `agent/tools`, `booking/service`, `booking/google`, `messaging/compose` | 3 of 4 packages; no owner |
| `google_auth.py` | `booking/google`, `voice/speech` | the two Google-touching modules |
| `lifecycle.py` | `voice/session` only — but imports **nothing** from `voice/` | it pulls `messaging/*`, `core/models`, `core/store`, `profiles` |

So the three primitives went into **`worker/lib/`** — bar for entry: no domain state, no
knowledge of a `CallRecord` or a `Profile`. `lifecycle.py` stayed at `worker/` root, and is
now the only module at that level, which reads as the spine rather than as leftovers.
Moving it under `voice/` would have put SMS composition and persistence orchestration
inside the package defined as "everything LiveKit and nothing else".

### 11b. `profiles/` moved under `worker/`

§11 left `profiles/` at the top level on the argument that it is product configuration
rather than process machinery. That was the weaker half of the reasoning: once
`business_name` moved onto `CallRecord`, every importer of `profiles/` in `src/` was under
`worker/`, so a top-level package contradicted the one rule the tree is built on — *if a
module is not in `core/`, exactly one process owns it*.

It is now `worker/profiles/`. The top level is four entries: two processes, the seam, and
`settings.py`.

### 11c. `links.py` moved to `worker/lib/`

Measured: `core/` had **no API importers at all** — `api/` is still a health check, so
`models.py`, `store.py` and `links.py` were equally worker-only by the import graph. `core/`
is declared from the contract in `frontend_spec.md` §7, not measured.

Decision was to keep `models.py` and `store.py` there — the record shape and the data layer
are structurally shared — and move `links.py` out, since only `messaging/compose.py` uses it
(`call_url`) today. It is now `worker/lib/links.py`, which it qualifies for: it imports no
domain type, only `settings`.

**Known future move.** `verify()` is the web service's half — `GET /api/calls/{id}?t=`
(§7.3) — and it *is* `compare_digest(sign(...), token)`, so it cannot be split from `sign`.
When that endpoint lands, this module returns to `core/`. Re-implementing the scheme on the
API side instead is the one shortcut that could break the signing property; the module
docstring says so.
