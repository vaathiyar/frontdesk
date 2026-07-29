# Voice + LiveKit SIP — Delivery Plan

> **Historical.** This plan has been delivered, and the engine it describes has since been
> rebuilt on LangGraph — so its code sketches (`ConversationRunner`, `providers/factory.py`,
> `tool_schemas()`) no longer match the tree. Kept for the telephony reasoning and the SIP
> reference links, which still hold. For the design as actually built, read
> [`lld.md`](./lld.md); for running it, [`../backend/deploy/README.md`](../backend/deploy/README.md).

> How we get from today's text-only brain to a **hostable Docker image that answers a real phone call** over LiveKit SIP. Companion to [`lld.md`](./lld.md).

---

## 0. Where we are today

**Done (and tested, offline):**
- The brain: `Receptionist` (prompt + 6 tools + `CallRecord`), `ConversationRunner` (manual tool-use loop), `providers/gemini.py` (Gemini adapter, incl. the thought-signature fix).
- Profiles: `hvac`, `restaurant` (auto parked). `FakeCalendarService`. `core/` contract (`CallRecord`, `links`, `repository`), `persistence/memory.py` (in-memory repo).
- Dev harness `scripts/chat.py`; offline unit suite + **live e2e** suite (`tests/test_e2e.py`, simulated caller).

**Not built yet:** anything voice/telephony — no LiveKit deps, no `agent/worker.py`, no STT/TTS/VAD wiring (the `build_stt`/`build_tts` factory fns are stubs), no real `GoogleCalendarService`, no owner notification, no durable persistence, no web dashboard.

The brain is deliberately LiveKit-free so it stays testable without a network. The voice work adds LiveKit **around** it — it does not rewrite it.

---

## 1. The one decision to make first — the integration seam

LiveKit's `AgentSession` orchestrates the real-time loop **VAD ▸ STT ▸ LLM(+tools) ▸ TTS**, plus endpointing, barge-in, and interruptions. We need our tools + prompt + `CallRecord` to run *inside* that loop. Two ways:

- **(A) Recommended — LiveKit drives, we adapt.** Use `AgentSession` with LiveKit's Google **LLM plugin** (Gemini) for reasoning, and expose our existing tools to it. Keep `Receptionist` as the pure brain; add a thin `ReceptionistAgent(livekit.agents.Agent)` adapter that:
  - sets `instructions = receptionist.system_prompt()`,
  - builds LiveKit function-tools **at runtime from `receptionist.tool_schemas()`**, each handler calling `receptionist.dispatch(name, args)` — so the tool surface, the safety boundary, and the `CallRecord` side-effects stay a **single source of truth** (the same code the offline e2e suite exercises).

  LiveKit handles the hard real-time voice mechanics; our `ConversationRunner` + Gemini adapter remain the **text/dev/test driver** (`chat.py`, `test_e2e.py`). Same model, same prompt, same tools — two drivers.

- **(B) Alternative — we drive, LiveKit transports.** Plug `ConversationRunner` in as a custom LiveKit LLM node (STT text in → our loop → text out to TTS). Reuses the exact tested loop, but we give up LiveKit's built-in tool orchestration and have to hand-manage streaming/interruption around a multi-round loop. More bespoke, more brittle.

**Go with (A).** The rest of this plan assumes it. (If you'd rather keep the `ConversationRunner` as the literal voice brain, say so — Phases 2–3 change.)

> Dynamic tool schemas: our `book` tool's parameters vary per profile (`booking_fields()`), so we build LiveKit tools from a **raw JSON schema at runtime** (LiveKit supports raw/dynamic function tools) rather than static `@function_tool` signatures. Verify the exact raw-tool API against the installed `livekit-agents` version.

---

## 2. Phase 1 — Dependencies & provider plugins

1. Add to `pyproject.toml`:
   - `livekit-agents` (the framework), `livekit-plugins-google` (STT/TTS/LLM on GCP + Gemini), `livekit-plugins-silero` (VAD), and optionally `livekit-plugins-turn-detector` (better endpointing) and `livekit-plugins-noise-cancellation` (LiveKit Cloud only).
   - `uv sync` and commit the lockfile.
2. Fill in `providers/factory.py` (the constants `STT_MODEL`/`TTS_VOICE`/`VAD` already live there):
   - `build_stt()` → `google.STT(model=STT_MODEL, spoken_punctuation=False, languages=["en-US"], location=STT_LOCATION)`
   - `build_tts()` → `google.TTS(voice_name=TTS_VOICE)`
   - `build_vad()` → `silero.VAD.load()` (add the constant/knob)
   - `build_llm()` → `google.LLM(model=CHAT_MODEL)` (Gemini) — new; the voice reasoner
   - Keep `build_chat()` (our Gemini adapter) for the text driver.
   - These read GCP creds from `GOOGLE_CREDENTIALS_FILE_PATH` and Gemini from `GOOGLE_API_KEY`. Verify constructor kwargs against the plugin's current version.

---

## 3. Phase 2 — Tools usable by both drivers

- Confirm each tool body (`_tool_book`, etc.) is side-effect-complete (touches calendar, mutates `CallRecord`) — it already is.
- Add the adapter that turns `receptionist.tool_schemas()` into LiveKit tools whose handlers call `receptionist.dispatch(...)`. No second copy of the tool logic.
- Offline tests are unchanged and remain the correctness guarantee for tool behavior.

---

## 4. Phase 3 — The agent worker (`agent/worker.py`)

The dockerized process. Sketch (verify API against installed version):

```python
from livekit import agents
from livekit.agents import AgentSession, JobContext, WorkerOptions, cli

async def entrypoint(ctx: JobContext):
    await ctx.connect()

    profile_id = json.loads(ctx.job.metadata or "{}").get("profile_id", "hvac")
    participant = await ctx.wait_for_participant()          # the inbound SIP caller
    caller_number = participant.attributes.get("sip.phoneNumber", "unknown")

    record   = CallRecord(profile_id=profile_id, caller_number=caller_number)
    calendar = build_calendar()                              # Fake for MVP; Google later
    brain    = create_profile(profile_id, calendar, record) # pure Receptionist
    agent    = ReceptionistAgent(brain)                     # LiveKit adapter (Phase 1/2)

    session = AgentSession(stt=build_stt(), llm=build_llm(), tts=build_tts(), vad=build_vad())

    async def finalize():                                    # runs even on hang-up
        record.ended_at = now()
        record.outcome = record.outcome or Outcome.ABANDONED
        await repo.save(record)
        await notify.notify(record)                          # owner email + share link
    ctx.add_shutdown_callback(finalize)

    await session.start(agent=agent, room=ctx.room)
    await session.say(brain.greeting)                        # named-business greeting on connect

if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, agent_name="receptionist"))
```

Key points:
- **`agent_name="receptionist"`** disables auto-dispatch → the agent is dispatched *explicitly* by the SIP dispatch rule (Phase 6).
- **`profile_id` comes from `ctx.job.metadata`** (set per DID in the dispatch rule) — this is the DID→profile mapping.
- **Caller number = `sip.phoneNumber`** participant attribute → `record.caller_number` (feeds reschedule/cancel-by-number and take-a-message callback).
- **Persist in the shutdown hook**, off the spoken-turn hot path; hang-ups still record an `ABANDONED` call.

---

## 5. Phase 4 — Validate voice locally (no phone yet)

- `uv run agent.py console` — talk to the agent through your terminal mic/speakers; fastest voice loop check.
- `uv run agent.py dev` — connect to a LiveKit project and test in the Agents Playground / a web client.
- Success bar: a spoken HVAC call books against the fake calendar, greeting plays <1s, email is read back and confirmed, `CallRecord` finalizes on hang-up. (Reuse the e2e assertions as the behavioral spec.)

---

## 6. Phase 5 — Real integrations (parallelizable; each optional for the first call)

- **`GoogleCalendarService`** implementing `CalendarService` (service account, one calendar per profile; add caller email as attendee so Google sends the invite). **Note:** `Booking.slot` is a human string today — real calendar events need `start`/`end` datetimes + a business timezone; evolve `Booking`/`CalendarService` when you wire this. MVP can ship on `FakeCalendarService`.
- **`services/notify.py`** — owner summary email with the signed `share_path()` hardlink.
- **Durable persistence** — swap `persistence/memory.py` for Postgres/CockroachDB (`CallRepository` interface already exists) so records survive restarts and feed the dashboard.
- **Recording** — LiveKit Egress → `record.recording_url` (optional).
- **Web dashboard** (FastAPI + React per `lld.md` §8) — separate deployable; not on the SIP critical path.

---

## 7. Phase 6 — SIP wiring (LiveKit)

Use **LiveKit Cloud** (managed SIP — fastest) or self-host (`livekit-server` + Redis + `sip` service). Then:

1. **Get a DID** — LiveKit Phone Numbers, or a third-party elastic SIP trunk (Twilio/Telnyx/Sinch) pointed at LiveKit's SIP URI.
2. **Inbound trunk** (`inbound-trunk.json`) — one per DID:
   ```json
   { "trunk": { "name": "HVAC line", "numbers": ["+16045550001"] } }
   ```
   `lk sip inbound create inbound-trunk.json`
3. **Dispatch rule** (`dispatch-rule.json`) — routes each caller to their own room **and** dispatches our named agent with the profile in metadata:
   ```json
   {
     "dispatch_rule": {
       "name": "HVAC inbound",
       "trunk_ids": ["<hvac_trunk_id>"],
       "rule": { "dispatchRuleIndividual": { "roomPrefix": "hvac-call-" } },
       "roomConfig": {
         "agents": [{ "agentName": "receptionist",
                      "metadata": "{\"profile_id\":\"hvac\"}" }]
       }
     }
   }
   ```
   `lk sip dispatch create dispatch-rule.json`
4. **More profiles = more (trunk, rule) pairs** — the restaurant DID gets its own rule with `"profile_id":"restaurant"`. That JSON *is* the DID→profile routing table.
5. Place a test call to the DID → LiveKit creates the room, dispatches `receptionist`, our worker reads `profile_id`, and answers.

---

## 8. Phase 7 — The Dockerfile

Canonical uv-based image, with the model-download step added so containers start cold-fast (silero VAD / turn-detector weights baked in):

```dockerfile
# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.13
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS base
ENV PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1

FROM base AS build
RUN apt-get update && apt-get install -y gcc g++ python3-dev && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked
COPY . .
RUN uv run agent.py download-files          # bake VAD / turn-detector weights into the image

FROM base
ARG UID=10001
RUN adduser --disabled-password --gecos "" --home /app --shell /sbin/nologin --uid ${UID} appuser
WORKDIR /app
COPY --from=build --chown=appuser:appuser /app /app
USER appuser
CMD ["uv", "run", "agent.py", "start"]
```

Notes:
- **No inbound ports.** The worker dials *out* to LiveKit over WebSocket; SIP media terminates at LiveKit's SIP service, not in this container. It needs outbound access to LiveKit + GCP + Gemini.
- **On LiveKit Cloud**, don't bake `LIVEKIT_URL/API_KEY/API_SECRET` — Cloud injects them; use its secrets manager for `GOOGLE_API_KEY` and the service-account JSON. **Self-managed**, provide them as env/secrets.
- Prefer a fixed `CMD ... start` (no wrapper script) so LiveKit's graceful **drain** on SIGTERM works.

---

## 9. Phase 8 — Deploy & operate

- **Fastest:** `lk agent create` / `lk agent deploy` — LiveKit Cloud builds this Dockerfile and runs the worker managed, with autoscaling and secret injection.
- **Self-managed:** run the image on Fly/Render/ECS/K8s with `LIVEKIT_*` + `GOOGLE_*` env; scale **horizontally** (one worker handles several concurrent jobs; add replicas for more). Set resource requests for the audio pipeline.
- **Operate:** structured logs per call/room, drain on deploy (don't cut live calls), and a dashboard/alert on failed dispatch or STT/TTS/LLM errors.
- **Definition of done:** call the DID from a real phone → hear the greeting → book/answer/take-a-message end to end → `CallRecord` persisted → owner gets the summary + share link.

---

## Environment & secrets checklist

| Var | For | Notes |
|---|---|---|
| `LIVEKIT_URL` / `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | worker ↔ LiveKit | injected by LiveKit Cloud; set manually if self-hosting |
| `GOOGLE_API_KEY` | Gemini (LLM) | already in settings |
| `GOOGLE_CREDENTIALS_FILE_PATH` | GCP STT/TTS + Calendar | path to service-account JSON; mount as a secret |
| `RECEPTIONIST_LINK_SECRET` / `RECEPTIONIST_PUBLIC_BASE_URL` | share links | already in settings |

## What you can defer for the first live call
Real Google Calendar (ship on the fake), durable DB (in-memory), recording/Egress, the web dashboard, turn-detector/noise-cancellation plugins, and the second profile. The critical path is: **plugins → worker → local `console` check → SIP trunk+rule → Docker → deploy → dial.**

## Sources
- [Builds and Dockerfiles](https://docs.livekit.io/deploy/agents/builds/) · [Dockerfile example](https://github.com/livekit/agents/blob/main/examples/Dockerfile-example) · [agent-deployment examples](https://github.com/livekit-examples/agent-deployment) · [agent-starter-python](https://github.com/livekit-examples/agent-starter-python)
- [Accepting incoming calls](https://docs.livekit.io/agents/quickstarts/inbound-calls/) · [SIP dispatch rule](https://docs.livekit.io/sip/dispatch-rule/) · [Accepting inbound calls (SIP)](https://docs.livekit.io/sip/accepting-calls/) · [Telephony integration](https://docs.livekit.io/telephony/agents-integration/)
- Verify version-specific APIs (`AgentSession`, raw function tools, plugin kwargs, `download-files`) against the installed `livekit-agents`.
