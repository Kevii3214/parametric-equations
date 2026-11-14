"""Build the routing graph for the demo building (1415 Louisiana, id 233928).

Run from backend/:  python -m uv run python notebooks/make_demo_graph.py

Writes fixtures/buildings/233928/graph.json (contracts/building_graph.schema.json shape).

MEASURED: the Regus Suite 1800 interior on floor 18. The two door positions are taken from the Matterport
scan's doorway data (model LJn59uoV759), not typed by hand.
ESTIMATED: everything else (street entrance, ground lobby, elevators, stairs, floor-18 corridor). No scan
covers them. Elevator and stair times are assumptions. Check these by hand before the demo.
"""

import json
import math
from pathlib import Path

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928"
WALK_MPS = 1.3
SUITE_MODEL = "LJn59uoV759"  # Matterport model: Regus Suite 1800 reception, hallway and phone room


def doorway_positions(model_id: str) -> list[tuple[float, float]]:
    """World position (metres, scan frame) of every doorway in the scan."""
    interior = json.loads((FIXTURES / "interior.json").read_text(encoding="utf-8"))
    model = next(m for m in interior["models"] if m["id"] == model_id)
    points = []
    for room in model["rooms"]:
        for edge in (room.get("boundary") or {}).get("edges", []):
            (ax, ay), (bx, by) = (
                (v["position"]["x"], v["position"]["y"]) for v in edge["vertices"]
            )
            for opening in edge.get("openings") or []:
                t = opening["relativeCenter"]
                points.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    return points


def nearest(points: list[tuple[float, float]], target: tuple[float, float]) -> tuple[float, float]:
    x, y = min(points, key=lambda p: math.hypot(p[0] - target[0], p[1] - target[1]))
    return round(x, 2), round(y, 2)


doors = doorway_positions(SUITE_MODEL)
SUITE_ENTRY = nearest(
    doors, (-0.2, -2.1)
)  # assumed suite entrance: west side, nearest the scan origin
PHONE_DOOR = nearest(doors, (6.7, -3.1))  # door of the phone room, where the patient is

# (id, floor, x, y, kind, label, tag_id)
NODES = [
    # ---- floor 1: estimated
    ("st_main", 1, 0.0, 0.0, "entrance", "Louisiana St main entrance", "TAG-ENTRANCE-01"),
    ("lob1", 1, 15.0, 0.0, "corridor", "Ground floor lobby", None),
    ("el1", 1, 15.0, 12.0, "elevator", "Elevators (floor 1)", None),
    ("stair1", 1, 22.0, 12.0, "stairs", "Stairwell (floor 1)", None),
    ("gar1", 1, 40.0, 12.0, "entrance", "Parking garage lobby", None),
    # ---- floor 18: corridor estimated, suite measured
    ("el18", 18, -0.2, -25.0, "elevator", "Elevators (floor 18)", None),
    ("stair18", 18, -6.0, -25.0, "stairs", "Stairwell (floor 18)", None),
    ("hall18", 18, -0.2, -8.0, "corridor", "Floor 18 corridor", None),
    (
        "door18",
        18,
        SUITE_ENTRY[0],
        SUITE_ENTRY[1],
        "door",
        "Regus Suite 1800 entrance",
        "TAG-SUITE-1800",
    ),
    ("rec_a", 18, 1.0, -0.5, "corridor", "Regus reception", None),
    ("rec_b", 18, PHONE_DOOR[0], -0.5, "corridor", "Regus reception, by the phone room", None),
    (
        "phone_door",
        18,
        PHONE_DOOR[0],
        PHONE_DOOR[1],
        "door",
        "Regus Suite 1800 phone room (patient)",
        None,
    ),
]
BY_ID = {n[0]: n for n in NODES}

# Walkable links, listed once and added in both directions: (from, to, kind)
LINKS = [
    ("st_main", "lob1", "corridor"),
    ("lob1", "el1", "corridor"),
    ("el1", "stair1", "corridor"),
    ("gar1", "el1", "corridor"),
    ("el18", "stair18", "corridor"),
    ("el18", "hall18", "corridor"),
    ("hall18", "door18", "corridor"),
    ("door18", "rec_a", "door"),
    ("rec_a", "rec_b", "corridor"),
    ("rec_b", "phone_door", "door"),
]


def distance(a: str, b: str) -> float:
    na, nb = BY_ID[a], BY_ID[b]
    return round(math.hypot(na[2] - nb[2], na[3] - nb[3]), 1)


edges = []
for a, b, kind in LINKS:
    meters = distance(a, b)
    seconds = math.ceil(meters / WALK_MPS)  # never faster than the router's 1.3 m/s heuristic
    for src, dst in ((a, b), (b, a)):
        edges.append(
            {
                "from": src,
                "to": dst,
                "meters": meters,
                "kind": kind,
                "stretcher_ok": True,
                "seconds": seconds,
            }
        )

# Vertical links. ASSUMED: about 25 s wait plus 35 s ride up, 55 s down; stairs about 25 s per floor with a stretcher.
edges += [
    {
        "from": "el1",
        "to": "el18",
        "meters": 0,
        "kind": "elevator",
        "stretcher_ok": True,
        "seconds": 60,
    },
    {
        "from": "el18",
        "to": "el1",
        "meters": 0,
        "kind": "elevator",
        "stretcher_ok": True,
        "seconds": 55,
    },
    {
        "from": "stair1",
        "to": "stair18",
        "meters": 90,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": 425,
    },
    {
        "from": "stair18",
        "to": "stair1",
        "meters": 90,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": 330,
    },
]

graph = {
    "building_id": "233928",
    "nodes": [
        {"id": i, "floor": f, "x": x, "y": y, "kind": k, "label": label, "tag_id": tag}
        for i, f, x, y, k, label, tag in NODES
    ],
    "edges": edges,
}
out = FIXTURES / "graph.json"
out.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}: {len(graph['nodes'])} nodes, {len(edges)} edges")
print("suite entry", SUITE_ENTRY, "| phone door", PHONE_DOOR)
