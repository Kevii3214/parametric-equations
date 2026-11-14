"""Build the routing graph for Williams Tower (id 233903) from its Matterport 56th-floor scan.

Run from backend/:  python -m uv run python notebooks/make_williams_graph.py

Writes fixtures/buildings/233903/graph.json (contracts/building_graph.schema.json shape).

MEASURED (floor 56, model eJKnR3x44eh): every doorway and open ("invisible") gap between rooms, taken from
the scan's vector data. Two rooms are joined through a doorway only where the straight walk stays inside the
room outline. The suite entrance is the 2 m glass doorway at the scan origin.
ESTIMATED: the street entrance, ground lobby, elevators, stairs and the corridor outside the suite, plus all
elevator and stair times. No scan covers them. Check these by hand before the demo.
"""

import json
import math
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString
from shapely.ops import polygonize, unary_union

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233903"
WALK_MPS = 1.3
SAME_SPOT_M = 0.6  # two doorways this close are one door seen from both rooms
GAP_MATCH_M = 0.8  # same for open gaps
INSIDE_TOLERANCE_M = 0.4  # a straight walk may stray this far from the room outline

# Which rooms the crew might be sent to, by room index in the scan (see the floor plan).
DESTINATIONS = {
    29: "Conference Room (patient)",
    23: "Kitchen (patient)",
    27: "Coworking space (patient)",
    5: "Office at the north end (patient)",
}
ENTRY_TARGET = (-0.2, 0.7)  # the suite's main glass door, at the scan origin

interior = json.loads((FIXTURES / "interior.json").read_text(encoding="utf-8"))
model = interior["models"][0]
rooms = model["rooms"]
room_name = {
    i: (r.get("label") or (r.get("classifications") or [{}])[0].get("label") or "room")
    for i, r in enumerate(rooms)
}

# ---- read the scan: room outlines, doorways, open gaps
outline: dict[int, object] = {}
doorways: list[tuple[int, float, float]] = []
gaps: list[tuple[int, float, float]] = []
for i, room in enumerate(rooms):
    segments = []
    for edge in (room.get("boundary") or {}).get("edges", []):
        (ax, ay), (bx, by) = ((v["position"]["x"], v["position"]["y"]) for v in edge["vertices"])
        segments.append(LineString([(ax, ay), (bx, by)]))
        if edge["type"] == "invisible":
            gaps.append((i, (ax + bx) / 2, (ay + by) / 2))
        for opening in edge.get("openings") or []:
            if opening["type"] in ("doorway", "opening"):  # windows are not ways through
                t = opening["relativeCenter"]
                doorways.append((i, ax + (bx - ax) * t, ay + (by - ay) * t))
    polygons = list(polygonize(unary_union(segments)))
    outline[i] = max(polygons, key=lambda p: p.area) if polygons else None


def merge(points: list[tuple[int, float, float]], radius: float) -> list[dict]:
    """Group points from different rooms that sit at the same spot into one passage."""
    passages: list[dict] = []
    for room, x, y in points:
        for p in passages:
            if room not in p["rooms"] and math.hypot(p["x"] - x, p["y"] - y) < radius:
                p["rooms"].add(room)
                break
        else:
            passages.append({"x": x, "y": y, "rooms": {room}})
    return passages


passages = merge(doorways, SAME_SPOT_M) + [
    p for p in merge(gaps, GAP_MATCH_M) if len(p["rooms"]) > 1
]
entry = min(
    (p for p in passages if len(p["rooms"]) == 1),
    key=lambda p: math.hypot(p["x"] - ENTRY_TARGET[0], p["y"] - ENTRY_TARGET[1]),
)
ENTRY_X, ENTRY_Y = round(entry["x"], 2), round(entry["y"], 2)

# ---- nodes
nodes: list[dict] = []


def add_node(node_id, floor, x, y, kind, label=None, tag=None):
    nodes.append(
        {
            "id": node_id,
            "floor": floor,
            "x": round(x, 2),
            "y": round(y, 2),
            "kind": kind,
            "label": label,
            "tag_id": tag,
        }
    )


# floor 1: estimated
add_node("st_main", 1, 0.0, 0.0, "entrance", "Post Oak Blvd main entrance", "TAG-ENTRANCE-01")
add_node("lob1", 1, 18.0, 0.0, "corridor", "Ground floor lobby")
add_node("el1", 1, 18.0, 14.0, "elevator", "Elevators (floor 1)")
add_node("stair1", 1, 26.0, 14.0, "stairs", "Stairwell (floor 1)")
add_node("gar1", 1, 46.0, 14.0, "entrance", "Parking garage lobby")
# floor 56: the corridor outside the suite is estimated, the suite itself is measured
add_node("el56", 56, ENTRY_X, 9.0, "elevator", "Elevators (floor 56)")
add_node("stair56", 56, ENTRY_X - 7.0, 9.0, "stairs", "Stairwell (floor 56)")
add_node("hall56", 56, ENTRY_X, 4.0, "corridor", "Floor 56 elevator corridor")
add_node(
    "door56",
    56,
    ENTRY_X,
    ENTRY_Y,
    "door",
    "Titan Global Advisory Suite 5600 entrance",
    "TAG-SUITE-5600",
)

passage_ids: list[tuple[str, dict]] = []
dead_ends = 0
for n, p in enumerate(passages):
    if p is entry:
        passage_ids.append(("door56", p))
        continue
    if len(p["rooms"]) < 2:  # a door to somewhere the scan does not cover: not a way between rooms
        dead_ends += 1
        continue
    a, b = sorted(p["rooms"])[:2]
    label = f"{room_name[a]} to {room_name[b]} passage"
    node_id = f"p{n}"
    add_node(node_id, 56, p["x"], p["y"], "door", label)
    passage_ids.append((node_id, p))

dest_ids: dict[int, str] = {}
for index, label in DESTINATIONS.items():
    c = outline[index].representative_point() if outline[index] else None
    if c is None:
        continue
    dest_ids[index] = f"room{index}"
    add_node(dest_ids[index], 56, c.x, c.y, "door", f"Suite 5600 {label}")

pos = {n["id"]: (n["x"], n["y"]) for n in nodes}

# ---- edges
edges: list[dict] = []


def link(a, b, kind="corridor"):
    meters = round(math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]), 1)
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


link("st_main", "lob1")
link("lob1", "el1")
link("el1", "stair1")
link("gar1", "el1")
link("el56", "stair56")
link("el56", "hall56")
link("hall56", "door56")

# Inside each room, join every pair of its doors/gaps (and any destination point) that can be walked in a straight line.
members: dict[int, list[str]] = defaultdict(list)
for node_id, p in passage_ids:
    for r in p["rooms"]:
        members[r].append(node_id)
for index, node_id in dest_ids.items():
    members[index].append(node_id)

joined = 0
for r, ids in members.items():
    area = outline[r].buffer(INSIDE_TOLERANCE_M) if outline[r] else None
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            segment = LineString([pos[a], pos[b]])
            if area is None or area.contains(segment):
                link(a, b, "door" if "door56" in (a, b) else "corridor")
                joined += 1

# Vertical links. ASSUMED: about 25 s wait plus 35 s ride up, 55 s down; stairs about 25 s per floor with a stretcher.
edges += [
    {
        "from": "el1",
        "to": "el56",
        "meters": 0,
        "kind": "elevator",
        "stretcher_ok": True,
        "seconds": 60,
    },
    {
        "from": "el56",
        "to": "el1",
        "meters": 0,
        "kind": "elevator",
        "stretcher_ok": True,
        "seconds": 55,
    },
    {
        "from": "stair1",
        "to": "stair56",
        "meters": 300,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": 1375,
    },
    {
        "from": "stair56",
        "to": "stair1",
        "meters": 300,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": 1000,
    },
]

graph = {"building_id": "233903", "nodes": nodes, "edges": edges}
out = FIXTURES / "graph.json"
out.write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
print(f"wrote {out}: {len(nodes)} nodes, {len(edges)} edges ({joined} room links)")
print(f"skipped {dead_ends} one-sided doorways")
print(
    "suite entrance (measured doorway):",
    (ENTRY_X, ENTRY_Y),
    "| destinations:",
    {room_name[i]: n for i, n in dest_ids.items()},
)
