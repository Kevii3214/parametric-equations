"""Pretend to be the wearable: walk an incident's route and post telemetry to the server.

Run from backend/ once an incident has a route (the agent saves it):

    python -m uv run python tools/mock_wearable.py <incident_id> [--base-url URL] [--speedup 4] [--no-tags]

The web app's dot should move along the route and cues should appear. Reads the route with the server's own
Supabase key, so run it on your machine, never from the browser.
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import get_db
from app.graph.schema import RouteStep
from app.position.simulate import simulate
from app.providers.snapshot import SnapshotProvider


async def load(incident_id: str) -> tuple[list[RouteStep], dict[str, str]]:
    db = get_db()
    incident = db.table("incidents").select("*").eq("id", incident_id).execute().data
    routes = db.table("routes").select("*").eq("incident_id", incident_id).execute().data
    if not incident or not routes:
        sys.exit("That incident does not exist or has no route yet.")
    route = max(routes, key=lambda r: r["version"])
    steps = [RouteStep.model_validate(s) for s in route["steps"]]
    tags: dict[str, str] = {}  # node id -> tag UID
    if incident[0].get("building_id"):
        try:
            graph = await SnapshotProvider().graph(incident[0]["building_id"])
            tags = {n["id"]: n["tag_id"] for n in graph["nodes"] if n.get("tag_id")}
        except LookupError:
            pass
    return steps, tags


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("incident_id")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--speedup", type=float, default=4.0, help="1 = real walking pace")
    parser.add_argument("--no-tags", action="store_true", help="do not scan RFID tags on the way")
    args = parser.parse_args()

    steps, tags = asyncio.run(load(args.incident_id))
    url = f"{args.base_url}/incidents/{args.incident_id}/telemetry"
    print(f"Walking {len(steps)} steps ({sum(s.seconds for s in steps):.0f} s planned) -> {url}")
    sent = 0
    with httpx.Client(timeout=30) as client:
        for sample in simulate(steps, tags_at=None if args.no_tags else tags):
            response = client.post(url, json=sample)
            response.raise_for_status()
            sent += 1
            if sample["tag"]:
                print(f"  scanned {sample['tag']}")
            time.sleep(0.2 / args.speedup)
    print(f"Done: {sent} samples sent.")


if __name__ == "__main__":
    main()
