# AI Receptionist — Low-Level Design (PoC)

> Companion to [`poc_requirements_p0.md`](./poc_requirements_p0.md). This is a **proof-of-concept for demos**, not a production system. The design is deliberately trimmed to the path a tester will actually walk, and extension is **class-based** (subclass a base `Receptionist`), not config-file-driven.

---

## 1. Scope — what the PoC does, and what it deliberately doesn't

Each profile supports the **1–2 things a caller is most likely to try**:

| Profile | Primary (hero) | Secondary |
|---|---|---|
| **HVAC** — Helpdesk Heating and Cooling | Book a service visit | Answer questions (hours, service area, $119 call fee) |
| **Restaurant** — Helpdesk Kitchen | Make a table reservation | Answer menu / hours questions (from its own `restaurant_menu.json`) |

The shared shape is **Book/Reserve + Answer-a-question**, plus **reschedule/cancel an existing booking** (found by the caller's own number) and a thin **take-a-message** fallback for anything off-script.

**Deliberately deferred** (out of scope for the demo — easy to add back later via a subclass hook, see §9):
- A third vertical — the **Auto / automotive** profile (Helpdesk Auto Services) — parked for now; it drops back in as one more `Receptionist` subclass + a one-line factory entry when we want it (see §9).
- Urgency detection & tiers (gas/CO safety escalation) — a tester won't exercise it; adding it back to HVAC later is one overridden method.
- Warm transfer to a human (we take a message instead).
- Per-field validator/confirm *frameworks*, YAML profile configs — overkill at this size.

> Note: `poc_requirements_p0.md` lists urgency as a "deal-killer." We're consciously stepping below that for the *demo build*; the extension model (§9) is designed so it drops back in cleanly when a real customer needs it.

---

## 2. Design principles

- **Class-based extension.** A new vertical = subclass `Receptionist`, override the handful of hooks that differ, add it to the factory. Minimal boilerplate; whatever custom logic the profile needs lives *in that class*.
- **Config in code, not YAML.** Business name, services, fields, and prompt live as code on the subclass. A profile that genuinely has bulk data (the restaurant menu) **owns its own file** (`restaurant_menu.json`) and loads it itself — no shared config schema everyone must fit.
- **Template Method + Strategy + Factory.** The base class implements the common call handling and assembles the prompt; subclasses override strategy hooks (`domain_prompt`, `booking_fields`, `knowledge`). A factory maps `profile_id → class`.
- **One shared end-result contract.** `CallRecord` (in `core`) is produced by the agent and read by the store, the email, and the web view. This is the common interface between agent and backend — kept as-is.
- **Providers swappable in one place.** GCP STT/TTS today; LLM decoupled. A `providers/factory.py` is the only place that names a vendor.

---

## 3. Architecture at a glance

Two processes, one shared spine. LiveKit is already hosted; we connect to it.

```
 caller ─dials DID─▶ LiveKit (hosted) ─dispatch {profile_id}─▶ agent job
                                                     │
        ┌────────────────────────────────────────────┘
        ▼
 AGENT WORKER                          factory: profile_id → Receptionist subclass
   AgentSession: VAD▸STT▸LLM(+tools)▸TTS   (GCP STT/TTS, LLM decoupled)
        │ produces CallRecord   │ calls CalendarService / NotificationService
        ▼                       ▼
   CockroachDB ◀── save() ──────┘        ┌──────────────────────────┐
        ▲                                 │ WEB APP (FastAPI + React) │
        └──────────── read ───────────────│ /api/calls, /c/{id}?t=…   │
                                          └──────────────────────────┘
   email (summary) ── signed hardlink ─▶ /c/{id}?t=<hmac>
```

`core`, `profiles`, `services`, `persistence` are imported by both processes. `core` depends on nothing internal.

---

## 4. Repository layout

```
ai-receptionist/
├── pyproject.toml            # uv; ruff + mypy + pytest
├── README.md  LICENSE  CONTRIBUTING.md  .env.example
├── docs/
├── scripts/chat.py          # text REPL to chat with a profile (no telephony) — dev-ex
├── src/receptionist/
│   ├── core/                 # SHARED CONTRACT
│   │   ├── models.py         #   CallRecord, CallEvent, Booking, TranscriptTurn, Outcome
│   │   ├── repository.py     #   CallRepository (interface)
│   │   ├── links.py          #   sign() / verify()  — HMAC, no expiry
│   │   └── settings.py       #   pydantic-settings
│   ├── profiles/             # EXTENSION SURFACE (class-based)
│   │   ├── base.py           #   Receptionist (ABC): template + shared tools
│   │   ├── fields.py         #   Field dataclass + shared constants (NAME, EMAIL)
│   │   ├── hvac.py           #   HvacReceptionist
│   │   ├── restaurant.py     #   RestaurantReceptionist (loads its own restaurant_menu.json)
│   │   ├── data/restaurant_menu.json   #   profile-owned config
│   │   └── factory.py        #   PROFILES registry + create_profile()
│   ├── services/
│   │   ├── calendar.py       #   CalendarService (iface) + GoogleCalendarService
│   │   ├── notify.py         #   NotificationService + EmailRenderer
│   │   └── recording.py      #   LiveKit Egress → recording_url
│   ├── providers/factory.py  #   build_stt / build_tts / build_llm
│   ├── persistence/
│   │   ├── schema.sql
│   │   └── cockroach.py      #   CockroachCallRepository
│   ├── agent/worker.py       #   entrypoint: metadata → factory → AgentSession
│   └── web/
│       ├── app.py  routes/  deps.py
│       └── frontend/         #   React SPA (call list + detail/timeline)
└── tests/                    # engine + profiles with fake services (no network)
```

---

## 5. The shared contract (`core/models.py`)

Produced by the agent; read by store, email, and web. Trimmed (no urgency fields in the PoC).

```python
class Outcome(StrEnum):
    BOOKED = "booked"
    RESCHEDULED = "rescheduled"
    CANCELLED = "cancelled"
    ANSWERED = "answered"
    MESSAGE_TAKEN = "message_taken"
    ABANDONED = "abandoned"


class TranscriptTurn(BaseModel):
    ts: datetime
    role: str
    text: str  # role: "caller" | "agent"


class CapturedField(BaseModel):
    key: str
    label: str
    value: str
    confirmed: bool = False


class CallEvent(BaseModel):  # decision-timeline row — emitted by CODE
    ts: datetime = Field(default_factory=datetime.utcnow)
    type: str
    summary: str  # e.g. "question_answered", "booking_created"


class Booking(BaseModel):
    calendar_event_id: str | None = None
    service: str
    start: datetime
    end: datetime
    fields: list[CapturedField] = []


class CallRecord(BaseModel):  # THE end-result — single source of truth
    id: UUID = Field(default_factory=uuid4)
    profile_id: str
    caller_number: str
    started_at: datetime
    ended_at: datetime | None = None
    outcome: Outcome | None = None
    fields: list[CapturedField] = []
    booking: Booking | None = None
    transcript: list[TranscriptTurn] = []
    events: list[CallEvent] = []
    recording_url: str | None = None

    def share_path(self) -> str:  # -> /c/{id}?t=<signed>
        from receptionist.core.links import sign

        return f"/c/{self.id}?t={sign(self.id)}"
```

`CallRepository` (interface in `core`, implemented in `persistence`):

```python
class CallRepository(Protocol):
    async def save(self, record: CallRecord) -> None: ...
    async def get(self, call_id: UUID) -> CallRecord | None: ...
    async def list_recent(self, limit: int = 50) -> list[CallRecord]: ...
```

---

## 6. The profile base class — Template Method + Strategy

`Receptionist` extends LiveKit's `Agent`. The base owns the shared behaviour (the prompt scaffold and the three tools every profile uses); subclasses override only what differs. LiveKit's `AgentSession` drives the turns and calls the tools — we don't hand-roll a loop.

> **Follow-ups are field-driven but limited — no scripted question loop.** The LLM conducts the conversation itself; we only bound it: `booking_fields()` caps *what* gets asked, the base prompt tells it to batch related questions and stay brief (a couple of quick questions, never an interrogation), and a profile may add **at most one** domain clarifier in `domain_prompt()` (e.g. HVAC: *"if the issue is vague, ask one quick question to categorize it — won't-start vs. runs-but-no-heat"*). The natural stop condition is built in: the `book` tool refuses until required fields are present, so the model knows exactly when it has enough and stops — no counter needed. Keep each profile's `booking_fields()` short; that list *is* the annoyance control.

```python
# profiles/base.py
from abc import ABC, abstractmethod
from livekit.agents import Agent, function_tool
from receptionist.services.calendar import CalendarService
from receptionist.core.models import CallRecord, Booking, CapturedField, Outcome

BASE_PROMPT = """You are the receptionist for {business}. Be warm, concise, and never
invent facts. {domain}
When booking, collect and confirm: {fields}. Ask only for what you still need, group
related questions into one turn, and keep it to a couple of quick questions — never
interrogate the caller. You already know the caller's phone number from the call — never
ask for it. Always collect an email (it's needed to send the calendar invite), read it
back — spell it out — and get an explicit yes. Never say something is booked unless the
booking tool confirmed it. You can also reschedule or cancel the caller's existing
booking. If you can't help, take a message."""


class Receptionist(Agent, ABC):
    # --- static config the subclass sets in code ---
    profile_id: str
    business_name: str
    greeting: str  # pre-synthesized; played on connect (<1s, names the business)

    def __init__(self, calendar: CalendarService, record: CallRecord):
        self.calendar = calendar
        self.record = record
        super().__init__(instructions=self._build_instructions())

    # --- Template Method: base assembles the prompt from the strategy hooks ---
    def _build_instructions(self) -> str:
        fields = ", ".join(f.label for f in self.booking_fields())
        return BASE_PROMPT.format(
            business=self.business_name, domain=self.domain_prompt(), fields=fields
        )

    # --- Strategy hooks: subclasses override these ---
    @abstractmethod
    def domain_prompt(self) -> str: ...  # role + services + tone
    @abstractmethod
    def booking_fields(self) -> list[Field]: ...  # what to collect before booking
    def knowledge(self) -> str:
        return ""  # FAQ/menu text for Q&A; default: none

    # --- Shared tools (same for every profile) — the safety boundary ---
    @function_tool
    async def check_availability(self, day: str, window: str) -> list[str]:
        slots = await self.calendar.free_busy(...)  # source of truth → never offer a busy time
        self.record.events.append(CallEvent(type="availability_checked", summary=f"{day} {window}"))
        return [s.isoformat() for s in slots]

    @function_tool
    async def book(self, service: str, start: str) -> str:
        booking = Booking(service=service, start=..., end=..., fields=[...])
        booking.calendar_event_id = await self.calendar.create_event(booking)  # real confirmation
        self.record.booking = booking
        self.record.outcome = Outcome.BOOKED
        self.record.events.append(CallEvent(type="booking_created", summary=f"{service} @ {start}"))
        return f"Booked {service} for {start}."  # the model must read this back

    @function_tool
    async def reschedule(self, new_day: str, new_window: str) -> str:
        event_id = await self.calendar.find_event(self.record.caller_number)  # located by caller ID
        await self.calendar.reschedule(event_id, ...)
        self.record.outcome = Outcome.RESCHEDULED
        self.record.events.append(
            CallEvent(type="booking_rescheduled", summary=f"{new_day} {new_window}")
        )
        return f"Moved your appointment to {new_day} {new_window}."

    @function_tool
    async def cancel(self) -> str:
        event_id = await self.calendar.find_event(self.record.caller_number)
        await self.calendar.cancel(event_id)
        self.record.outcome = Outcome.CANCELLED
        self.record.events.append(CallEvent(type="booking_cancelled", summary="caller cancelled"))
        return "Your appointment is cancelled."

    @function_tool
    async def answer_question(self, question: str) -> str:
        self.record.outcome = self.record.outcome or Outcome.ANSWERED
        self.record.events.append(CallEvent(type="question_answered", summary=question))
        return self.knowledge()  # profile-supplied facts; no bluffing beyond them

    @function_tool
    async def take_message(
        self, name: str, reason: str
    ) -> str:  # callback # = caller ID (record.caller_number)
        self.record.outcome = Outcome.MESSAGE_TAKEN
        self.record.fields += [
            CapturedField(key="name", label="Name", value=name, confirmed=True),
            ...,
        ]
        return "Got it — I'll pass that along."
```

`profiles/fields.py` stays tiny — a `Field` is just a label + whether to confirm; no validator framework:

```python
@dataclass(frozen=True)
class Field:
    key: str
    label: str
    confirm: bool = False


NAME = Field("name", "name")
EMAIL = Field(
    "email", "email", confirm=True
)  # required — needed for the calendar invite; spelled back to confirm
# Phone isn't a collected field — it comes from the call (SIP caller ID) → record.caller_number.
```

### The three subclasses

```python
# profiles/hvac.py
class HvacReceptionist(Receptionist):
    profile_id = "hvac"
    business_name = "Helpdesk Heating and Cooling"
    greeting = "Thanks for calling Helpdesk Heating and Cooling — how can I help?"

    def domain_prompt(self):
        return (
            "You book service visits (furnace/AC repair, maintenance). "
            "Service area: Burnaby, New West, Coquitlam. $119 service call, waived if repair proceeds."
        )

    def booking_fields(self):
        return [
            NAME,
            Field("address", "service address", confirm=True),
            Field("issue", "issue description"),
            Field("day_window", "preferred day and time"),
            EMAIL,
        ]

    def knowledge(self):
        return "Hours: Mon–Sat 8–6. Service area: Burnaby, New West, Coquitlam. Service call: $119 (waived if repair proceeds). Free install quotes."
```

```python
# profiles/restaurant.py  — profile owns its OWN config file
class RestaurantReceptionist(Receptionist):
    profile_id = "restaurant"
    business_name = "Helpdesk Kitchen"
    greeting = "Thanks for calling Helpdesk Kitchen!"

    def __init__(self, calendar, record):
        self._menu = json.loads((Path(__file__).parent / "data/restaurant_menu.json").read_text())
        super().__init__(calendar, record)

    def domain_prompt(self):
        return (
            "You take table reservations. Parties over 8 → offer to take a message for the manager."
        )

    def booking_fields(self):
        return [
            Field("party_size", "party size"),
            Field("date", "date"),
            Field("time", "time"),
            NAME,
            EMAIL,
        ]

    def knowledge(self):
        return "Hours: Tue–Sun 5–10pm.\nMenu:\n" + render_menu(self._menu)
```

Adding another vertical is the same one-class move: e.g. a **parked** Auto profile (`business_name = "Helpdesk Auto Services"`) would follow the same shape — subclass `Receptionist`, override the three hooks with its own fields (name, vehicle year/make/model, service, drop-off-or-wait, email), and add one line to the factory.

### Factory

```python
# profiles/factory.py
PROFILES: dict[str, type[Receptionist]] = {
    "hvac": HvacReceptionist,
    "restaurant": RestaurantReceptionist,
}


def create_profile(profile_id: str, calendar, record) -> Receptionist:
    try:
        return PROFILES[profile_id](calendar, record)
    except KeyError:
        raise UnknownProfile(profile_id)  # fail fast; don't serve a call we can't handle
```

The agent worker reads `profile_id` from the SIP dispatch metadata and calls `create_profile(...)`.

---

## 7. Services & providers

**Services** (interfaces so tests use fakes; concrete impls call the real thing):

```python
class CalendarService(Protocol):
    async def free_busy(self, start, end) -> list[Slot]: ...
    async def create_event(self, booking: Booking) -> str: ...  # returns event id
    async def find_event(
        self, caller_number: str
    ) -> str | None: ...  # locate the caller's booking by number
    async def reschedule(self, event_id: str, start, end) -> None: ...
    async def cancel(self, event_id: str) -> None: ...
```
`GoogleCalendarService` (service-account, one calendar per profile). `create_event` adds the **caller's email as an attendee**, so Google Calendar emails them the invite automatically — that's why email is a required booking field. **Seed a couple of busy blocks** so the demo shows it declining a taken slot. `NotificationService.notify(record)` additionally emails the **owner** the summary + hardlink.

**Providers** — one place names a vendor:
```python
def build_stt(s):
    return google.STT(...)  # GCP


def build_tts(s):
    return google.TTS(...)  # GCP


def build_llm(s):
    return anthropic.LLM(...)  # decoupled; swap freely (incl. Gemini)
```
STT/TTS on GCP per your billing. LLM is an independent choice — pick a strong tool-caller since booking correctness rides on reliable tool use.

---

## 8. Persistence, links, web

- **CockroachDB** (Postgres-wire → `psycopg`/SQLAlchemy; local Postgres in dev = zero code diff). Tables: `calls`, `call_events`, `bookings` (JSONB for the nested lists). **Persist in a session-close hook, off the spoken-turn hot path** — and it still runs if the caller hangs up (outcome `ABANDONED`).
- **`core/links.py`** — `sign(id)=HMAC(secret,id)`, `verify(id,token)` constant-time. **No expiry** (per decision); bad token → 404.
- **Web app** — FastAPI + React. `GET /api/calls` (live "recent calls" dashboard for the pitch); `GET /c/{id}?t=…` verifies the token and renders the **detail view**: transcript, the code-emitted decision timeline (`call_events`), captured fields, and an audio player for the recording. Email is the executive summary; the hardlink is the full record.

---

## 9. Adding a new profile (the extension model, proven)

Add **"Riverside Dental"**:
1. `class DentalReceptionist(Receptionist)` in `profiles/dental.py` — set `business_name`/`greeting`, override `domain_prompt`, `booking_fields`, `knowledge`. Add custom tools or its own data file only if it needs them.
2. One line in `PROFILES`.
3. Point a DID's dispatch metadata at `profile_id: "dental"`.

Nothing in `core/`, `services/`, `providers/`, `web/`, or the other profiles changes.

**Same mechanism brings back a deferred feature.** Want HVAC urgency later? Override one hook on `HvacReceptionist` (e.g. a `screen(turn)` check the base calls before booking) that plays the evacuation script and skips booking on a gas/CO trigger. The base and the other profiles are untouched — which is exactly the Template Method payoff.

---

## 10. Quality bar (open-source, but PoC-sized)

`uv` · `ruff` · `mypy` (strict on `core`/`profiles`) · `pytest` with fake services so the profiles are testable with no network — one test per demo behaviour (books the open slot, declines the busy one, reschedules/cancels an existing booking, confirms a spoken email by reading it back, takes a message when off-script, never fakes a booking). `pre-commit`, `structlog`, secrets via `.env` (documented in `.env.example`). README with a one-command run; `CONTRIBUTING.md` whose centrepiece is the §9 "add a profile" recipe.

### Local dev harness (`scripts/chat.py`)

A text REPL to iterate on prompts and booking logic **without placing a phone call**. It builds a `Receptionist` through the factory with a **fake `CalendarService`** and runs the same LLM + tools over stdin/stdout — no LiveKit, STT, or TTS in the loop. `python scripts/chat.py hvac` → type as the caller, watch the tool calls fire and the resulting `CallRecord` print. Fastest way to develop the conversation before touching the voice stack.

---

## 11. Next step

Scaffold in this order: `core` models + `CallRepository` → `profiles/base.py` + `HvacReceptionist` + factory → fake `CalendarService` + `scripts/chat.py` to hand-drive it, and a passing test for the HVAC book/answer/reschedule/message paths → wire the live LiveKit `AgentSession` (GCP STT/TTS) → CockroachDB + web detail view. HVAC first end-to-end; Restaurant is then a subclass (the parked Auto profile would be one more when wanted).
