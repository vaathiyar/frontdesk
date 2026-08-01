# Configuration reference

Every value you can set to run the receptionist.
**Local:** copy `backend/.env.example` → `backend/.env` (auto-loaded).
**Docker / Coolify:** set the same names as container env vars, and mount the
service-account JSON as a file.

## Environment variables

`GOOGLE_*`, `LIVEKIT_*` and `TELNYX_*` keep their standard names; app settings use the
`RECEPTIONIST_` prefix.

| Variable | What it does | Where to get it |
|---|---|---|
| `GOOGLE_API_KEY` | Gemini API key — the reasoning model | [Google AI Studio](https://aistudio.google.com/apikey) → *Create API key* |
| `GOOGLE_CREDENTIALS_FILE_PATH` | Path to the GCP **service-account JSON** used for Cloud Speech-to-Text, Text-to-Speech and Calendar | Cloud Console → *IAM → Service Accounts → Keys* (JSON). Enable the Speech-to-Text, Text-to-Speech and Calendar APIs, and share each calendar with the service account's email as "Make changes to events" |
| `LIVEKIT_URL` | Your `livekit-server` URL (`wss://…`, or `ws://…` locally) | Your LiveKit deployment |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | LiveKit credentials | Your `livekit-server` key config |
| `TELNYX_API_KEY` | Sends the confirmation text. **Required — the worker refuses to start without it**, because a text that never goes out is only ever a log line | Telnyx portal → *API Keys* (a V2 key) |
| `TELNYX_FROM_NUMBER` | Fallback sender, optional. Real calls send from the DID that was dialled. **Must be E.164 if set**, or startup fails | Telnyx portal. Every sending number — each DID included — **must be assigned to a messaging profile**, or sends fail `40300 Forbidden` |
| `RECEPTIONIST_CALENDAR_IDS` | JSON map `profile_id` → Google Calendar ID. **Every registered profile needs one** — the worker refuses to start otherwise; there is no in-memory fallback. Example: `{"hvac":"abc@group.calendar.google.com"}` | Google Calendar → *Settings → Integrate calendar → Calendar ID*, one per profile |
| `RECEPTIONIST_TIMEZONE` | IANA timezone all booking arithmetic happens in (default `America/Vancouver`) | You choose |
| `RECEPTIONIST_PROFILE` | Profile for `agent.py console`/`dev` when there is no SIP metadata (default `hvac`) | `hvac` \| `restaurant` |
| `RECEPTIONIST_PUBLIC_BASE_URL` | Base URL for the link in each text. **Must be reachable from a phone** — `localhost` is useless there. Baked in at send time, so changing it does not repair links already sent | Your public URL, or a `cloudflared tunnel` for a demo |
| `RECEPTIONIST_LINK_SECRET` | HMAC key signing those links. The worker and the web service **must share one**, or every link already texted 404s | You generate (random string) |
| `RECEPTIONIST_DATABASE_PATH` | The SQLite file both processes use (default `calls.db`; `/data/calls.db` in the image) | You choose; in Docker it must sit on the shared volume |

> `RECEPTIONIST_CALENDAR_IDS` is a dict, and pydantic-settings **merges** dict fields
> across sources — setting it to `{}` in the shell will *not* override what's in `.env`.
> Use `scripts/chat.py --fake-calendar` to force the fake for a single run.

## Phone / SIP

Set in `backend/deploy/sip/*.json`, applied with `backend/deploy/sip/setup.sh`.

| Field | File | What it does | Where to get it |
|---|---|---|---|
| `trunk.numbers` | `inbound-trunk-*.json` | The DID(s) this trunk answers | Your telephony provider (Telnyx, …) |
| `dispatch_rule.trunk_ids` | `dispatch-rule-*.json` | Links the rule to its trunk | The `ST_…` id printed by `lk sip inbound create` |
| `…roomConfig.agents[].metadata` → `{"profile_id":"…"}` | `dispatch-rule-*.json` | **The DID → profile mapping** | `hvac` \| `restaurant` |
| `…rule.dispatchRuleIndividual.roomPrefix` | `dispatch-rule-*.json` | Per-caller room name prefix (cosmetic) | You choose |
| `…roomConfig.agents[].agentName` | `dispatch-rule-*.json` | Must match `AGENT_NAME` in `worker/voice/session.py` | Fixed: `receptionist` |

## Set in code, not the environment

These are wired to what the rest of the pipeline expects — a wrong value is a broken call,
not a tuning preference.

| Constant(s) | File | What it does |
|---|---|---|
| `CHAT_MODEL`, `CHAT_EFFORT`, `CHAT_MAX_TOKENS` | `worker/agent/graph.py` | Gemini model, thinking level, output ceiling |
| `MAX_TOOL_ROUNDS`, `RECURSION_LIMIT` | `worker/agent/graph.py` | Cap on tool rounds per turn. Must be passed explicitly — LangGraph's own default is effectively unlimited |
| `STT_MODEL`, `STT_LOCATION`, `STT_LANGUAGES` | `worker/voice/speech.py` | Speech-to-Text model, region, language |
| `TTS_MODEL`, `TTS_VOICE` | `worker/voice/speech.py` | Text-to-Speech model and voice |
| `OPEN_HOUR`, `CLOSE_HOUR`, `SLOT_MINUTES`, `APPOINTMENT_MINUTES` | `worker/booking/service.py` | Default bookable hours, slot spacing, appointment length |
| `TOKEN_LENGTH` | `worker/lib/links.py` | Signed-link token length — short enough to keep a text to one segment |

Per-business hours are **not** these constants: a profile sets its own `opens`/`closes`
(see `worker/profiles/restaurant.py`, which serves dinner only), and they have to match the hours
stated in that profile's `knowledge`, or the agent offers times the calendar then refuses.
