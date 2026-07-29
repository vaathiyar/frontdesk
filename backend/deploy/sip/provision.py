"""Apply deploy/sip/numbers.json to LiveKit: one inbound trunk and one dispatch rule per DID.

    uv run python deploy/sip/provision.py            # apply
    uv run python deploy/sip/provision.py --show     # read-only: what's there now

There is nothing to "connect". LiveKit's SIP config lives in livekit-server's own store,
not in a file any process watches, so this just calls the management API with
LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET. That is the whole bridge, and it is
why it does not matter where this runs — host, container, or CI.

Safe to re-run, and numbers.json is authoritative: change a number there and the next run
moves the trunk to match. The safety boundary is the name — only trunks and rules called
`receptionist-<profile>` are ever touched, so a LiveKit shared with other applications is
left alone.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

import dotenv

dotenv.load_dotenv()

from livekit import api  # noqa: E402
from livekit.protocol import agent_dispatch as ad  # noqa: E402
from livekit.protocol import room as room_pb  # noqa: E402
from livekit.protocol import sip as sip_pb  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from receptionist.agent.worker import AGENT_NAME  # noqa: E402
from receptionist.profiles import PROFILES  # noqa: E402

NUMBERS = Path(__file__).parent / "numbers.json"


def wanted() -> dict[str, str]:
    """The desired DID -> profile mapping, validated against the registered profiles."""
    numbers: dict[str, str] = json.loads(NUMBERS.read_text())["numbers"]
    for did, profile_id in numbers.items():
        if not did.startswith("+"):
            raise SystemExit(f"{did!r} is not E.164 — it must start with '+'")
        if profile_id not in PROFILES:
            raise SystemExit(
                f"{did} maps to unknown profile {profile_id!r}. Registered: {', '.join(PROFILES)}"
            )
    return numbers


def trunk_name(profile_id: str) -> str:
    return f"receptionist-{profile_id}"


async def show(sip: api.SipService) -> None:
    trunks = (await sip.list_inbound_trunk(sip_pb.ListSIPInboundTrunkRequest())).items
    rules = (await sip.list_dispatch_rule(sip_pb.ListSIPDispatchRuleRequest())).items
    print(f"inbound trunks ({len(trunks)}):")
    for trunk in trunks:
        print(f"  {trunk.sip_trunk_id}  {trunk.name!r}  numbers={list(trunk.numbers)}")
    print(f"dispatch rules ({len(rules)}):")
    for rule in rules:
        agents = [(a.agent_name, a.metadata) for a in rule.room_config.agents]
        print(f"  {rule.sip_dispatch_rule_id}  {rule.name!r}")
        print(f"    trunks={list(rule.trunk_ids)}  agents={agents}")
    if not rules:
        print("  (none — calls would connect to a room with no agent, and hear silence)")


async def apply() -> None:
    numbers = wanted()
    async with api.LiveKitAPI() as lk:
        sip = lk.sip
        trunks = {
            t.name: t
            for t in (await sip.list_inbound_trunk(sip_pb.ListSIPInboundTrunkRequest())).items
        }
        rules = {
            r.name: r
            for r in (await sip.list_dispatch_rule(sip_pb.ListSIPDispatchRuleRequest())).items
        }

        for did, profile_id in numbers.items():
            name = trunk_name(profile_id)
            trunk = trunks.get(name)

            if trunk is None:
                trunk = await sip.create_inbound_trunk(
                    sip_pb.CreateSIPInboundTrunkRequest(
                        trunk=sip_pb.SIPInboundTrunkInfo(name=name, numbers=[did])
                    )
                )
                print(f"created trunk  {trunk.sip_trunk_id}  {name}  {did}")
            elif list(trunk.numbers) != [did]:
                was = list(trunk.numbers)
                trunk = await sip.update_inbound_trunk(
                    trunk_id=trunk.sip_trunk_id,
                    trunk=sip_pb.SIPInboundTrunkInfo(name=name, numbers=[did]),
                )
                print(f"moved trunk    {trunk.sip_trunk_id}  {name}  {was} -> {did}")
            else:
                print(f"trunk exists   {trunk.sip_trunk_id}  {name}  {did}")

            # Rules carry no state, so replacing is the simplest way to converge on the
            # file. There is a moment with no rule; provisioning is an admin action.
            existing = rules.get(name)
            if existing is not None:
                await sip.delete_dispatch_rule(
                    sip_pb.DeleteSIPDispatchRuleRequest(
                        sip_dispatch_rule_id=existing.sip_dispatch_rule_id
                    )
                )

            rule = await sip.create_dispatch_rule(
                sip_pb.CreateSIPDispatchRuleRequest(
                    name=name,
                    trunk_ids=[trunk.sip_trunk_id],
                    rule=sip_pb.SIPDispatchRule(
                        dispatch_rule_individual=sip_pb.SIPDispatchRuleIndividual(
                            room_prefix=f"{profile_id}-call-"
                        )
                    ),
                    # This is the DID -> profile mapping, and the only thing that differs
                    # between rules. The worker reads it from ctx.job.metadata.
                    room_config=room_pb.RoomConfiguration(
                        agents=[
                            ad.RoomAgentDispatch(
                                agent_name=AGENT_NAME,
                                metadata=json.dumps({"profile_id": profile_id}),
                            )
                        ]
                    ),
                )
            )
            verb = "replaced" if existing else "created"
            print(f"{verb} rule   {rule.sip_dispatch_rule_id}  {name} -> {profile_id}")

        print("\ncurrent state:")
        await show(sip)
        print(
            f"\nDispatch is explicit: a worker must be registered as {AGENT_NAME!r} when a "
            "call lands, or the caller reaches a room with no agent."
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--show", action="store_true", help="print the current config and change nothing"
    )
    args = parser.parse_args()

    for required in ("LIVEKIT_URL", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"):
        if not os.getenv(required):
            raise SystemExit(f"{required} is not set — that is how this reaches LiveKit")

    if args.show:

        async def run() -> None:
            async with api.LiveKitAPI() as lk:
                await show(lk.sip)

        asyncio.run(run())
    else:
        asyncio.run(apply())


if __name__ == "__main__":
    main()
