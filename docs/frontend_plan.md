# AI Receptionist — Web Frontend Implementation Plan (PoC)

> Companion to [`frontend_spec.md`](./frontend_spec.md) (the *what*) and
> [`lld.md`](./lld.md). This is the *how*: stack, structure, dev/build/hosting,
> milestones, tests, and the decisions left for a human. **Planning only — no app
> code is written here.**

---

## 0. Grounding facts (from the backend, today)

- The **web/API layer is greenfield** — the FastAPI app exists but serves only a health check: there is no `/api/calls` and no `/c/{id}` route. The frontend's only fixed contract is `CallRecord` (`core/models.py`), the `sign`/`verify` link scheme (`worker/lib/links.py`), and the profile registry. → the frontend develops against **MSW mocks** of the [API contract](./frontend_spec.md#7-api-contract--the-frontendbackend-seam); the backend team implements that contract with `fastapi-bp`.
- `core/settings.py` already has **`RECEPTIONIST_PUBLIC_BASE_URL` (default `http://localhost:8000`)** — "the base URL hardlinks are built against" — and `CallRecord.share_path()` returns a **same-host** path `/c/{id}?t=…`. The signed-link design already assumes **one origin** → drives §4.
- Backend runs on **Python ≥3.11 via `uv`** from `/home/kris/ai/frontdesk/backend` (`uv sync --extra dev`, `uv run pytest`, `uv run python scripts/chat.py hvac`).
- **`Booking.slot` is a string**, `outcome` is nullable, `recording_url` is always null, captured fields are dynamic — see spec §9. The client mirrors the code, not `lld.md`.

**LLD refinement (explicit):** `lld.md` §4 nested the SPA under the backend package. We refine this to a **top-level `frontend/` sibling of `backend/`** (`/home/kris/ai/frontdesk/frontend`) — the root `README` already lists it. FastAPI still *serves* the built assets by pointing `StaticFiles` at `../frontend/dist` (§4).

---

## 1. Tech stack (with justification)

Tuned for **a polished pitch asset built fast**: minimal, well-known dependencies.

| Concern | Choice | Justification |
|---|---|---|
| **Base** | React 18/19 + Vite 6 + TypeScript | Mandated. Vite = instant HMR, first-class TS, trivial dev proxy + env story. |
| **Styling** | **Tailwind CSS v4** (`@tailwindcss/vite`) | Chosen **over CSS Modules**. Fastest path to a *consistent, polished* look: design tokens in one `@theme` block, `dark:` variant gives cohesive dark mode almost free (toggle `.dark` on `<html>`), utilities remove naming/spec-drift. CSS Modules would mean hand-rolling a token system + manual dark theming — slower and more inconsistent under a demo deadline. v4's Vite plugin is zero-config. |
| **Data fetching** | **TanStack Query v5** | Chosen **over a custom fetch+cache**. Ships exactly the three needs: `refetchInterval` (live polling), `useInfiniteQuery` (cursor pagination on `next_before`), and built-in loading/error/stale states + dedup + retry control. Detail uses `useQuery(..., { retry: false, staleTime: Infinity })` so a 404 surfaces immediately without retry churn. A custom cache would re-implement all of this and be the riskiest code in the app. |
| **Routing** | **React Router v6** (`createBrowserRouter`) | Standard, tiny; the client-side history routing the SPA catch-all (§4) relies on. Routes `/`, `/c/:id` (reads `?t=` via `useSearchParams`), `*`. TanStack Router is heavier for two routes. |
| **Icons** | **lucide-react** | Tree-shakeable line icons matching the modern look; import only what's used. |
| **Date/time** | Native **`Intl`** (`DateTimeFormat` + `RelativeTimeFormat`) in `lib/time.ts` | Zero-dep absolute + relative formatting. Add `date-fns` only if it gets fiddly (open decision). |
| **Animation** | **CSS-only** (Tailwind keyframes + a `data-new` flag) | No dependency for fade/slide + highlight; `framer-motion` only if list reordering needs enter/exit choreography (open decision). |
| **Component lib** | **None** | Two surfaces; a small hand-rolled `components/ui/` keeps the bundle small and the visual language consistent. |

**Runtime deps:** `react`, `react-dom`, `react-router-dom`, `@tanstack/react-query`, `lucide-react`.
**Dev deps:** `vite`, `@vitejs/plugin-react`, `typescript`, `@types/react`, `@types/react-dom`, `tailwindcss`, `@tailwindcss/vite`, `vitest`, `jsdom`, `@testing-library/react`, `@testing-library/jest-dom`, `@testing-library/user-event`, `msw`.
No client-side secrets, no auth SDK, **no HMAC lib** (the token is an opaque passthrough).

---

## 2. Directory structure (`/home/kris/ai/frontdesk/frontend`)

```
frontend/
├── index.html
├── package.json
├── tsconfig.json  tsconfig.node.json
├── vite.config.ts                 # react + tailwind plugins; /api dev proxy
├── .env.example  .env.development  .env.production
├── .gitignore                     # node_modules, dist
├── public/favicon.svg
└── src/
    ├── main.tsx                   # QueryClientProvider + RouterProvider
    ├── router.tsx                 # createBrowserRouter: '/', '/c/:id', '*'
    ├── index.css                  # @import "tailwindcss"; @theme tokens; keyframes
    ├── types/
    │   └── call.ts                # CallListItem, CallDetail, Booking, CapturedField,
    │                              #   TranscriptTurn, CallEvent, Outcome — mirror the contract
    ├── api/
    │   ├── client.ts              # fetchJson(): base URL + non-2xx -> ApiError { status }
    │   ├── calls.ts               # useCallsInfinite / useCall / useStats
    │   └── queryKeys.ts
    ├── lib/
    │   ├── time.ts                # formatAbsolute, formatRelative, formatDuration (Intl)
    │   ├── outcome.ts             # outcome (incl. null) -> { label, tier, icon }
    │   ├── humanize.ts            # free-string -> friendly label (event.type / role / key)
    │   ├── businessName.ts        # profile_id -> name (defensive fallback only)
    │   └── cn.ts
    ├── components/
    │   ├── ui/                    # Badge, Card, Spinner, Skeleton, EmptyState, ErrorState
    │   ├── StatRow.tsx            # KPI tiles from /api/stats
    │   ├── CallList.tsx  CallRow.tsx      # CallRow handles animate-in / live timer
    │   ├── ConnectionPill.tsx  DarkModeToggle.tsx
    │   ├── BookingCard.tsx  FieldsTable.tsx
    │   ├── Transcript.tsx  Timeline.tsx   # events = decision timeline
    │   └── RecordingPlayer.tsx    # disabled placeholder while recording_url === null
    ├── routes/
    │   ├── Dashboard.tsx          # '/'
    │   ├── CallDetail.tsx         # '/c/:id' — reads :id + ?t=
    │   └── NotFound.tsx           # bad token / unknown id / unknown route (identical)
    └── test/
        ├── setup.ts               # jest-dom + MSW server lifecycle
        ├── handlers.ts            # MSW: /api/calls, /api/calls/:id (404 unless t valid), /api/stats
        └── fixtures.ts            # records/list-items derived from the contract
```
Co-locate `*.test.tsx` next to the component under test.

---

## 3. Local dev — frontend + backend together

Two processes, one logical origin via the dev proxy:

- **Backend** (from `backend/`): `uv run fastapi dev` *(module path per `lld.md` §4; confirm with the backend team since it's greenfield)*.
- **Frontend** (from `frontend/`): `npm run dev` → Vite on `:5173`.

**Vite proxy — proxy only `/api`** (`vite.config.ts`):
```ts
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { '/api': 'http://localhost:8000' } },
});
```

**Do *not* proxy `/c`** (refinement of the task's "proxy /api and /c"): `/c/:id` is a **client route** that serves no data. The browser URL carries `?t=`; `CallDetail` extracts it and calls `/api/calls/{id}?t=` (which *is* proxied). In dev, Vite's SPA fallback serves `index.html` for `/c/:id` with full HMR; proxying `/c` would defeat that. To click the **real emailed hardlink** in dev, set the backend's `RECEPTIONIST_PUBLIC_BASE_URL=http://localhost:5173` so links point at the Vite origin → SPA fallback → React Router → `/api/*` proxied to `:8000`.

**Env / config** (`VITE_*` are build-time inlined — never secrets):
- `VITE_API_BASE_URL` — **default `""` (relative)** so `/api/...` works via the dev proxy **and** the single-origin prod deploy unchanged. Set an absolute URL only for the cross-origin hosting option.
- `VITE_POLL_INTERVAL_MS` — default `4000`.
- Files: `.env.development`, `.env.production`, `.env.example` (documents both).

**Bootstrap:**
```bash
npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm i @tanstack/react-query react-router-dom lucide-react
npm i -D tailwindcss @tailwindcss/vite vitest jsdom \
  @testing-library/react @testing-library/jest-dom @testing-library/user-event msw
npx msw init public/     # dev mocking service worker
npm run dev              # :5173  (backend: uv run fastapi dev)
```
Optional: a root `Makefile`/`concurrently` target to boot both — nice-to-have, two terminals is fine for a PoC.

---

## 4. Build & serve + hosting (reconciling the LLD's open decision)

**Recommendation: FastAPI serves the built Vite assets — single origin.**

Why, for this PoC:
1. **The signed-hardlink design already assumes one host** — `public_base_url` defaults to `:8000`, `share_path()` returns a same-host path. Single origin means the emailed link, the SPA, and the API share an origin — no split-brain base URL to reconcile.
2. **No CORS** — no preflight or cross-origin credential edge cases to debug during a live demo.
3. **One artifact, one URL** — a single service to deploy (one Render/Fly box) and one link to hand out in the pitch.
4. **404-on-bad-token is unaffected** — token verification lives entirely in `GET /api/calls/{id}?t=`; serving the HTML shell never touches it.

Trade-off: a frontend ship couples to a backend redeploy — acceptable for a PoC, and Vite dev + proxy keeps local iteration fast. Choose the **separate-host** option (Vercel/Netlify/Render + cross-origin API, needing CORS + `VITE_API_BASE_URL` + `public_base_url` pointed at the SPA host) **only** if a frontend team wants independent CDN/per-PR-preview deploys — not worth the extra origins here.

**SPA catch-all in FastAPI (for the `fastapi-bp` team) — order matters:**
1. **Register `/api/*` routers first** (`/api/calls`, `/api/calls/{id}`, `/api/stats`) — explicit routes beat the wildcard; unmatched `/api/*` must return **JSON 404**, never the HTML shell.
2. **Mount hashed assets:** `app.mount("/assets", StaticFiles(directory=<dist>/assets), name="assets")` (Vite fingerprints under `/assets`).
3. **HTML fallback LAST:** a wildcard `GET /{full_path:path}` returning `<dist>/index.html`, so `/`, `/c/:id`, and any deep link serve the same shell; React Router then renders the right route client-side.

A browser deep-link `/c/<id>?t=…` has no explicit route → hits the fallback → `index.html` → React Router → `CallDetail` → fetches `/api/calls/<id>?t=…`; a **bad token still 404s via the API** and the client shows NotFound. Gotcha: `StaticFiles(html=True)` serves `index.html` only at directory roots, **not** arbitrary client routes like `/c/:id`, so the explicit wildcard fallback is required. Point `StaticFiles`/fallback at `../frontend/dist` (mono-repo) or a `static/` dir copied into the image at build (`cd frontend && npm run build`).

---

## 5. Milestones & acceptance criteria

Each milestone is independently demoable; **MSW (M1) unblocks all frontend work without waiting on the greenfield backend.**

### M1 — Skeleton + dashboard list (against a mocked API)
Scaffold Vite+TS+React; Tailwind + light/dark tokens; router (`/`, `/c/:id`, `*`); `QueryClientProvider`; MSW handlers + fixtures from the contract; TS types mirroring `CallListItem`/`CallDetail`; Dashboard renders `GET /api/calls` via `useInfiniteQuery` — each row: `business_name`, `caller_number`, outcome badge, context line, relative time; loading/empty/error states; "load more" via `next_before`.
**Acceptance**
- `npm run dev` shows a styled list served by MSW (no backend needed).
- Loading → skeleton; empty and error states reachable by toggling the handler.
- Outcome→badge mapping correct for **all six outcomes and `null`** ("In progress"/"No outcome").
- Booking context line renders; relative + absolute time correct; row click routes to `/c/:id`.
- `tsc --noEmit` and `npm run build` pass; layout responsive; both themes legible.

### M2 — Detail view + signed-link / token handling + 404
`/c/:id` reads `:id` + `?t=`; `useCall(id, token)` (`retry:false`) → `GET /api/calls/{id}?t=`; renders header (business, caller, start/duration, outcome), `BookingCard` (`service` + `slot`), `FieldsTable` (generic; `confirmed` state), `Transcript` (caller/agent styling, ordered by `ts`), `Timeline` (decision `events`, ordered), disabled `RecordingPlayer`. Missing/invalid token, unknown id, and API 404 all render the **same** NotFound; other errors render a generic error state.
**Acceptance**
- Valid token → full detail, all sections; booking-absent renders gracefully.
- **Bad token, missing token, and unknown id all show the identical NotFound** — no detail leaked, no existence disclosure.
- Deep-link entry (`/c/:id?t=` opened cold) renders (SPA-fallback path exercised).
- Transcript & timeline ordered; recording player disabled; "← All calls" works.
- Timeline **humanizes an unknown `event.type`** instead of showing raw snake_case.

### M3 — Live updates + polish
Live tailing via TanStack Query `refetchInterval` on the **top page**, reconciled **by `id`** (catches both new calls and LIVE→resolved transitions); new items flagged for **animate-in** (fade/slide + one-shot highlight); `StatRow` from `GET /api/stats`; `ConnectionPill`; `DarkModeToggle` persisted (localStorage + `prefers-color-scheme` initial); a11y + polish pass.
**Acceptance**
- A new call appears within the poll interval and animates **exactly once**; a LIVE row resolves **in place** (badge cross-fade, timer freeze).
- Stat row updates live with no layout shift; polling pauses when the tab is hidden (`refetchIntervalInBackground: false`).
- Dark-mode choice persists across reload and honours the system default on first load.
- `prefers-reduced-motion` disables animate-in/pulse; axe/Lighthouse report **no serious a11y violations** (landmarks, labels, focus order, contrast, keyboard).

---

## 6. Test approach

- **Runner:** **Vitest** (Vite-native, `jsdom`) + **React Testing Library** + `@testing-library/jest-dom` + `user-event`.
- **Contract/mock:** **MSW** — one set of handlers + fixtures powers **both dev and tests** (`setupWorker` in dev, `setupServer` in tests). Fixtures derived from the contract: a `booked` (with `booking`), an `answered`, a `message_taken`, a **null-outcome / live** one, one **without** a booking, and one with an **unknown `event.type`**. Asserting UI against these makes contract drift (e.g. a missing `business_name`) fail fast. **Detail handler returns the record only when the token is the fixture's valid `t`, else 404** — so bad-token and unknown-id paths are exercised identically.
- **Type-safety of the seam (recommended):** once the backend exists, generate `types/call.ts` from its **OpenAPI** (`openapi-typescript`) so client types can't drift from the FastAPI models. Until then, hand-write types mirroring the contract.

**Per surface:**
- **Dashboard** — loading/empty/error; outcome→badge incl. `null`; context line; relative time; (M3) animate-in adds the class only for a genuinely-new `id` and **respects `prefers-reduced-motion`**; stat-row math from a known fixture; polling merges a new item (Vitest fake timers).
- **Detail** — valid token → all sections; **bad token → NotFound**; **missing token → NotFound**; **unknown id → NotFound (assert identical DOM to bad-token — no existence leak)**; booking present/absent; transcript & timeline ordering + unknown-type humanization; recording placeholder disabled; non-404 → error state.
- **Lib units** — `outcome.ts` map, `humanize.ts` (known + unknown), `time.ts` under a fixed clock, `api/client.ts` (non-2xx → `ApiError{status}`; forwards `t` verbatim; 404 is terminal, not retried).

PoC-sized: a handful of high-value tests per surface. **CI = `tsc --noEmit` + `vitest run` + `npm run build`.**

---

## 7. Open decisions for the human

| Decision | Options | Recommendation |
|---|---|---|
| **Hosting model** | Single-origin (FastAPI serves the built SPA) vs separate host + cross-origin API | **Single-origin** — matches the `public_base_url`/hardlink assumption; no CORS; one URL. |
| **Live mechanism** | Poll `GET /api/calls` top page & reconcile by `id` vs SSE `GET /api/calls/stream` | **Poll ~4s.** Free via `refetchInterval`, catches new *and* LIVE→resolved transitions, trivial through the proxy/single-origin, nothing to reconnect. SSE is a later swap behind the same hook. |
| **Dashboard access** | Fully public vs a light env-toggled gate (basic-auth / shared passphrase) | **Light gate before wide sharing** — the list exposes caller numbers and the detail exposes transcripts. Fully public is fine only with synthetic demo data. |
| **In-progress rows** | Persist at call-**start** (enables the LIVE timer) vs only at session-close | **Persist at start + update at close** if the live timer matters for the pitch; otherwise every row simply arrives already-completed (still a good streaming demo). Backend dependency. |
| **Pagination** | Keyset (`before`/`next_before`) vs offset | **Keyset** — stable under live inserts; client uses `useInfiniteQuery`. |
| **Stat counts** | `GET /api/stats` server aggregate vs client-sum the visible page | **`/api/stats`** — tiles never disagree with the capped list. Client-sum only as an earliest-PoC fallback. |
| **`business_name` source** | Server-resolved (in the contract) vs client map | **Server-resolved**; ship a tiny client fallback map (`hvac/restaurant`) only for a missing/unknown value. |
| **Seam type-safety** | Hand-written TS types vs generated from backend OpenAPI | **Generate via `openapi-typescript`** once the API exists; hand-write until then. |
| **Date/relative time** | Native `Intl` (zero-dep) vs `date-fns` | **Native `Intl`**; add `date-fns` only if ergonomics bite. |
| **Animate-in** | CSS-only vs `framer-motion` | **CSS-only** for M3; adopt `framer-motion` only if list reordering needs enter/exit choreography. |

---

## 8. Backend dependencies (hand-off to the `fastapi-bp` team)

The frontend is unblocked by MSW, but the live demo needs the backend to:
1. **Add `api/routes/calls.py`** implementing the [API contract](./frontend_spec.md#7-api-contract--the-frontendbackend-seam).
2. **Extend `CallRepository`** beyond `list_recent(limit)` with `before`/`since` querying and a stats aggregate (trivial for the in-memory store).
3. **Wire a shared repository instance** into the web app and **actually populate it** — today `scripts/chat.py` builds a `CallRecord` but never `save()`s, and nothing holds a store. For the pitch, seed the store and/or run a demo driver that inserts records so the dashboard visibly streams.
4. **Verify tokens with `worker/lib/links.verify`** and return an **identical 404** for bad-token and unknown-id (no enumeration oracle).
5. Serve the built SPA per §4 (StaticFiles + wildcard `index.html` fallback), or deploy the separate-host option if that decision flips.
