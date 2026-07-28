# Configuration reference

Every value you can set to run the receptionist.
**Local:** copy `backend/.env.example` → `backend/.env` (auto-loaded).
**Docker / Coolify:** set the same names as container env vars, and mount the
service-account JSON as a file.

## Environment variables

`GOOGLE_*` and `LIVEKIT_*` keep their standard names; app settings use the
`RECEPTIONIST_` prefix.

| Variable | Where set | What it does | Where to get it |
|---|---|---|---|
| `GOOGLE_API_KEY` | `.env` / container env | Gemini API key — the reasoning LLM | [Google AI Studio](https://aistudio.google.com/apikey) → *Create API key* |
| `GOOGLE_CREDENTIALS_FILE_PATH` | `.env` (a path) / mounted secret | Path to the GCP **service-account JSON** used for Cloud Speech-to-Text, Text-to-Speech, and Calendar | Google Cloud Console → *IAM → Service Accounts → Keys* (JSON). Enable the Speech-to-Text, Text-to-Speech & Calendar APIs on the project |
| `LIVEKIT_URL` | `.env` / container env | Your self-hosted `livekit-server` URL (`wss://…`, or `ws://…` locally) | Your LiveKit deployment (Coolify/Hetzner) |
| `LIVEKIT_API_KEY` | `.env` / container env | LiveKit API key | Your `livekit-server` key config |
| `LIVEKIT_API_SECRET` | `.env` / container env | LiveKit API secret | Your `livekit-server` key config |
| `RECEPTIONIST_CALENDAR_IDS` | `.env` / container env | JSON map `profile_id` → Google Calendar ID. A profile that's omitted uses the in-memory fake (bookings **not** written to Google). Example: `{"hvac":"abc@group.calendar.google.com"}` | Google Calendar → the calendar's *Settings → Integrate calendar → Calendar ID*, one per profile |
| `RECEPTIONIST_TIMEZONE` | `.env` / container env | IANA timezone for interpreting spoken day/time and creating events (default `America/Vancouver`) | You choose (IANA tz name) |
| `RECEPTIONIST_PROFILE` | `.env` / container env | Profile for `agent.py console`/`dev` when there's no SIP metadata (default `hvac`) | You choose: `hvac` \| `restaurant` |
| `RECEPTIONIST_LINK_SECRET` | `.env` / container env | HMAC key signing shareable call-detail links (change in prod) | You generate (random string) |
| `RECEPTIONIST_PUBLIC_BASE_URL` | `.env` / container env | Base URL used to build share links (default `http://localhost:8000`) | You choose (your public URL) |

## Phone / SIP

Set in `backend/deploy/sip/*.json`, applied to your server with
`backend/deploy/sip/setup.sh`.

| Field | File | What it does | Where to get it |
|---|---|---|---|
| `trunk.numbers` | `inbound-trunk-*.json` | The DID(s) this trunk answers | Your telephony/SIP provider (Twilio, Telnyx, …) or a LiveKit phone number |
| `dispatch_rule.trunk_ids` | `dispatch-rule-*.json` | Links the rule to its inbound trunk | The `ST_…` id printed by `lk sip inbound create` |
| `…roomConfig.agents[].metadata` → `{"profile_id":"…"}` | `dispatch-rule-*.json` | **The DID → profile mapping** | You choose: `hvac` \| `restaurant` |
| `…rule.dispatchRuleIndividual.roomPrefix` | `dispatch-rule-*.json` | Per-caller room name prefix (cosmetic) | You choose |
| `…roomConfig.agents[].agentName` | `dispatch-rule-*.json` | Must stay `receptionist` (matches the worker) | Fixed |

## Advanced — set in code (not env vars)

| Constant(s) | File | What it does |
|---|---|---|
| `CHAT_MODEL`, `CHAT_EFFORT`, `CHAT_MAX_TOKENS` | `src/receptionist/agent/runner.py` | Gemini model, thinking level, max output tokens |
| `STT_MODEL`, `STT_LOCATION` | `src/receptionist/providers/factory.py` | Speech-to-Text model & region |
| `TTS_MODEL`, `TTS_VOICE` | `src/receptionist/providers/factory.py` | Text-to-Speech model & voice |
| `VAD` | `src/receptionist/providers/factory.py` | Voice-activity detector (Silero) |
| `OPEN_HOUR`, `CLOSE_HOUR`, `SLOT_MINUTES`, `APPOINTMENT_MINUTES` | `src/receptionist/services/google_calendar.py` | Bookable hours, slot granularity, appointment length |
