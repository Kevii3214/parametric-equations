"""Pretend to be the Raspberry Pi: link to an incident, walk its route and post wearable events.

Run from backend/ once an incident has a route (the agent saves it):

    python -m uv run python tools/mock_device.py <incident_id> [--device pi-01] [--base-url URL] [--speedup 4]

Prints every command the server sends back (CUE L, CUE UP, ...). Reads the route with the server's own
Supabase key, so run it on your machine. The real Pi only needs the two HTTP calls this makes.
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
    parser.add_argument("--device", default="pi-01")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--speedup", type=float, default=4.0, help="1 = real walking pace")
    parser.add_argument("--no-tags", action="store_true", help="do not scan RFID tags on the way")
    args = parser.parse_args()

    steps, tags = asyncio.run(load(args.incident_id))
    base = f"{args.base_url}/api/device/{args.device}"
    sent = 0
    with httpx.Client(timeout=30) as client:
        client.put(f"{base}/link", json={"incident_id": args.incident_id}).raise_for_status()
        print(f"Linked {args.device} to {args.incident_id}; walking {len(steps)} steps")
        for batch in telemetry_to_batches(simulate(steps, tags_at=None if args.no_tags else tags)):
            response = client.post(f"{base}/events", json=batch.model_dump(exclude_none=True))
            response.raise_for_status()
            sent += 1
            for command in response.json()["commands"]:
                print(f"  t={batch.t / 1000:5.1f}s  <- {command}")
            time.sleep(0.2 / args.speedup)
    print(f"Done: {sent} batches sent.")


if __name__ == "__main__":
    main()
