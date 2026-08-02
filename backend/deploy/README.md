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
   -> on hang-up it saves the call and texts the caller a signed link
   -> that link opens the SPA on CloudFront, which reads the call from the WEB
      service over JSON
```

The worker **dials out** and opens no inbound ports. The web service is the only part that
has to be reachable, and it genuinely does: the SPA runs in the caller's browser, so "the
frontend calls the API" means a phone on a mobile network calls it.

Two origins, deliberately: the SPA is static files on CloudFront, the API is this service.
That is a cross-origin setup, so the API needs CORS for the CloudFront origin, and
`RECEPTIONIST_PUBLIC_BASE_URL` must point at **CloudFront** — it is the base the texted
links are built against, and those links have to open the SPA, not raw JSON.

```
backend/
  docker-compose.yaml           worker + web + one-shot SIP provisioning
  deploy/
    README.md                   <- you are here
    docker-compose.livekit.yml  a throwaway local LiveKit, for dev only
    livekit.yaml                its config (trivial committed key — dev only)
    sip/
      numbers.json              THE routing table: DID -> profile
      provision.py              applies it to LiveKit; idempotent
```

The deployed compose file lives beside the Dockerfile, not in here, because Compose
resolves `context:` against the **project directory** — which defaults to the compose
file's own folder locally but which a platform sets for you. Coolify pins it to the
configured base directory, so a compose file in `deploy/` saying `context: ..` builds
correctly by hand and one level too high there, failing with
`open Dockerfile: no such file or directory`. Keeping it at `backend/` makes both agree.
The dev-only LiveKit stack stays here: no platform ever runs it.

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
docker compose up -d --build

docker compose logs -f
docker compose down
```

No `-f` and no `--env-file`: the file is at the default location and nothing in it is
interpolated. Every setting comes from `backend/.env`, which each service loads directly.

### Credentials: one variable, no mount

Set **`GOOGLE_CREDENTIALS_JSON`** to the whole service-account key on a single line.
Nothing is mounted and no file has to exist in the container.

```bash
jq -c . < service-account.json      # what to paste
```

That is the deploy channel because a path is not always mountable. Coolify rejects variable
substitution in a compose volume source outright — the usual `${CREDS}:/secrets/sa.json`
recipe cannot even be expressed — and its single-file mounts have their own long-standing
bug ([#8107](https://github.com/coollabsio/coolify/issues/8107),
[#3375](https://github.com/coollabsio/coolify/issues/3375)). A variable sidesteps all of it.

`GOOGLE_CREDENTIALS_FILE_PATH` still works and is the easier one locally, where the file is
just sitting there. **Inline wins if both are set** — otherwise setting the variable on a
platform would appear to do nothing while a stale `.env` path quietly took precedence. Bad
JSON raises instead of falling back, for the same reason.

Two notes if you do mount a file anyway: compose will not do it for you, so the path must
be one you created inside the container, and the image runs as UID 10001, so that user has
to be able to read it.

In `.env`, leave the JSON **unquoted or single-quoted**. Double quotes break it, and they
break it quietly: the key's own quote characters end the value early, python-dotenv fails
to parse the line, and the variable is simply absent — no error, just credentials that
never arrive. That is the most common way this fails locally.

Three settings have to agree across the services, and `.env` is what makes them:

| | why it matters |
|---|---|
| `RECEPTIONIST_DATABASE_URL` | Every service points at the same CockroachDB cluster. If the worker and the web process disagree, the link in each text resolves against a database the call was never written to. Required — neither starts without it. |
| `RECEPTIONIST_PUBLIC_BASE_URL` | Baked into each text at send time, and it addresses **the SPA**, not this backend. Must be reachable from a phone, not `localhost`. Changing it does not fix links already sent. |
| `RECEPTIONIST_CORS_ORIGINS` | The SPA's origin, as the browser sends it. Wrong here and the page loads but every fetch is blocked. |

Model weights (Silero VAD) are baked in at build time, so containers start cold-fast.

### Putting the web service on the internet

The API speaks plain HTTP on container port 8000 with no TLS of its own — put it behind
whatever already terminates TLS for you (Coolify, Caddy, nginx). The SPA is served
separately by CloudFront and is not this service's problem.

It must be reachable from the public internet, not just from CloudFront: the SPA is
JavaScript running on the caller's phone, so every request originates from that phone.
CloudFront never proxies to it.

Every unauthorised read of a call returns one identical 404 — bad token, malformed id,
unknown call, retired profile all look the same — so responses can't be used to discover
which call ids exist. Keep that property when the routes move to JSON.

The compose file **exposes** 8000 without publishing it, so a proxy can reach it and the
open internet cannot. `docker-compose.override.yaml` publishes it on the host for local
use; Compose merges that automatically for a bare `docker compose up` and skips it when
`-f` names the main file, which is how a platform runs it. The published default is 8001,
to stay out of the way of whatever else is already on 8000 — override with
`WEB_PORT=8010 docker compose up`. The *container* port stays 8000 and can never collide,
since each container has its own network namespace.

For a quick demo without a domain:

```bash
cloudflared tunnel --url http://localhost:8000
```

Then set `RECEPTIONIST_PUBLIC_BASE_URL` to the tunnel URL **before** placing calls.

### On Coolify

Deploy the same image twice next to your LiveKit stack — once with
`uv run agent.py start`, once with `uv run fastapi run`. Give both the same env, and expose
a domain for the web one only. Run `uv run alembic upgrade head` once against the cluster
before the first deploy. Scale the worker by adding replicas; one worker handles several
concurrent calls.

The SPA is deployed separately, to its own origin — this image serves JSON and never
markup. Point `RECEPTIONIST_PUBLIC_BASE_URL` at the SPA and name that origin in
`RECEPTIONIST_CORS_ORIGINS`.

The compose file works unmodified under the Docker Compose build pack. Two settings:

| field | value |
|---|---|
| Base Directory | `/backend` |
| Docker Compose Location | `/backend/docker-compose.yaml` |

Those two must agree, because Coolify passes the base directory as Compose's
`--project-directory`, and every relative path in the compose file resolves against it.
That is why the file lives at `backend/` rather than `backend/deploy/`.

Then add `GOOGLE_CREDENTIALS_JSON` and the rest as environment variables. `env_file: .env`
is marked `required: false`, so its absence from the clone — `.env` is gitignored — is
skipped rather than fatal, and Coolify's injection supplies the environment instead.

**Reaching the API:** assign a domain to the `web` service in the UI and write it as
`https://api.example.com:8000` — the `:8000` tells Coolify's proxy which *container* port to
route to; the site still answers on 443.

That domain is **not** what goes in `RECEPTIONIST_PUBLIC_BASE_URL`. Two origins, two jobs:

| variable / setting | points at | why |
|---|---|---|
| Coolify domain for `web` | `api.example.com` | where the SPA fetches call data |
| `RECEPTIONIST_PUBLIC_BASE_URL` | the CloudFront origin | it builds the texted link, which must open the SPA — a caller tapping it should not land on raw JSON |

Getting these backwards is silent: calls still complete and texts still send, but every
link opens the API instead of the app.

Do not add `ports:` to reach the API instead. That binds the port on the server outside the
proxy, so it is served without TLS, and it fails outright when anything else already holds
the port — `Bind for 0.0.0.0:8000 failed: port is already allocated`.

One behaviour worth knowing before you debug something else: Coolify injects every variable
into every container in a compose project, regardless of which service declared it
([#7655](https://github.com/coollabsio/coolify/issues/7655)).

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
> until something dispatches — and a job that arrives without a `profile_id` in its
> metadata is refused rather than answered as a guessed business.

## 3. The confirmation text

The text goes out **from the number the caller dialled** — read off the SIP participant's
`sip.trunkPhoneNumber`, which works because `provision.py` creates one trunk per DID. So a
caller who rang the HVAC line gets the reply from the HVAC line. `TELNYX_FROM_NUMBER` is
only the fallback for a call that supplied no dialled number.

That means **every DID in `sip/numbers.json` must be assigned to a messaging profile**, not
just one number. Miss one and only that business's texts fail.

`TELNYX_API_KEY` is checked at startup: the worker will not register without it. To send
for real:

1. Buy numbers with SMS enabled and **assign each to a messaging profile** in the Telnyx
   portal. Skipping that step is the common failure: `40300 Forbidden — the from number is
   not assigned to a messaging profile`.
2. Set `TELNYX_API_KEY` (a V2 key). `TELNYX_FROM_NUMBER` is optional — it only covers a
   call that supplied no dialled number — but must be E.164 if you set it.

### When a text doesn't arrive

Every path logs. In the worker log, `receptionist.messaging.telnyx` gives you one of:

```
sms to +1604… not sent: '' is not an E.164 number          ← never reached Telnyx
sending sms +16042969870 -> +1604… (128 chars)             ← attempted
telnyx rejected … -> …: 403 40300 Forbidden: …             ← Telnyx refused
sms sent +16042969870 -> +1604…: 40017…                    ← accepted
```

The same reason is stored on the call as an `sms_skipped` / `sms_failed` event, so it also
shows up in the call's decision timeline rather than only in a log you may have lost. The
message body is never logged — it carries a signed link.

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
media would fall back to ICE/TCP on 7881 — untested. Placing a real call through a
provisioned DID is the reliable way to hear the agent.

## References

- [Self-hosting](https://docs.livekit.io/home/self-hosting/) ·
  [SIP](https://docs.livekit.io/sip/) ·
  [Dispatch rules](https://docs.livekit.io/sip/dispatch-rule/) ·
  [Builds & Dockerfiles](https://docs.livekit.io/deploy/agents/builds/)
- [Telnyx: send a message](https://developers.telnyx.com/docs/messaging/messages/send-message)
