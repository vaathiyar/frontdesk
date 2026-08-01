# AI Receptionist — Web Frontend Spec (PoC)

> Companion to [`lld.md`](./lld.md) and [`poc_requirements_p0.md`](./poc_requirements_p0.md).
> Scope: the **web frontend** — the pitch asset. Implementation plan lives in
> [`frontend_plan.md`](./frontend_plan.md). This is a spec, not code.
>
> **Source of truth for every shape below is the backend, not this doc:**
> `backend/src/receptionist/core/models.py` (`CallRecord` & friends),
> `worker/lib/links.py` (signed links), `worker/profiles/*.py` (captured fields).
> Where `lld.md` disagrees with that code, the code wins — see
> [§9 Consistency with the LLD](#9-consistency-with-the-lld).

---

## 1. Goals & non-goals

**Goals**
- A clean, credible, **sales-ready** web app in both **light and dark** — what you send a prospective business owner or show a prospective employer.
- **Surface 1 — live "recent calls" dashboard** (demo centerpiece): recent calls stream in as rows that animate in, above a small **outcomes stat row**; clicking a row opens the detail view.
- **Surface 2 — signed call-detail view** reached from the emailed hardlink `/c/{id}?t=<hmac>`: it *proves the safety story* — speaker-labelled transcript, the **decision timeline** (code-emitted `CallRecord.events`, the trust artifact), captured-fields panel, booking card, outcome badge, and an **audio-player placeholder** (recording deferred).
- Render `CallRecord` **exactly**, and **degrade gracefully**: `outcome`/`ended_at`/`recording_url` may be null; captured fields are **dynamic per profile**; `CallEvent.type` / `TranscriptTurn.role` / `CapturedField.key` are **free strings**.

**Non-goals (deliberately out of scope)**
- **Recording playback.** `recording_url` is always `null` today → a *disabled* player placeholder. When a URL later appears the placeholder swaps to `<audio>` with **no contract change**.
- **Auth / login / accounts.** The only access control is the **signed link** (detail) — HMAC, no expiry, per `worker/lib/links.py`. The dashboard is a **public demo surface** (see the open decision on gating it in `frontend_plan.md`).
- **Any write path.** Both surfaces are strictly read-only views of `CallRecord`.
- **Urgency-tier UI.** Urgency is deferred in the engine (`lld.md` §1); the timeline simply renders whatever events the code emits.
- Not a production analytics dashboard — PoC-sized, favouring a polished demo over feature breadth.

---

## 2. The two surfaces at a glance

| | Surface 1 — Dashboard | Surface 2 — Call detail |
|---|---|---|
| Route | `/` | `/c/:id?t=<hmac>` |
| Access | Public (demo) | Signed link only; bad/missing token → 404 |
| Data | `GET /api/calls` (+ `GET /api/stats`) | `GET /api/calls/{id}?t=…` |
| Job | Prove the receptionist is handling live traffic with good outcomes | Prove one call was handled safely and correctly |
| Refresh | Live (polling, animate-in) | One-shot fetch |

Both render the **same** `CallRecord` type; nothing drifts.

---

## 3. Surface 1 — Live "Recent Calls" Dashboard

**Purpose.** Public, no-login demo centerpiece that streams calls in real time and, at a glance, shows the receptionist producing good outcomes.

### 3.1 Layout (desktop)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ▍Helpdesk Reception                                        ● Listening · live │  header + ConnectionPill
├──────────────────────────────────────────────────────────────────────────────┤
│  Recent calls                                                            <h1>  │
│                                                                                │
│  ┌────────┐┌───────────┐┌───────────┐┌──────────┐┌──────────┐┌───────────┐    │  stat row (<dl>, 6 tiles
│  │ Booked ││Rescheduled││  Message  ││ Answered ││Cancelled ││ Abandoned │    │  in enum order + Live now)
│  │   12   ││     3     ││ taken  5  ││    8     ││    1     ││     2     │    │
│  └────────┘└───────────┘└───────────┘└──────────┘└──────────┘└───────────┘    │
│                                                                                │
│  ┌──────────────────────────────────────────────────────────────────────────┐│  list = <ul> of row-links
│  │ ● LIVE   Helpdesk Kitchen        +1-555-0142   booking in progress…   0:18 ││
│  ├──────────────────────────────────────────────────────────────────────────┤│
│  │ [Booked] Helpdesk Heating and…   +1-555-0100   AC Repair · Tue 10:00   2m  ││  ← whole row is a link
│  ├──────────────────────────────────────────────────────────────────────────┤│
│  │ [Message]Helpdesk Heating and…   +1-555-0177   Msg: commercial boiler  6m  ││
│  ├──────────────────────────────────────────────────────────────────────────┤│
│  │ [Cancel] Helpdesk Kitchen        +1-555-0133   Cancelled · Fri 7:00PM  14m ││
│  └──────────────────────────────────────────────────────────────────────────┘│
└──────────────────────────────────────────────────────────────────────────────┘

Row = [outcome badge | ● LIVE] · business_name · caller_number · context snippet · relative time
```

**Mobile.** Stat row wraps to a 3×2 grid (or a horizontal chip strip). Each row becomes two lines: line 1 = badge + business name + time; line 2 = caller number + context snippet (muted). The "Listening · live" pill stays pinned in the header.

### 3.2 Components → data sources

Data comes from the **list item** (`CallListItem`, §7.2), not the full record.

| Component | Data source |
|---|---|
| **Header / brand** | Static wordmark, links to `/`. |
| **ConnectionPill** | Live-transport state (not from `CallRecord`): connected → "Listening · live" + pulse; retrying → "Reconnecting…"; offline → "Offline". |
| **StatRow** (`<dl>`, 6 tiles in `Outcome` order + optional "Live now") | `GET /api/stats` — **server aggregate** `by_outcome[...]` and `live_now`. Not summed from the visible ≤N rows (they can disagree once volume exceeds a page). |
| **CallList** (`<ul>`) | `GET /api/calls` — recent-first (`started_at` desc). |
| **CallRow** — an `<a href={share_path}>` wrapping the `<li>` | one `CallListItem`. |
| ↳ OutcomeCell | `outcome` → `OutcomeBadge`; if `ended_at == null` → `LiveBadge` (`● LIVE`); if `ended_at != null && outcome == null` → neutral "No outcome". |
| ↳ BusinessCell | `business_name` (server-derived from `profile_id`; client keeps a fallback map). |
| ↳ CallerCell | `caller_number`. |
| ↳ ContextCell (one line) | derived client-side: `booking` present → `booking.service + " · " + booking.slot`; else `last_event_summary` (if provided) or humanized `outcome`; else (live) "booking in progress…". |
| ↳ TimeCell | `started_at` as relative "2m" inside `<time datetime=…>`; for LIVE rows, an **elapsed timer** counting up from `started_at`. |
| ↳ RowLink | `share_path` = `/c/{id}?t=<hmac>` (server supplies it via `CallRecord.share_path()`) — how a **public** dashboard links into the **token-gated** detail without ever exposing an untokenized route. |

### 3.3 UI states

- **Loading** — 6 shimmer stat tiles + ~6 shimmer rows sized for badge/business/number/time; ConnectionPill "Connecting…". No layout shift when data swaps in.
- **Empty (no calls yet)** — keep the frame; center "Waiting for the first call…" with the pulsing live indicator so it reads *ready*, not *broken*; stat tiles show `0`. (An empty demo dashboard must still look alive.)
- **Error** — initial-load failure: inline "Can't reach the live feed" + **Retry**. Mid-stream drop: **keep the last-known rows**, show a non-destructive "Reconnecting…" via ConnectionPill, auto-retry with backoff. Never blank the list on a transient error.
- **In-progress / live row** (`ended_at == null`) — `● LIVE` pill (active accent + pulsing dot, *not* an outcome colour), elapsed timer, context = latest event; subtle persistent row tint. On resolution (same `id` arrives with `ended_at` + `outcome`) the row updates **in place**: LIVE cross-fades to the OutcomeBadge, timer freezes to a fixed duration, tint clears. *(Requires the backend to persist at call-start; see §9.)*
- **Animate-in on a new row** — arrives at the top, rows below shift down, the new row fades/slides in with a one-shot highlight (see §6.4). Under `prefers-reduced-motion` it simply appears.

---

## 4. Surface 2 — Signed Call-Detail View

**Purpose.** Token-gated, per-call **proof of trust**: the transcript *and* the code-emitted decision timeline side by side, plus captured fields, booking, outcome, and the (deferred) recording.

### 4.1 Layout (desktop, two-column)

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  ▍Helpdesk Reception                                              ← All calls  │
├──────────────────────────────────────────────────────────────────────────────┤
│  Helpdesk Heating and Cooling                                     [ Booked ]   │  <h1> + OutcomeBadge
│  +1-555-0100 · Tue Jul 21 · 2:14 PM · 4:12                                     │  caller · start · duration
│                                                                                │
│  🔗 helpdesk.demo/c/3f2a…?t=…                                    [ Copy link ] │  ShareLinkDisplay
│                                                                                │
│  ┌────────────────────────────────────────────────────────────────────────┐  │  AudioPlayerPlaceholder
│  │  ▶  ──────○───────────────────────  0:00 / 4:12    Recording coming soon │  │  (disabled)
│  └────────────────────────────────────────────────────────────────────────┘  │
│                                                                                │
│  ┌──────────────────────────────────────┐  ┌───────────────────────────────┐ │
│  │ Transcript                       <h2> │  │ Decision timeline        <h2> │ │
│  │                                       │  │ recorded automatically        │ │
│  │  Agent   Thanks for calling Helpdesk… │  │ ● Availability checked        │ │
│  │  Caller  My AC stopped working.       │  │   Tue: 9:00, 10:00     2:15PM │ │
│  │  Agent   I can help — what day works? │  │ ● Slot declined               │ │
│  │  Caller  Tuesday.                     │  │   9:00 Tue was taken   2:16PM │ │
│  │  Agent   Booked you Tuesday 10 AM.    │  │ ● Booking created             │ │
│  │  …                                    │  │   AC Repair — Tue 10:00 2:17PM│ │
│  │                                       │  ├───────────────────────────────┤ │
│  │                                       │  │ Details captured         <h2> │ │
│  │                                       │  │  Name      Jane Doe        ✓  │ │
│  │                                       │  │  Address   12 Oak St       ✓  │ │
│  │                                       │  │  Issue     No cooling      ·  │ │
│  │                                       │  ├───────────────────────────────┤ │
│  │                                       │  │ Booking                  <h2> │ │
│  │                                       │  │  AC Repair · Tuesday 10:00 AM │ │
│  │                                       │  │  ✓ On calendar                │ │
│  └──────────────────────────────────────┘  └───────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────────────────┘
```

**Mobile.** Single column, front-loading the result + proof: header → Booking → Details captured → Decision timeline → Transcript → Audio placeholder. The aside becomes stacked sections.

### 4.2 Components → data sources

| Component | Data source |
|---|---|
| **Header / nav** | Wordmark + "← All calls" back to `/` (safe to expose from a cold email link). |
| **CallHeader → BusinessTitle** (`<h1>`) | `business_name` (server-derived from `profile_id`). |
| **CallHeader → OutcomeBadge** | `outcome` (null → "In progress" / LIVE, see §6.3). |
| **CallHeader → MetaLine** | `caller_number` + `started_at` (`<time>`) + **Duration** = `ended_at − started_at` as `<time datetime="PT4M12S">4:12</time>`, or "In progress" when `ended_at == null`. |
| **ShareLinkDisplay** | current URL (`id` + `t`). Read-only field + **Copy link**. Surfaces the stable, non-expiring link owners can revisit (per `worker/lib/links.py`). |
| **AudioPlayerPlaceholder** | `recording_url`. Null → **disabled** transport + "Recording coming soon". Non-null later → `<audio controls src={recording_url}>`, no other layout change. |
| **Transcript** (`<section>`, `<ol>`) | `transcript: TranscriptTurn[]`. Each turn: `role` (humanized: caller→"Caller", agent→"Agent", unknown→humanized) as a **speaker label** + `text` + optional `ts` (`<time>`). Caller vs Agent differ by **label + alignment/tint**, never colour alone. |
| **DecisionTimeline** (`<section>`, `<ol>`, chronological) | `events: CallEvent[]`. Each row: `humanize(type)` (label + icon) + `summary` + `ts`. Sub-caption "recorded automatically" frames it as the **code-emitted** trust artifact vs the LLM transcript. |
| **CapturedFieldsPanel** ("Details captured", `<dl>`) | `fields: CapturedField[]`, rendered **generically** — `label` (fall back to `humanize(key)`), `value`, and `confirmed` → "✓ Confirmed" chip vs muted "·". `key` is used for stable DOM/test ids, not shown. |
| **BookingCard** ("Booking") | `booking: Booking \| null`, rendered only when non-null: `service`, `slot`, a **calendar status** from `calendar_event_id` ("✓ On calendar" vs muted "Not on calendar"), and `booking.fields` if present (same FieldRow treatment). |

**Known event `type`s to give tailored icons** (all others humanize + generic dot): `availability_checked`, `slot_declined`, `booking_created`, `booking_rescheduled`, `booking_cancelled`, `question_answered`, `message_taken`. `slot_declined` ("never offered a busy time") and `booking_created` ("a real, confirmed booking") are the two hero moments of the safety story — style them with intent.

### 4.3 UI states

- **Loading** — skeleton header (title, badge chip, meta), skeleton audio bar, ~6 skeleton transcript lines, ~4 timeline rows, skeleton field/booking panels.
- **Loaded** — as wireframe.
- **In-progress** (`ended_at == null && outcome == null`) — "In progress" LIVE badge, running duration, transcript/timeline may still be growing; BookingCard hidden until a booking exists.
- **Partial / edge data** — `booking == null` → hide BookingCard. `fields == []` → "No details captured." `events == []` → "No recorded actions." `transcript == []` → "Transcript unavailable." `ended_at != null && outcome == null` → neutral "Completed — no outcome recorded" (defensive; **not** LIVE).
- **Error (valid token, but API/network failed)** — full-page "Something went wrong loading this call" + **Retry**. **Visibly distinct from the 404** — it admits the call exists, which is fine for an *already-authorized* viewer.
- **Invalid / missing token → 404 (security-critical)** — one **identical** page + HTTP 404 for **every** failure mode: missing `t`, malformed `t`, wrong `t`, unknown `id`, and valid `id` + wrong token. It reveals **nothing** — no business name, no caller number, no "exists but denied". This uniformity is the point: the response must not be an oracle for enumerating call `id`s (it mirrors the constant-time `hmac.compare_digest` in `worker/lib/links.py`).

```
┌───────────────────────────────────────────────────────────────┐
│  ▍Helpdesk Reception                                           │
├───────────────────────────────────────────────────────────────┤
│                     This link isn't valid                 <h1> │
│        It may be mistyped or incomplete. Check the most        │
│        recent email we sent you and open the link again.       │
│                   [ Go to recent calls ]                       │
└───────────────────────────────────────────────────────────────┘
```

---

## 5. Shared building blocks

- **`OutcomeBadge`** — maps `Outcome | null` → `{ label, tier, icon }` (§6.3). The single place outcome styling lives; used on rows and the detail header.
- **`humanize(s)`** — the one helper for all free strings (`CallEvent.type`, `TranscriptTurn.role`, `CapturedField.key` fallback): known values → friendly label (+ icon); unknown → `underscores → spaces, Sentence case` + generic icon. **Never** renders raw `snake_case`, never crashes on an unseen value.
- **Time** — `lib/time.ts`: `formatRelative` ("2m ago") and `formatAbsolute` ("Tue Jul 21 · 2:14 PM") via `Intl`. All timestamps render inside `<time datetime={iso}>`. Backend serializes datetimes as **ISO-8601 with a UTC offset** (e.g. `2026-07-21T21:14:00+00:00`).
- **Generic field rendering** — captured-field keys are **profile-dependent** (hvac: `name/address/issue/email`; restaurant: `name/party_size/email`; a taken message adds `name/reason`). Never hardcode a column set — always iterate `label`/`value`/`confirmed`.

---

## 6. Visual & brand direction

Clean, credible SaaS look; **light and dark are both first-class** (dark is a designed set, not an auto-invert). Values below are drawn from a validated design-viz palette — re-run a contrast validator if a brand swaps its own hues in.

### 6.1 Typography
System sans only — `system-ui, -apple-system, "Segoe UI", sans-serif` (no webfont: fast, credible, zero layout shift). Scale (implementable): h1 24–28px/600, h2 16–18px/600, body 14–15px/400, meta 13px/500 (muted). Use `font-variant-numeric: tabular-nums` for **stat values, durations, and timestamp columns**; proportional figures elsewhere.

### 6.2 Colour tokens (define as CSS custom properties; swap light↔dark in one place)

| Role | Light | Dark |
|---|---|---|
| Page plane | `#f9f9f7` | `#0d0d0d` |
| Surface / card | `#fcfcfb` | `#1a1a19` |
| Primary ink | `#0b0b0b` | `#ffffff` |
| Secondary ink | `#52514e` | `#c3c2b7` |
| Muted (labels/meta) | `#898781` | `#898781` |
| Hairline border | `rgba(11,11,11,0.10)` | `rgba(255,255,255,0.10)` |
| Divider / grid | `#e1e0d9` | `#2c2c2a` |
| **Brand / interactive** (links, focus ring, primary button, wordmark, **LIVE** pulse) | `#2a78d6` | `#3987e5` |

Brand blue does double duty as the **"system active"** colour (LIVE pulse, focus, links) — deliberately distinct from every outcome hue so a live call is never mistaken for a "booked" (green) one.

### 6.3 Outcome / urgency badge treatment

Outcomes are a **status/state** encoding, not a categorical series. **Every badge carries a text label + an icon** — meaning never rides on colour alone (this is also required for AA, since amber/serious tones fall below 3:1 on the light surface). Recipe: soft tinted background + a darker/saturated same-hue text & icon that clears **4.5:1 on that tint**; attention tiers add a 1px hue border for extra weight.

| Outcome(s) | Tier | Accent (light / dark) | Icon | Weight |
|---|---|---|---|---|
| `booked`, `rescheduled` | **Positive** — goal achieved | good green `#0ca30c` / `#0ca30c` (text step `#006300` light) | check-circle / calendar-clock | strongest |
| `answered`, `message_taken` | **Neutral** — handled, no booking | secondary ink `#52514e` / `#c3c2b7` (outline) | help-circle / message-square | low |
| `cancelled` | **Caution** — deliberate, handled | warning amber `#fab219` | alert / x-circle | medium, bordered |
| `abandoned` | **Attention** — caller dropped, unresolved | critical red `#d03b3b` | phone-off / alert | highest, bordered |
| `null` **and** `ended_at != null` | Neutral defensive — "No outcome" | muted `#898781` (outline) | minus-circle | low |
| `ended_at == null` → **LIVE** (not an `Outcome`) | Active | brand blue `#2a78d6` / `#3987e5` | pulsing dot | pill + pulse |

`abandoned` is defined but **not currently emitted** by the engine, and `answered` may co-exist with a later booking — style for all six values regardless. LIVE must be distinguishable **without colour** (the word "LIVE" + dot + motion); under `prefers-reduced-motion` the pulse becomes a static ring.

### 6.4 The "animate-in" moment (dashboard)
A new record inserts at the top; rows below shift down via a transform transition; the new row plays a one-shot **fade + slide-from-top** (~250–300ms) plus a brief **highlight flash** in the brand-blue tint that fades over ~1.2s. Keep the row **keyed by `id`** so React reuses the node when a LIVE row resolves in place (badge cross-fade, timer freeze). Gate every motion behind `prefers-reduced-motion: no-preference`; reduced-motion users get an instant, non-shifting insert.

---

## 7. API contract — the frontend↔backend seam

> **This section defines the contract the backend must expose. The backend team
> implements it with the `fastapi-bp` skill; the frontend codes against it and
> mocks it with MSW until it lands (see `frontend_plan.md`).** All shapes derive
> strictly from `core/models.py`; the only additions are clearly-labelled
> server-side **enrichments** (`business_name`, `share_path`) and **aggregates**
> (`/api/stats`) — no new fields are invented on `CallRecord`.
>
> Base path `/api`. JSON in/out. Datetimes are ISO-8601 **with UTC offset**; `id`
> is a UUID string; `outcome` is a lowercase enum string or `null`.

### 7.1 `GET /api/calls` — dashboard list

Query params:

| Param | Type | Default | Meaning |
|---|---|---|---|
| `limit` | int | 30 | page size (cap ~100) |
| `before` | ISO-8601 | — | keyset cursor: return calls with `started_at < before` (older page) |
| `since` | ISO-8601 | — | optional live optimization: only calls with `started_at > since` |

**200** →
```json
{
  "items": [ /* CallListItem, recent-first (started_at desc) */ ],
  "next_before": "2026-07-21T21:11:02.511903+00:00"   // cursor for the next older page; null when exhausted
}
```

> **Backend note:** `CallRepository.list_recent(limit=50)` today supports **only**
> `limit`. This endpoint requires a small extension (a `before`/`since`-aware
> query); trivial for the in-memory store (sort by `started_at` desc, filter,
> slice). Keyset (`before`) is chosen over offset because the feed takes live
> inserts.

### 7.2 `CallListItem` (trimmed record — no transcript/events/fields for a light list)

```json
{
  "id": "3f2a6e12-8c4a-4b2e-9d77-0b2f9a1c6e10",
  "profile_id": "hvac",
  "business_name": "Helpdesk Heating and Cooling",   // server enrichment: profile_id -> Receptionist.business_name
  "caller_number": "+1-555-0100",
  "started_at": "2026-07-21T21:14:00+00:00",
  "ended_at": "2026-07-21T21:18:12+00:00",            // null => in progress (live)
  "outcome": "booked",                                 // Outcome value or null
  "booking": { "service": "AC Repair", "slot": "Tuesday 10:00 AM" },  // subset of Booking, or null
  "share_path": "/c/3f2a6e12-…?t=<hmac-hex>",          // server: CallRecord.share_path(); public row -> token-gated detail
  "last_event_summary": "AC Repair — Tuesday 10:00 AM" // OPTIONAL enrichment (events[-1].summary) for the live context line
}
```

The client derives each row's context line from these fields (§3.2); no free-text `summary` field is invented on the record.

### 7.3 `GET /api/calls/{id}?t=<hmac>` — signed detail

- Path `id` (UUID), query `t` (hex HMAC-SHA256, **required**).
- Backend: `verify(UUID(id), t)`; **if the token is missing/malformed/wrong _or_ the record is absent → 404 with an identical body** (no existence disclosure). Otherwise **200** with the full record + `business_name`.

**200 →** (`CallDetail` = full `CallRecord` + `business_name`)
```json
{
  "id": "3f2a6e12-8c4a-4b2e-9d77-0b2f9a1c6e10",
  "profile_id": "hvac",
  "business_name": "Helpdesk Heating and Cooling",
  "caller_number": "+1-555-0100",
  "started_at": "2026-07-21T21:14:00+00:00",
  "ended_at": "2026-07-21T21:18:12+00:00",
  "outcome": "booked",
  "fields": [
    { "key": "name",    "label": "name",            "value": "Jane Doe",      "confirmed": true },
    { "key": "address", "label": "service address", "value": "12 Oak St",     "confirmed": true },
    { "key": "issue",   "label": "issue description","value": "No cooling",   "confirmed": false },
    { "key": "email",   "label": "email",           "value": "jane@doe.com",  "confirmed": true }
  ],
  "booking": {
    "service": "AC Repair",
    "slot": "Tuesday 10:00 AM",
    "calendar_event_id": "evt_abc123",     // null => not on calendar
    "fields": [ /* CapturedField[] specific to the booking */ ]
  },
  "transcript": [
    { "ts": "2026-07-21T21:14:02+00:00", "role": "agent",  "text": "Thanks for calling Helpdesk Heating and Cooling — how can I help?" },
    { "ts": "2026-07-21T21:14:07+00:00", "role": "caller", "text": "My AC stopped working." }
  ],
  "events": [
    { "ts": "2026-07-21T21:15:00+00:00", "type": "availability_checked", "summary": "Tue: 9:00, 10:00" },
    { "ts": "2026-07-21T21:16:00+00:00", "type": "slot_declined",        "summary": "9:00 Tue was taken" },
    { "ts": "2026-07-21T21:17:00+00:00", "type": "booking_created",      "summary": "AC Repair — Tuesday 10:00 AM" }
  ],
  "recording_url": null
}
```

**404 →** (identical for bad token and unknown id)
```json
{ "detail": "Not Found" }
```

**Token handling on the client:** `t` is an **opaque passthrough** — the client never signs or inspects it; it reads `t` from the browser URL and forwards it verbatim to this endpoint. A 404 is terminal (no retry) → render the NotFound page.

### 7.4 `GET /api/stats` — dashboard stat row (recommended)

**200 →**
```json
{
  "window": "all",
  "total": 31,
  "by_outcome": { "booked": 12, "rescheduled": 3, "answered": 8, "message_taken": 5, "cancelled": 1, "abandoned": 2, "unknown": 0 },
  "live_now": 1
}
```
`unknown` = completed calls with `outcome == null`; `live_now` = `ended_at == null`. Server-aggregated so tiles never disagree with the capped list. *(Fallback for the earliest PoC: sum the visible page client-side — acceptable only at tiny volume.)*

### 7.5 `recording_url` and a future live push
- `recording_url` is **always `null` now** (playback deferred). No contract change is needed when it becomes a URL — the field already exists; the client swaps the placeholder for `<audio>`.
- **Optional upgrade:** `GET /api/calls/stream` (SSE) as a future push feed. Not required for the PoC — polling `GET /api/calls` (top page, reconcile by `id`) is the recommendation (see `frontend_plan.md`). Documented here so the seam is stable if it's added.

---

## 8. Accessibility basics

- **Keyboard.** Dashboard rows are real `<a href={share_path}>` wrapping the `<li>` → natively focusable, Enter-activatable, top-to-bottom order, visible focus ring (brand blue, ≥3:1). Avoid `<div onClick>`. **Copy link** and audio controls are real `<button>`s; the disabled placeholder uses `disabled` (out of tab order) with a caption. On entering detail, move focus to `<h1>`; on 404, focus its `<h1>`.
- **Semantics.** Stat row = `<dl>` (outcome `<dt>`, count `<dd>`); list = `<ul>`/`<li>`; transcript & decision timeline = `<ol>` (ordered sequences); captured fields = `<dl>`. Headings: dashboard `<h1>` "Recent calls"; detail `<h1>` = business name with `<h2>` per section. Detail landmarks: `<header>`+`<nav>`, `<main>` (transcript), `<aside role="complementary">` (timeline/fields/booking), each section `aria-labelledby` its heading. All times use `<time datetime>`.
- **Transcript for screen readers.** Each turn begins with the speaker name as **text** (visible or `sr-only` "Agent:" / "Caller:") so it reads as a natural back-and-forth; speaker is never conveyed by alignment/colour alone.
- **Live regions.** Wrap the list (or a status line) in `aria-live="polite" aria-relevant="additions"`; announce **throttled**, concise updates only — new arrivals ("New call: Helpdesk Kitchen") and resolutions ("Helpdesk Heating and Cooling — booked"). The ticking timer is `aria-hidden`. Never `assertive`. "Link copied" confirms via a polite live region.
- **Contrast & motion.** Body text ≥4.5:1; large text/badges/icons/focus ≥3:1 (WCAG AA). Every badge pairs colour with icon + label. `prefers-reduced-motion` disables row slide/shift and the LIVE pulse.

---

## 9. Consistency with the LLD

This spec is consistent with `lld.md` except for the following **explicit refinements**, where the actual backend code (or the root `README`) is the source of truth:

| # | `lld.md` says | This spec / the code | Why |
|---|---|---|---|
| 1 | §5 `Booking` has `start`/`end` datetimes | `Booking` is `{ service, slot: str, calendar_event_id, fields[] }` — a **single human-readable `slot`** | `core/models.py` is the shipped contract; there are no `start`/`end` fields. Time UIs just display the `slot` string. |
| 2 | §4 SPA nested under the backend package | Top-level **`frontend/` sibling of `backend/`** | Root `README` already anticipates this; keeps the Node/TS toolchain out of the Python wheel. FastAPI can still serve `../frontend/dist`. |
| 3 | §6 per-profile `booking_fields()` (e.g. HVAC has `day_window`) | Actual keys differ per profile; message-taking adds `name/reason` | Captured fields are **dynamic** — the UI renders them generically, never a fixed schema. |
| 4 | §5 `CallRepository.list_recent(limit)` | The dashboard needs `before`/`since` + a `/api/stats` aggregate | Small backend extension flagged in §7. |
| 5 | §8 persist in a **session-close** hook | The **in-progress / LIVE** row needs a record saved **at call-start** (updated at close) | Otherwise every row arrives already-completed (still a fine "streaming" demo, but no live timer). Flagged as a backend dependency. |
| 6 | `business_name` is not on `CallRecord` | The API **enriches** list & detail with `business_name` from the profile registry | Single source of truth for the profile→name map stays in the backend; the client keeps only a defensive fallback. |

Not a contradiction: the engine's deferral of urgency (§1) — this spec simply renders whatever `events` the code emits, so urgency drops in for free when it returns.
