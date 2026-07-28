# Deploying the Receptionist voice agent (self-hosted LiveKit)

This directory holds everything needed to deploy the **receptionist** LiveKit voice
agent against your **own** self-hosted LiveKit — `livekit-server` + `livekit-sip`
running on Hetzner via Coolify — **not** LiveKit Cloud.

How a call flows:

```
caller dials a DID
   -> your livekit-sip answers (inbound trunk matches the DID)
   -> a SIP dispatch rule creates a room and dispatches the "receptionist" agent
      with job metadata {"profile_id": "hvac" | "restaurant"}
   -> the worker container (this image) — already connected to livekit-server —
      picks up the job, reads the profile from metadata and the caller number from
      the `sip.phoneNumber` participant attribute, and runs the call.
```

The worker **dials out** to livekit-server over a WebSocket and registers under the
agent name `receptionist` (explicit dispatch). It opens **no inbound ports**.

```
deploy/
  README.md                          <- you are here
  docker-compose.agent.yml           runs JUST this worker (loads ../.env, mounts SA JSON)
  sip/
    inbound-trunk-hvac.json          DID  -> HVAC inbound trunk
    inbound-trunk-restaurant.json    DID  -> Restaurant inbound trunk
    dispatch-rule-hvac.json          trunk -> receptionist + {"profile_id":"hvac"}
    dispatch-rule-restaurant.json    trunk -> receptionist + {"profile_id":"restaurant"}
    setup.sh                         provisions the above via the lk CLI
```

## Prerequisites

- A running **livekit-server** and **livekit-sip** on your infra (Hetzner/Coolify),
  reachable over `wss://` for the worker and SIP/RTP for calls.
- The **`lk` CLI** — https://docs.livekit.io/home/cli/
- A **GCP service account** JSON with **Cloud Speech-to-Text** and **Text-to-Speech**
  enabled (used by the voice STT/TTS).
- A **Gemini API key** (the agent's brain).
- A **DID** (phone number) that your telephony/SIP provider routes to your
  livekit-sip service.
- **Docker** to build and run the worker image.

## 1. Build the worker image

Build context is `backend/` (the directory above this one):

```bash
cd backend
docker build -t receptionist-agent .
```

Model weights (Silero VAD + any turn detector) are baked in at build time, so cold
starts are fast.

## 2. Run the worker

The worker needs these environment variables:

| var | purpose |
|-----|---------|
| `LIVEKIT_URL` | `wss://` URL of your livekit-server |
| `LIVEKIT_API_KEY` / `LIVEKIT_API_SECRET` | credentials for that server |
| `GOOGLE_API_KEY` | Gemini API key |
| `GOOGLE_CREDENTIALS_FILE_PATH` | path (inside the container) to the GCP service-account JSON |
| `RECEPTIONIST_*` | the app settings (link secret, public base URL, ...) |

Put the non-path vars in `backend/.env`, mount the service-account JSON as a file,
and point the credential vars at the mounted path:

```bash
docker run --rm \
  --env-file .env \
  -v /abs/path/to/service-account.json:/secrets/sa.json:ro \
  -e GOOGLE_CREDENTIALS_FILE_PATH=/secrets/sa.json \
  receptionist-agent
```

> **Two distinct Google credentials.** Gemini (the LLM) authenticates with
> `GOOGLE_API_KEY`; Cloud Speech-to-Text, Text-to-Speech, and Calendar authenticate with
> the service-account JSON at `GOOGLE_CREDENTIALS_FILE_PATH` — the app passes that path to
> the Google clients directly. The `-e` flag overrides whatever host path `.env` carries
> with the in-container mount path.

The container needs **outbound** network only — it opens no inbound ports and needs
no published ports, domain, or HTTP health check. It dials your livekit-server; you
never route traffic to it.

### Run the worker with compose

[`docker-compose.agent.yml`](docker-compose.agent.yml) runs **just this worker** (not
LiveKit): it builds/uses the `receptionist-agent` image, loads `../.env`, mounts your
service-account JSON read-only at `/secrets/sa.json`, points
`GOOGLE_CREDENTIALS_FILE_PATH` at it, sets `restart: unless-stopped`, and publishes no
ports. Point `SA_JSON` at the JSON on the host and bring it up from `backend/`:

```bash
cd backend
SA_JSON=/abs/path/to/service-account.json \
  docker compose -f deploy/docker-compose.agent.yml up -d --build
```

```bash
docker compose -f deploy/docker-compose.agent.yml logs -f    # tail logs
docker compose -f deploy/docker-compose.agent.yml down       # stop + remove
```

`SA_JSON` is required — compose refuses to start without it rather than silently mount an
empty path. Put everything else (`LIVEKIT_*`, `GOOGLE_API_KEY`, `RECEPTIONIST_*`) in
`backend/.env`; do **not** put `GOOGLE_CREDENTIALS_FILE_PATH` there, the compose file
sets it to the in-container mount path.

### On Coolify

Deploy this same image as a service next to your LiveKit stack:

- Set the env vars above in the Coolify service.
- Add the service-account JSON as a **file mount / secret** and set
  `GOOGLE_CREDENTIALS_FILE_PATH` to its path.
- No ports or domains are required (it's a worker, not a server). Scale by running
  more replicas of the same image.

## 3. Provision SIP (DID -> profile)

Two DIDs map to two profiles. Each DID is an **inbound trunk**; each trunk has a
**dispatch rule** that creates a per-caller room and dispatches the `receptionist`
agent with the profile in the job metadata:

- `+16045550001` -> `hvac-call-*` room -> `{"profile_id":"hvac"}`
- `+16045550002` -> `restaurant-call-*` room -> `{"profile_id":"restaurant"}`

(The numbers in `sip/inbound-trunk-*.json` are **placeholders** — replace them.)

Steps:

1. Edit the `numbers` in `sip/inbound-trunk-*.json` to your real DIDs (E.164). They
   **must** match the DIDs your provider delivers to livekit-sip.
2. Point the `lk` CLI at your self-hosted server (env vars or `lk project add` — see
   the script header).
3. Run it (twice — the script guides you):

```bash
cd backend
bash deploy/sip/setup.sh
```

The first run creates the trunks and prints their IDs (`ST_...`). Paste each ID into
the matching `dispatch-rule-*.json` `trunk_ids`, then re-run to create the rules and
list everything.

> **The DID -> profile mapping lives in each dispatch rule's
> `roomConfig.agents[].metadata`.** To add a profile (e.g. `dental`): add a new
> `inbound-trunk-dental.json` (its DID) and a new `dispatch-rule-dental.json`
> (`roomPrefix`, the new trunk id, and `metadata: {"profile_id":"dental"}`), then
> create them with `lk sip inbound create` / `lk sip dispatch create`. The worker
> must also have a matching profile registered in
> `src/receptionist/profiles/factory.py`.

> `agentName` in every dispatch rule is `receptionist` and must match the worker's
> registered `agent_name`. The worker must be **running** for dispatch to attach it
> to a call.

---

## OPTIONAL — a fully-local LiveKit stack for end-to-end testing

> You already run livekit-server + livekit-sip on Hetzner via Coolify. **This section
> is only for spinning up a throwaway local stack** to test calls end-to-end on your
> machine — skip it for production.

The templates below are distilled from the official guides
([self-hosting](https://docs.livekit.io/home/self-hosting/),
[run locally](https://docs.livekit.io/home/self-hosting/local/), and the SIP server
guide at https://docs.livekit.io/sip/ + https://github.com/livekit/sip). Image tags
and config keys evolve — check those pages if something does not line up.

Save the two files below into `deploy/`, then:

```bash
docker compose -f deploy/docker-compose.livekit.yml up
```

**`deploy/livekit.yaml`**

```yaml
# LOCAL TESTING ONLY
port: 7880
rtc:
  tcp_port: 7881
  port_range_start: 50000
  port_range_end: 60000
  use_external_ip: false
keys:
  devkey: secret          # matches the SIP config + the agent .env below
redis:
  address: 127.0.0.1:6379
```

**`deploy/docker-compose.livekit.yml`**

```yaml
# LOCAL TESTING ONLY — livekit-server + redis + livekit-sip
services:
  redis:
    image: redis:7-alpine
    command: ["redis-server", "--save", "", "--appendonly", "no"]
    ports: ["6379:6379"]

  livekit:
    image: livekit/livekit-server:latest
    command: ["--config", "/etc/livekit.yaml"]
    network_mode: host          # WebRTC media needs host networking
    volumes:
      - ./livekit.yaml:/etc/livekit.yaml:ro
    depends_on: [redis]

  livekit-sip:
    image: livekit/sip:latest
    network_mode: host          # SIP 5060 + RTP 10000-20000 need host networking
    environment:
      SIP_CONFIG_BODY: |
        log_level: debug
        api_key: devkey
        api_secret: secret
        ws_url: ws://127.0.0.1:7880
        redis:
          address: 127.0.0.1:6379
        sip_port: 5060
        rtp_port: 10000-20000
        use_external_ip: true
    depends_on: [livekit, redis]
```

> `network_mode: host` is used so SIP signalling (5060/UDP) and RTP media
> (10000-20000) reach the container; on Linux the host-mode services reach the
> bridged redis at `127.0.0.1:6379`. Docker Desktop on macOS/Windows handles host
> networking differently — see the official guides if you are not on Linux.

Point the agent at the local stack (`backend/.env`):

```
LIVEKIT_URL=ws://127.0.0.1:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secret
GOOGLE_API_KEY=...            # a real key: STT/TTS/Gemini still call Google
```

Then run the worker locally (`uv run agent.py dev`, or the built image), provision
SIP with `deploy/sip/setup.sh` (pointing a softphone/SIP provider at
`127.0.0.1:5060`), and place a test call.

> To exercise just the agent's audio loop without any SIP/DID, use
> `uv run agent.py console` (local mic/speaker) — no LiveKit stack required.

### Official references

- Self-hosting overview & deployment: https://docs.livekit.io/home/self-hosting/
- Run locally: https://docs.livekit.io/home/self-hosting/local/
- SIP server (self-host): https://docs.livekit.io/sip/ and https://github.com/livekit/sip
- `lk` CLI: https://docs.livekit.io/home/cli/
