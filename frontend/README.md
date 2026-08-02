# Frontdesk — frontend

React SPA for the Frontdesk demo. Two surfaces:

| Route | What it is |
| --- | --- |
| `/` | The demo pitch and the two live phone numbers a visitor can call. |
| `/c/:id` | One call record. This is the URL that goes out in the confirmation SMS. |
| `*` | Not found. |

## Run it

```bash
npm install
npm run dev          # http://localhost:5173
```

```bash
npm run build        # tsc -b && vite build  -> dist/
npm run preview      # serve the built bundle
```

## How it reaches the backend

One endpoint, one request, no auth:

```
GET {VITE_API_BASE_URL}/api/calls/{id}   ->  200 record | 404 {"detail":"Not Found"}
```

`VITE_API_BASE_URL` defaults to `""`, i.e. same-origin relative requests. In dev
that still works, because `vite.config.ts` proxies `/api` to
`http://localhost:8000`, so the SPA and the FastAPI backend look like one
origin. Set an absolute origin only if the SPA is ever served from a different
host than the API. Copy `.env.example` to `.env` to override.

The whole data layer is `src/lib/useCallRecord.ts` — a single `fetch` on mount
plus an explicit retry. There is no query cache and no request library.

Record links that were already sent carry a trailing `?t=<hex>`. It is ignored:
the id in the path is the only input the page reads.

## Sample records

The backend does not have to be running to work on the record page. Any id
starting with `demo-` renders from `src/lib/fixtures.ts` instead of the network.
This is on automatically in `npm run dev`, and the landing page grows an index
of them at the bottom. To get the same behaviour out of a production build:

```bash
VITE_USE_FIXTURES=1 npm run build
```

The set covers the shapes that break naive implementations: a booked HVAC call,
a message taken instead of a booking, a rescheduled call whose confirmation SMS
failed, a cancelled call with no booking left, a call with `ended_at: null` and
an empty transcript and empty timeline, and one full of values this build has
never seen (unknown outcome, unknown event type, camelCase and nested detail
keys). Three further ids force the non-success states: `demo-loading`,
`demo-missing`, `demo-error`.

## Design notes

The record page is built mobile-first, because that is where the SMS link gets
opened. Order on a phone: what happened → the appointment → what the agent
actually did → what was said.

Two typefaces carry the central distinction. **Archivo** sets anything a human
said or authored; **IBM Plex Mono** sets anything a machine emitted — timestamps,
phone numbers, ids, event types. So the transcript and the decision timeline
never read as the same kind of evidence.

Colour is defined in OKLCH in `src/styles.css` and means exactly four things:

| Token | Meaning |
| --- | --- |
| `signal` (amber) | The agent took an action, recorded by code. |
| `confirm` (pine) | It landed on the business's real calendar. |
| `alert` (rust) | Declined, cancelled or failed. |
| `ink` / neutrals | Everything said, and everything unclassified. |

Every tone is paired with an icon and a text label, so nothing is carried by
colour alone. Light and dark are both handled through
`prefers-color-scheme` overrides of the raw custom properties, which the
Tailwind v4 `@theme inline` block references.

## Layout

```
frontend/
├─ index.html                     fonts, colour-scheme, theme-color
├─ vite.config.ts                 react + tailwind plugins, /api proxy
├─ src/
│  ├─ main.tsx  App.tsx           routes
│  ├─ styles.css                  the whole design system: tokens, scale, utilities
│  ├─ lib/
│  │  ├─ types.ts                 the API contract
│  │  ├─ api.ts                   fetch + defensive normalisation
│  │  ├─ useCallRecord.ts         the data layer
│  │  ├─ format.ts                dates, durations, phones, the key humanizer
│  │  ├─ semantics.ts             outcome + event tone/label mapping
│  │  └─ fixtures.ts              sample records
│  ├─ components/
│  │  ├─ Shell.tsx                header, footer, skip link
│  │  ├─ CallTape.tsx             the call drawn to scale
│  │  ├─ EventTimeline.tsx        what the agent did
│  │  ├─ Transcript.tsx           what was said
│  │  ├─ BookingPanel.tsx         the appointment
│  │  ├─ MessagePanel.tsx         the message
│  │  ├─ OutcomeChip.tsx  EventIcon.tsx  RecordStates.tsx  primitives.tsx
│  └─ routes/
│     ├─ Landing.tsx  CallRecordPage.tsx  NotFoundPage.tsx
```

## Contract notes worth keeping

- `outcome` is a free string. Unknown values humanize (`snake_case` →
  `Sentence case`) and render with the raw token beside them, never crash.
- `ended_at` is nullable. Duration shows "In progress" and the call tape runs
  into hatching rather than closing.
- `booking.details` is a different key set per business. It is always iterated,
  never named.
- `transcript` and `events` may be empty; both have designed empty states.
- `role` and `event.type` are free strings too.
