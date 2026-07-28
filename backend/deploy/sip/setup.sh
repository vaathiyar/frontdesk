#!/usr/bin/env bash
#
# Provision SIP inbound trunks + dispatch rules on a SELF-HOSTED LiveKit server.
#
# Two DIDs -> two profiles: each inbound trunk (a DID) is paired with a dispatch
# rule whose job metadata carries {"profile_id": "..."}, so the "receptionist"
# worker knows which profile to load for that call.
#
# Prereqs:
#   - The `lk` CLI is installed:  https://docs.livekit.io/home/cli/
#   - Your self-hosted livekit-server AND livekit-sip are running and reachable.
#   - Your telephony/SIP provider delivers each DID to your livekit-sip service,
#     and the "numbers" in each inbound-trunk-*.json match those DIDs exactly.
#
# The script is safe to run twice: the first run creates the trunks; after you
# paste the printed trunk IDs into the dispatch-rule-*.json files, the second run
# creates the dispatch rules (and does NOT re-create the trunks).
#
# Run from the backend/ directory:  bash deploy/sip/setup.sh
set -euo pipefail

cd "$(dirname "$0")/../.."   # -> backend/ (so the deploy/sip/*.json paths resolve)

HVAC_RULE="deploy/sip/dispatch-rule-hvac.json"
REST_RULE="deploy/sip/dispatch-rule-restaurant.json"

# --- 1. Point the lk CLI at YOUR self-hosted server -------------------------
# Option A (quick, per-shell): export the connection env vars; `lk` reads them.
: "${LIVEKIT_URL:?set LIVEKIT_URL, e.g. wss://livekit.example.com}"
: "${LIVEKIT_API_KEY:?set LIVEKIT_API_KEY}"
: "${LIVEKIT_API_SECRET:?set LIVEKIT_API_SECRET}"
#
# Option B (persisted): register a named project once, then drop the env vars:
#   lk project add --url "$LIVEKIT_URL" \
#       --api-key "$LIVEKIT_API_KEY" --api-secret "$LIVEKIT_API_SECRET" selfhosted
#   lk project set-default selfhosted
#
# NOTE: subcommand names below follow the current lk CLI. If yours differ, check
#       `lk sip --help`.

if grep -q "REPLACE_.*trunk_id" "$HVAC_RULE" "$REST_RULE"; then
  # --- Phase 1: trunk IDs are not wired into the dispatch rules yet ----------
  # Create one inbound trunk per DID. EDIT the "numbers" in these files first so
  # they match your real DIDs.
  echo "== Phase 1: creating inbound trunks =="
  lk sip inbound create deploy/sip/inbound-trunk-hvac.json
  lk sip inbound create deploy/sip/inbound-trunk-restaurant.json

  cat <<'EOF'

Next:
  1. Copy each SIPTrunkID (ST_...) printed above into the matching file's
     "trunk_ids", replacing the placeholder:
       HVAC trunk id        -> deploy/sip/dispatch-rule-hvac.json
       Restaurant trunk id  -> deploy/sip/dispatch-rule-restaurant.json
  2. Re-run this script to create the dispatch rules.
EOF
  exit 0
fi

# --- Phase 2: trunk IDs are wired in -> create the dispatch rules ------------
# Each rule creates a per-caller room (roomPrefix) and dispatches the named agent
# "receptionist" with {"profile_id": "..."} in its job metadata.
echo "== Phase 2: creating dispatch rules =="
lk sip dispatch create "$HVAC_RULE"
lk sip dispatch create "$REST_RULE"

# --- Verify -----------------------------------------------------------------
echo
echo "Inbound trunks:"
lk sip inbound list
echo
echo "Dispatch rules:"
lk sip dispatch list
