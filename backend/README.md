# AI Receptionist — Backend

One engine, swappable **call profiles**. A caller reaches the agent, which books /
reschedules / cancels an appointment on the same call, answers questions about the
business, or takes a message — and produces one `CallRecord` (transcript, decision
timeline, outcome, booking) that the email summary and web detail view both read.

The same brain answers behind **two drivers**: a **voice** path (LiveKit —
VAD ▸ STT ▸ LLM ▸ TTS on a real phone call) and a **text** path (the dev REPL and
the test suites). The prompt and the six tools live in one place, so what you iterate
on in text is exactly what answers the phone.

Design & rationale: **[`../docs/lld.md`](../docs/lld.md)**. Voice + telephony delivery plan: [`../docs/voice_livekit_sip_plan.md`](../docs/voice_livekit_sip_plan.md). Requirements: [`../docs/poc_requirements_p0.md`](../docs/poc_requirements_p0.md).

> All commands below run from this `backend/` directory.

## Status

The **brain + dev harness** are done and tested with no network: the profile engine,
the six tools, the tool-use loop, a text REPL, and an offline unit suite plus a live
LLM e2e suite. The **voice stack** (LiveKit worker + Google STT/TTS + Silero VAD) is
now wired around that same brain — talk to it locally with `agent.py console`, or point
it at your self-hosted LiveKit for real phone calls (see [Running the agent](#running-the-agent)).

Still deferred (and designed in [`../docs/lld.md`](../docs/lld.md)): the real
`GoogleCalendarService` (today it runs on a seeded fake), the owner-notification email,
durable CockroachDB persistence, and the web app.

## Quickstart

```bash
uv sync                      # create .venv, install deps
uv run pytest -q             # 36 tests, no network, no API key needed

# To chat with the agent you need a Google API key (Gemini):
export GOOGLE_API_KEY=...                # or set it in .env
uv run python scripts/chat.py hvac      # also: restaurant
```

Type as the caller. On exit the harness prints the resulting `CallRecord` — outcome,
captured fields, the code-emitted decision timeline, and the signed share link:

```
caller> my furnace quit, can someone come Tuesday morning?
agent>  I can help with that. ...
...
────────────────────────────────────────────────────────────────
  CallRecord 3f2a…   profile: hvac   caller: +1-555-0100
  outcome: booked
  booking: furnace repair @ Tuesday 10:00 AM  (evt_1a2b3c4d)
  fields:  name='Sam Lee', address='12 Oak St', issue='no heat', email='sam@example.com'
  decision timeline:
    • availability_checked: Tuesday: 10:00 AM, 1:00 PM, 3:00 PM
    • booking_created: furnace repair — Tuesday 10:00 AM
  share link: /c/3f2a…?t=…
```

The fake calendar seeds **tomorrow 8:00 AM as busy**, so ask for it to watch the agent
decline and offer another time — and note it never claims a booking the tool didn't make.

## Running the agent

The text REPL above is the fast inner loop; the LiveKit worker (`agent.py`) is the
voice path. Both drive the same brain — pick a mode:

| Command | What it does | Needs |
|---|---|---|
| `uv run python scripts/chat.py hvac` | Text REPL — type as the caller, no telephony | `GOOGLE_API_KEY` |
| `uv run pytest -q` | Offline unit suite (36 tests, no network) | — |
| `uv run pytest -m e2e -s` | Live LLM e2e — simulated caller against real Gemini | `GOOGLE_API_KEY` |
| `uv run agent.py console` | **Local voice** — talk through your mic/speakers | Google (key + JSON) |
| `uv run agent.py dev` | Connect to your self-hosted LiveKit; test in a browser/room | Google + `LIVEKIT_*` |
| `uv run agent.py start` | Production worker | Google + `LIVEKIT_*` |

### Local voice (recommended first test)

`uv run agent.py console` runs the whole pipeline — Silero VAD, Google Cloud STT/TTS,
Gemini reasoning — locally against your mic and speakers, with **no LiveKit server
required**. Set `RECEPTIONIST_PROFILE=restaurant` to try the other profile (default
`hvac`). It needs both Google credentials: `GOOGLE_API_KEY` (Gemini) and
`GOOGLE_CREDENTIALS_FILE_PATH` (a GCP service-account JSON with Cloud
Speech-to-Text + Text-to-Speech enabled).

### Against your self-hosted LiveKit

This is **not** LiveKit Cloud — you run `livekit-server` + `livekit-sip` yourself
(e.g. on Hetzner via Coolify). The worker dials *out* to it using `LIVEKIT_URL` /
`LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET`:

- `uv run agent.py dev` — connect and test from a browser/room.
- `uv run agent.py start` — the production worker command.

### Phone / SIP

On your LiveKit server, configure a SIP **inbound trunk** + **dispatch rule** per DID
(see [`deploy/sip/`](deploy/sip/) and [`deploy/README.md`](deploy/README.md)).
The DID's dispatch rule carries `{"profile_id":"hvac"}` metadata that selects the
profile, and the worker reads the caller's number from the `sip.phoneNumber` participant
attribute. Adding a profile = one more (trunk, rule) pair.

### Docker

Build from this directory, then run with the env vars set and the service-account JSON
mounted (see [`deploy/README.md`](deploy/README.md)):

```bash
docker build -t receptionist-agent .
```

The same image deploys in Coolify next to LiveKit. The worker needs **outbound network
only** — no inbound ports (SIP media terminates at LiveKit, not in the container).

## Environment variables

Local runs read `.env` automatically; copy [`.env.example`](.env.example) as the
starting template.

| Var | Purpose |
|---|---|
| `GOOGLE_API_KEY` | Gemini (the reasoning LLM) |
| `GOOGLE_CREDENTIALS_FILE_PATH` | Path to a GCP service-account JSON with Cloud Speech-to-Text + Text-to-Speech enabled (voice STT/TTS) |
| `LIVEKIT_URL` | Your self-hosted livekit-server URL (`wss://` prod, `ws://` local) |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit API credentials |
| `RECEPTIONIST_PROFILE` | Profile for local `agent.py console` when there's no SIP metadata (default `hvac`) |
| `RECEPTIONIST_LINK_SECRET` / `RECEPTIONIST_PUBLIC_BASE_URL` | Signed share-link config |

### Google auth: two distinct mechanisms

The two Google credentials are **not** interchangeable. Gemini (reasoning) uses the
`GOOGLE_API_KEY`; Cloud STT/TTS use the service-account JSON pointed to by
`GOOGLE_CREDENTIALS_FILE_PATH`. Voice needs **both**. If `agent.py console` fails with
an auth error on STT/TTS, it's the service account — not the API key.

## Add a profile

The extension model in one file — no engine changes:

```python
# src/receptionist/profiles/dental.py
class DentalReceptionist(Receptionist):
    profile_id = "dental"
    business_name = "Riverside Dental"
    greeting = "Thanks for calling Riverside Dental!"

    def domain_prompt(self) -> str: ...  # role, services, tone
    def booking_fields(self) -> list[Field]:
        return [NAME, ..., EMAIL]

    def knowledge(self) -> str: ...  # facts for answer_question
```

Then one line in `src/receptionist/profiles/factory.py`: `"dental": DentalReceptionist`.
To answer a real phone line with it, add one more SIP (trunk, dispatch-rule) pair on
your LiveKit server (see [Running the agent](#running-the-agent)).

## Layout

```
agent.py          LiveKit voice worker — the entrypoint you run (console | dev | start)
src/receptionist/
  core/        CallRecord + repository interface + links + settings   (shared contract)
  profiles/    Receptionist base + hvac/restaurant + factory          (extension surface)
  services/    CalendarService interface + seeded FakeCalendarService
  agent/       ConversationRunner (text driver) + ReceptionistAgent   (LiveKit voice adapter)
  providers/   Gemini chat adapter + Google STT/TTS + Silero VAD — the one place that names a vendor
  persistence/ InMemoryCallRepository (CockroachDB later)
scripts/chat.py   the text dev REPL
tests/            offline coverage (fake calendar + fake LLM) + live e2e (test_e2e.py)
```

## Quality

```bash
uv run ruff check . && uv run ruff format --check .
uv run mypy
uv run pytest
```
