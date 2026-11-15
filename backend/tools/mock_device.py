"""Pretend to be the Raspberry Pi: bind to an incident, walk its route and post wearable events.

Run from backend/ once an incident has a route (the agent saves it):

    python -m uv run python tools/mock_device.py <incident_id> [--device wearable-1] [--base-url URL] [--speedup 4]

It speaks the real protocol (Hardware/BACKEND_BRIEF.md): `hello`, then `state` / `step` / `turn` / `floor` / `btn`
with heading and floor relative to the start, and prints every command the server sends back (RESET, CUE L,
ARRIVED, TXT ...). Reads the route with the server's own Supabase key, so run it on your machine. The real Pi
only needs the two HTTP calls this makes.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.device.replay import telemetry_to_batches
from app.position.simulate import simulate
from tools.mock_wearable import load


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("incident_id")
    parser.add_argument("--device", default="wearable-1")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--speedup", type=float, default=4.0, help="1 = real walking pace")
    parser.add_argument("--no-bind", action="store_true", help="the device is already bound")
    args = parser.parse_args()

    steps, _tags = asyncio.run(load(args.incident_id))
    sent = 0
    with httpx.Client(timeout=30, base_url=args.base_url) as client:
        if not args.no_bind:
            client.post(
                f"/incidents/{args.incident_id}/device", json={"device_id": args.device}
            ).raise_for_status()
            print(f"Bound {args.device} to {args.incident_id}; walking {len(steps)} steps")
        for events in telemetry_to_batches(simulate(steps), start_ts=int(time.time() * 1000)):
            response = client.post(f"/api/device/{args.device}/events", json={"events": events})
            response.raise_for_status()
            sent += 1
            for command in response.json()["commands"]:
                print(f"  ts={events[0]['ts'] % 1_000_000}  <- {command}")
            time.sleep(0.2 / args.speedup)
    print(f"Done: {sent} batches sent.")


if __name__ == "__main__":
    main()
