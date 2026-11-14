"""Onboard a building from its Matterport scan with one command: snapshot, routing map, tour, and a check list.

Run from backend/:

    python -m uv run python tools/add_building.py --model P3S6VUTP3qB --id jrr --name "Rabinowitz Hall" \
        --address "Princeton University" --city Princeton --state NJ [--alias rabinowitz] \
        [--entrance-px 1330] [--stairs-px 300] [--vision] [--level 1 | --floor-map "Floor 2=2,Floor 3=3"]

What it does, with no hand-drawing: pulls the scan (rooms, doors, camera positions), builds the walkable map, makes a
destination for every room, finds the entrance and stairs from the best evidence it has, saves everything under
fixtures/buildings/<id>/, writes a sample fly-through tour, and prints what it had to infer (check those by hand).
The building record is written by hand from the arguments (use CoStar's data instead when the building is in the kit).
"""

import argparse
import json
import math
import os
import re
import sys
from datetime import date
from pathlib import Path

import httpx
import networkx as nx
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.graph.from_scan import DEFAULT_IMAGE_WIDTH, Hints, build_graph_from_scan
from app.graph.router import NoRouteError, build_digraph, find_route
from app.tour import build_tour

BACKEND = Path(__file__).resolve().parents[1]
FIXTURES = BACKEND.parent / "fixtures" / "buildings"
load_dotenv(BACKEND / ".env")

QUERY = """query($id: ID!) { model(id: $id) { id name
  geolocation { lat long }
  floors { id label sequence }
  rooms { id label classifications { label } floor { id label sequence }
    boundary { edges { id type thickness
      openings { id type width height lowerElevation relativeCenter }
      vertices { id position { x y } } } }
    holes { edges { id type
      openings { id type width relativeCenter }
      vertices { id position { x y } } } } }
  locations { id position { x y z } floor { id } neighbors }
  image { url width snapshotLocation { position { x y z } rotation { x y z w } } }
} }"""


def pull(model_id: str) -> dict:
    auth = (os.environ["MATTERPORT_API_KEY"], os.environ["MATTERPORT_API_TOKEN"])
    r = httpx.post(
        "https://api.matterport.com/api/models/graph",
        json={"query": QUERY, "variables": {"id": model_id}},
        auth=auth,
        timeout=240,
    )
    r.raise_for_status()
    body = r.json()
    if body.get("errors") or not body["data"]["model"]:
        sys.exit(f"Matterport would not give model {model_id}: {body.get('errors')}")
    return body["data"]["model"]


def bearing_and_pitch(q: dict) -> tuple[float, float]:
    """Compass bearing (0 = +y, clockwise) and pitch of a camera looking down -Z rotated by quaternion q."""
    x, y, z, w = q["x"], q["y"], q["z"], q["w"]
    vx, vy, vz = 0.0, 0.0, -1.0
    tx, ty, tz = 2 * (y * vz - z * vy), 2 * (z * vx - x * vz), 2 * (x * vy - y * vx)
    fx, fy, fz = (
        vx + w * tx + (y * tz - z * ty),
        vy + w * ty + (z * tx - x * tz),
        vz + w * tz + (x * ty - y * tx),
    )
    return round(math.degrees(math.atan2(fx, fy)) % 360, 1), round(
        math.degrees(math.asin(max(-1, min(1, fz)))), 1
    )


def floor_levels(model: dict, floor_map: str | None, level: int) -> dict[str, int]:
    """Floor label -> the floor number used in the map, for the floors that have scan positions."""
    used = {loc["floor"]["id"] for loc in model["locations"]}
    floors = sorted((f for f in model["floors"] if f["id"] in used), key=lambda f: f["sequence"])
    if floor_map:
        return {k.strip(): int(v) for k, v in (pair.split("=") for pair in floor_map.split(","))}
    if len(floors) == 1:
        return {floors[0]["label"]: level}
    result = {}
    for k, f in enumerate(floors, start=1):
        m = re.search(r"(\d+)\s*$", f["label"])
        result[f["label"]] = int(m.group(1)) if m else k
    return result


def vision_hints(model: dict, image_bytes: bytes, width: int, model_name: str) -> Hints:
    from langchain_google_genai import ChatGoogleGenerativeAI

    from app.agent.vision_hints import propose_hints
    from app.config import get_settings

    llm = ChatGoogleGenerativeAI(
        model=model_name,
        google_api_key=get_settings().google_api_key,
        temperature=0,
        timeout=60,
        max_retries=0,
    )
    return propose_hints(llm, image_bytes, width)


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--model", required=True, help="Matterport model id")
    ap.add_argument(
        "--id", required=True, help="building id to save under (letters, digits, - and _)"
    )
    ap.add_argument("--name", required=True)
    ap.add_argument("--address", default="unknown")
    ap.add_argument("--city", default="")
    ap.add_argument("--state", default="")
    ap.add_argument(
        "--alias",
        action="append",
        default=[],
        help="another name the dispatcher might use; repeatable",
    )
    ap.add_argument("--level", type=int, default=1, help="floor number for a single-level scan")
    ap.add_argument("--floor-map", help='for several levels, e.g. "Floor 2=2,Floor 3=3"')
    ap.add_argument(
        "--entrance-px",
        type=float,
        help="pixel column of the entrance in the scan's opening picture",
    )
    ap.add_argument(
        "--stairs-px", type=float, help="pixel column of the staircase in the opening picture"
    )
    ap.add_argument(
        "--image-width",
        type=float,
        default=DEFAULT_IMAGE_WIDTH,
        help="width the pixel hints were read at",
    )
    ap.add_argument(
        "--vision",
        action="store_true",
        help="ask Gemini for entrance/stairs hints from the opening picture",
    )
    ap.add_argument("--vision-model", default="gemini-flash-lite-latest")
    args = ap.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9_-]+", args.id):
        sys.exit("--id may only contain letters, digits, - and _")

    print(f"Pulling scan {args.model} ...")
    model = pull(args.model)
    levels = floor_levels(model, args.floor_map, args.level)
    snap = (model.get("image") or {}).get("snapshotLocation")
    start_pose = None
    if snap:
        bearing, pitch = bearing_and_pitch(snap["rotation"])
        start_pose = {
            "position": {k: round(snap["position"][k], 3) for k in "xyz"},
            "bearing_deg": bearing,
            "pitch_deg": pitch,
        }
    level_of_floor = {f["id"]: levels[f["label"]] for f in model["floors"] if f["label"] in levels}
    sweeps = [
        {
            "id": l["id"],
            "x": round(l["position"]["x"], 3),
            "y": round(l["position"]["y"], 3),
            "z": round(l["position"]["z"], 3),
            "level": level_of_floor[l["floor"]["id"]],
            "neighbors": l["neighbors"] or [],
        }
        for l in model["locations"]
        if l["floor"]["id"] in level_of_floor
    ]
    if not sweeps:
        sys.exit("The scan has no camera positions on the chosen floors.")
    sweeps_model = {
        "id": args.model,
        "name": model["name"],
        "start_pose": start_pose,
        "sweeps": sweeps,
    }

    hints = Hints(
        entrance_px=args.entrance_px, stairs_px=args.stairs_px, image_width=args.image_width
    )
    if args.vision:
        img = model["image"]
        print(f"Asking {args.vision_model} to look at the opening picture ...")
        found = vision_hints(
            model,
            httpx.get(img["url"], timeout=60, follow_redirects=True).content,
            img["width"],
            args.vision_model,
        )
        hints = Hints(
            entrance_px=args.entrance_px if args.entrance_px is not None else found.entrance_px,
            stairs_px=args.stairs_px if args.stairs_px is not None else found.stairs_px,
            image_width=args.image_width
            if (args.entrance_px is not None or args.stairs_px is not None)
            else found.image_width,
            source="a person"
            if (args.entrance_px is not None or args.stairs_px is not None)
            else found.source,
        )
        print(
            f"  vision found: entrance {found.entrance_px}, stairs {found.stairs_px} (of {img['width']} px)"
        )

    result = build_graph_from_scan(args.id, model, sweeps_model, levels, hints)
    graph, report = result.graph, result.report

    folder = FIXTURES / args.id
    folder.mkdir(parents=True, exist_ok=True)
    today = str(date.today())
    (folder / "interior.json").write_text(
        json.dumps(
            {
                "building_id": args.id,
                "source": "Matterport Model API",
                "snapshot_date": today,
                "models": [{k: v for k, v in model.items() if k != "image"}],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    (folder / "sweeps.json").write_text(
        json.dumps(
            {
                "building_id": args.id,
                "source": "Matterport Model API",
                "snapshot_date": today,
                "models": [sweeps_model],
            },
            indent=1,
        )
        + "\n",
        encoding="utf-8",
    )
    geo = model.get("geolocation") or {}
    record = {
        "building_id": args.id,
        "source": "written by hand: not in the CoStar kit",
        "snapshot_date": today,
        "name": args.name,
        "address": args.address,
        "city": args.city,
        "state": args.state,
        "latitude": float(geo["lat"]) if geo.get("lat") else None,
        "longitude": float(geo["long"]) if geo.get("long") else None,
        "property_type": None,
        "stories_above_grade": len(levels),
        "floor_names": list(levels),
        "elevators": [],
        "parking": [],
        "matterport_model_ids": [args.model],
        "current_tenants": [],
        "data_quality_notes": [
            "Written by hand from the Matterport scan: address, floors and elevators are unverified. No elevator is recorded because the scan does not show one."
        ],
    }
    (folder / "record.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    (folder / "graph.json").write_text(
        json.dumps(graph.model_dump(by_alias=True), indent=2) + "\n", encoding="utf-8"
    )
    index_path = FIXTURES / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    aliases = sorted(
        {args.name.lower(), args.id.lower(), *[a.lower() for a in args.alias]}
        | ({args.address.lower()} if args.address != "unknown" else set())
    )
    index[args.id] = {"name": args.name, "aliases": aliases}
    index_path.write_text(json.dumps(index, indent=2) + "\n", encoding="utf-8")

    # ---- check it works: every destination reachable, and a sample tour for the farthest one
    digraph = build_digraph(graph, [])
    parts = nx.number_weakly_connected_components(digraph)
    entrance = next((n.id for n in graph.nodes if n.kind == "entrance"), None)
    rows = []
    for n in [n for n in graph.nodes if n.label and n.label.endswith("(patient)")]:
        try:
            steps = find_route(graph, entrance, n.id)
            rows.append((sum(s.seconds for s in steps), n, steps))
        except (NoRouteError, LookupError):
            rows.append((None, n, None))
    reachable = [r for r in rows if r[0] is not None]
    far = max(reachable, key=lambda r: r[0], default=None)
    if far:
        tour = build_tour(far[2], graph, {"models": [sweeps_model]})
        if tour:
            (folder / "tour_sample.json").write_text(
                json.dumps(tour, indent=1) + "\n", encoding="utf-8"
            )

    lines = (
        [
            f"# {args.name} (id `{args.id}`): generated map",
            "",
            f"Built by `tools/add_building.py` from Matterport scan `{args.model}` on {today}. Not hand-checked.",
            "",
            "## Things the builder had to infer: check each one",
            "",
        ]
        + [f"- {i}" for i in report["inferred"]]
        + (
            ["", "## Warnings", ""] + [f"- {w}" for w in report["warnings"]]
            if report["warnings"]
            else []
        )
        + ["", "## Rooms you can send a patient to", ""]
        + [
            f"- {n.label} (floor {n.floor}): {f'{s:.0f} s from the entrance' if s is not None else 'NOT REACHABLE'}"
            for s, n, _ in sorted(rows, key=lambda r: (r[1].floor, r[1].label))
        ]
        + [
            "",
            "To correct the entrance or stairs, rerun with `--entrance-px` / `--stairs-px` (read them off the scan's opening picture).",
        ]
    )
    (folder / "GRAPH_NOTES.generated.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"\nSaved to {folder}")
    print(
        f"Map: {report['stats']['nodes']} nodes, {report['stats']['edges']} edges, {parts} connected piece(s); {len(reachable)}/{len(rows)} destinations reachable from the entrance"
    )
    print("Inferred (check these):")
    for i in report["inferred"]:
        print("  -", i)
    for w in report["warnings"]:
        print("WARNING:", w)
    if far:
        print(f"Sample tour: entrance -> {far[1].label} ({far[0]:.0f} s)")
    if parts > 1 or len(reachable) < len(rows):
        print(
            "NOTE: the map has unreachable parts: see the warnings; a hint for the stairs or entrance usually fixes it."
        )


if __name__ == "__main__":
    main()
