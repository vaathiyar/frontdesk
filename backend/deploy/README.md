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
  docker-compose.yml            worker + web + one-shot SIP provisioning
  docker-compose.livekit.yml    a throwaway local LiveKit, for dev only
  livekit.yaml                  its config (trivial committed key — dev only)
  sip/
    numbers.json                THE routing table: DID -> profile
    provision.py                applies it to LiveKit; idempotent
```

## Prerequisites

- A running **livekit-server** and **livekit-sip**, reachable over `wss://` and SIP/RTP.
- A **DID** your telephony provider routes to livekit-sip.
- A **GCP service account** with Cloud Speech-to-Text, Text-to-Speech and Calendar enabled.
- A **Gemini API key**.
- A **Telnyx** number assigned to a messaging profile, for the confirmation text.
- **Redis, shared between livekit-server and livekit-sip.** Not optional, even on a single
  node: they are separate processes that coordinate through it, and without it every SIP
  API call fails with `sip not connected (redis required)`.

No `lk` CLI needed — SIP is provisioned by `deploy/sip/provision.py`, which uses the
`livekit-api` package we already depend on.

## 1. Both services

```bash
cd backend
docker compose --env-file .env -f deploy/docker-compose.yml up -d --build

docker compose --env-file .env -f deploy/docker-compose.yml logs -f
docker compose --env-file .env -f deploy/docker-compose.yml down
```

Everything goes in `backend/.env`, `GOOGLE_CREDENTIALS_FILE_PATH` included: the service
account is bind-mounted at the same path inside the container as on the host, so that one
value is right for both the mount and the app, with nothing to keep in sync. It must be
**absolute** — a relative path resolves against `deploy/` for the mount source, and Docker
rejects it outright as a container path.

`--env-file` is not optional, and the reason is a real Compose subtlety: `env_file:` in the
compose file populates each *container's* environment, while `${...}` in that same file is
*interpolation*, resolved earlier and only from the shell or `--env-file`. The mount is
interpolated, so without the flag every command fails with
`required variable GOOGLE_CREDENTIALS_FILE_PATH is missing a value`.

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
put the service-account JSON somewhere on the host and point
`GOOGLE_CREDENTIALS_FILE_PATH` at that absolute path, and expose a domain for the web one
only. Scale the worker by adding replicas; one worker handles several concurrent calls.

Under Coolify's Docker Compose build pack the compose file above works unmodified. Coolify
writes its own `.env` from the UI variables and passes it, which covers interpolation
without the flag; and `env_file: ../.env` is marked `required: false`, so its absence from
the clone — `.env` is gitignored — is skipped rather than fatal, with Coolify's injection
supplying the container environment instead. Set `GOOGLE_CREDENTIALS_FILE_PATH` in the UI
to the absolute host path of the JSON, clear of `/app` and `/data`, which the image and the
`calls` volume already occupy.

## 2. SIP: one DID per profile

Edit one file — `sip/numbers.json` **is** the routing table:

```json
{ "numbers": { "+16042969870": "hvac", "+16042969871": "restaurant" } }
```

The `sip` service in the compose file applies it on `up`. To run it by hand:

```bash
uv run python deploy/sip/provision.py           # apply
uv run python deploy/sip/provision.py --show    # read-only: what's there now
```

For each entry it creates an inbound trunk matching that DID, and a dispatch rule that
puts the caller in their own room and asks LiveKit to dispatch agent `receptionist` with
`{"profile_id": "..."}` as job metadata. **That metadata is how one worker answers as
either business** — the worker reads it from `ctx.job.metadata`.

Idempotent, and `numbers.json` is authoritative: change a number and the next run moves
the trunk. Only objects named `receptionist-<profile>` are ever touched, so a LiveKit
shared with your other applications is left alone. Adding a profile is one more line here,
plus registering it in `src/receptionist/profiles/__init__.py`.

### There is nothing to "connect"

A common confusion: LiveKit's SIP config is **not** a file any process reads. `provision.py`
(like `lk`) is just an API client — it POSTs to livekit-server, which stores the config, and
livekit-sip reads it from there via Redis. `LIVEKIT_URL` + `LIVEKIT_API_KEY` +
`LIVEKIT_API_SECRET` are the entire bridge, which is why it does not matter where the
provisioner runs.

### Two ways this fails silently

**No dispatch rule** → the call connects, a room is created, nobody joins, and the caller
hears silence. `provision.py --show` says so explicitly when rules are missing.

**No worker registered when the call lands** → same symptom. Because the worker registers
with an `agent_name`, dispatch is explicit and there is no auto-join fallback. Confirm
`registered worker {"agent_name": "receptionist", ...}` in the worker log before dialling.

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

`docker-compose.livekit.yml` runs a throwaway stack — redis, livekit-server and
livekit-sip — so `agent.py dev` has somewhere to register and `provision.py` has somewhere
to apply. **Development only:** the committed `apk`/`123` key is worthless, and
livekit-server logs `secret is too short` and starts anyway.

```bash
docker compose -f deploy/docker-compose.livekit.yml up -d

export LIVEKIT_URL=ws://127.0.0.1:7880 LIVEKIT_API_KEY=apk LIVEKIT_API_SECRET=123
uv run python deploy/sip/provision.py     # needs redis up, or "sip not connected"
uv run agent.py dev

docker compose -f deploy/docker-compose.livekit.yml down
```

Host networking, so SIP signalling (5060) and the RTP range are reachable. A browser on
Windows hitting a WSL2 container gets TCP localhost forwarding but not the UDP range, so
media would fall back to ICE/TCP on 7881 — untested. `agent.py console` remains the
reliable way to hear the agent.

## References

- [Self-hosting](https://docs.livekit.io/home/self-hosting/) ·
  [SIP](https://docs.livekit.io/sip/) ·
  [Dispatch rules](https://docs.livekit.io/sip/dispatch-rule/) ·
  [Builds & Dockerfiles](https://docs.livekit.io/deploy/agents/builds/)
- [Telnyx: send a message](https://developers.telnyx.com/docs/messaging/messages/send-message)
