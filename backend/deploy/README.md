# Deploying the receptionist

Two processes from one image, against your **own** self-hosted LiveKit
(`livekit-server` + `livekit-sip`) — not LiveKit Cloud.

```
caller dials a DID
   -> livekit-sip answers (inbound trunk matches the DID)
   -> a dispatch rule creates a room and dispatches agent "receptionist"
      with metadata {"profile_id": "hvac"}
   -> the WORKER picks up the job, reads the profile from that metadata and the
      caller's number from the sip.phoneNumber attribute, and runs the call
   -> on hang-up it saves the call and texts the caller a link
   -> the WEB service serves that link
```

The worker **dials out** and opens no inbound ports. The web service is the only thing
that needs to be reachable — and it genuinely does, because the link in the text is
useless if a phone can't open it.

```
deploy/
  README.md                     <- you are here
  docker-compose.yml            worker + web, sharing a SQLite volume
  docker-compose.livekit.yml    a throwaway local LiveKit, for dev only
  livekit.yaml                  its config (trivial committed key — dev only)
  sip/
    inbound-trunk-hvac.json         DID  -> HVAC trunk
    inbound-trunk-restaurant.json   DID  -> Restaurant trunk
    dispatch-rule-hvac.json         trunk -> receptionist + {"profile_id":"hvac"}
    dispatch-rule-restaurant.json   trunk -> receptionist + {"profile_id":"restaurant"}
    setup.sh                        provisions the above with the lk CLI
```

## Prerequisites

- A running **livekit-server** and **livekit-sip**, reachable over `wss://` and SIP/RTP.
- A **DID** your telephony provider routes to livekit-sip.
- A **GCP service account** with Cloud Speech-to-Text, Text-to-Speech and Calendar enabled.
- A **Gemini API key**.
- A **Telnyx** number assigned to a messaging profile, for the confirmation text.
- The **`lk` CLI** for SIP provisioning — <https://docs.livekit.io/home/cli/>

## 1. Both services

```bash
cd backend
SA_JSON=/abs/path/to/service-account.json \
  docker compose -f deploy/docker-compose.yml up -d --build

docker compose -f deploy/docker-compose.yml logs -f
docker compose -f deploy/docker-compose.yml down
```

Everything except the credential path goes in `backend/.env`. `SA_JSON` is required and
points at the service-account JSON **on the host**; compose mounts it read-only at
`/secrets/sa.json` and sets `GOOGLE_CREDENTIALS_FILE_PATH` to that path. Don't put that
variable in `.env` — the host path is not the container path.

Three settings have to agree across the two services, and `.env` is what makes them:

| | why it matters |
|---|---|
| `RECEPTIONIST_DATABASE_PATH` | Both mount the `calls` volume at `/data`. The image defaults this to `/data/calls.db`; override it and they stop sharing calls. |
| `RECEPTIONIST_LINK_SECRET` | Signs the links. If the two disagree, **every link already texted 404s**. Set a real value — the default is a placeholder. |
| `RECEPTIONIST_PUBLIC_BASE_URL` | Baked into each text at send time. Must be the address a phone can reach, not `localhost`. Changing it does not fix links already sent. |

Model weights (Silero VAD) are baked in at build time, so containers start cold-fast.

### Putting the web service on the internet

The page is HTTP on port 8000 with no TLS of its own — put it behind whatever already
terminates TLS for you (Coolify, Caddy, nginx). It serves exactly two routes: `/healthz`
and `/c/{id}`, and every unauthorised request to the latter returns one identical 404 so
the response can't be used to discover which call ids exist.

For a quick demo without a domain:

```bash
cloudflared tunnel --url http://localhost:8000
```

Then set `RECEPTIONIST_PUBLIC_BASE_URL` to the tunnel URL **before** placing calls.

### On Coolify

Deploy the same image twice next to your LiveKit stack — once with
`uv run agent.py start`, once with `uv run serve.py`. Give both the same volume and env,
add the service-account JSON as a file mount, and expose a domain for the web one only.
Scale the worker by adding replicas; one worker handles several concurrent calls.

## 2. SIP: one DID per profile

The **DID → profile mapping lives in each dispatch rule's
`roomConfig.agents[].metadata`.** That is the whole routing table.

- `+16045550001` → `hvac-call-*` → `{"profile_id":"hvac"}`
- `+16045550002` → `restaurant-call-*` → `{"profile_id":"restaurant"}`

The numbers in `sip/inbound-trunk-*.json` are **placeholders** — replace them with your
real DIDs in E.164, matching what your provider delivers to livekit-sip.

```bash
cd backend
bash deploy/sip/setup.sh
```

The first run creates the trunks and prints their IDs (`ST_...`). Paste each into the
matching `dispatch-rule-*.json` `trunk_ids`, then re-run to create the rules.

`agentName` in every rule is `receptionist` and must match the worker's registered name
(`AGENT_NAME` in `agent/worker.py`). **The worker must be running for dispatch to attach
it to a call.**

Adding a profile: one more trunk + rule pair with the new `profile_id`, plus the profile
registered in `src/receptionist/profiles/__init__.py`.

> **Explicit dispatch, not automatic.** Because the worker registers with an
> `agent_name`, joining a room does *not* summon it — a dispatch rule (or an explicit
> dispatch) must ask for it by name. That is what lets one worker serve several DIDs as
> different businesses, but it also means `agent.py dev` plus a browser will sit idle
> until something dispatches. Use `agent.py console` to exercise audio without SIP.

## 3. The confirmation text

Unset Telnyx credentials mean the text is composed and recorded as `sms_skipped` rather
than sent, which is what keeps the REPL and the tests from messaging anyone. To actually
send:

1. Buy a number with SMS enabled and **assign it to a messaging profile** in the Telnyx
   portal. Skipping that step is the common failure: `40300 Forbidden — the from number is
   not assigned to a messaging profile`.
2. Set `TELNYX_API_KEY` (a V2 key) and `TELNYX_FROM_NUMBER`.

Canada → Canada on a Canadian long code needs no A2P/10DLC registration. Sending to **US**
numbers does; a sole-proprietor brand is ~$22 and usually approved same day. `+1 (xxx)
555-01xx` is refused by the code regardless — it's the reserved fictional range.

## Local LiveKit for development

`docker-compose.livekit.yml` runs a single-node throwaway server so `agent.py dev` has
something to register with. **Development only** — the committed `apk`/`123` key is
worthless, and livekit-server logs `secret is too short` and starts anyway.

```bash
docker compose -f deploy/docker-compose.livekit.yml up -d
LIVEKIT_URL=ws://127.0.0.1:7880 LIVEKIT_API_KEY=apk LIVEKIT_API_SECRET=123 \
  uv run agent.py dev
docker compose -f deploy/docker-compose.livekit.yml down
```

It uses host networking so WebRTC's UDP media range is reachable. A browser on Windows
hitting a WSL2 container gets TCP localhost forwarding but not the UDP range, so media
would have to fall back to ICE/TCP on 7881 — untested. `agent.py console` remains the
reliable way to hear the agent.

## References

- [Self-hosting](https://docs.livekit.io/home/self-hosting/) ·
  [SIP](https://docs.livekit.io/sip/) ·
  [Dispatch rules](https://docs.livekit.io/sip/dispatch-rule/) ·
  [Builds & Dockerfiles](https://docs.livekit.io/deploy/agents/builds/)
- [Telnyx: send a message](https://developers.telnyx.com/docs/messaging/messages/send-message)
