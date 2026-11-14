"""Build the routing graph for Rabinowitz Hall (JRR), building id "jrr", from its Matterport scan.

Run from backend/:  python -m uv run python notebooks/make_jrr_graph.py

Writes fixtures/buildings/jrr/graph.json (contracts/building_graph.schema.json shape).

MEASURED: walkable waypoints are the scan's camera positions (the camera stood on walkable floor); two
waypoints are joined only if the straight line stays inside the walkable floor outline and does not cross a
wall except at a measured doorway. The exterior doors are the scan's doorways that belong to only one room.
ESTIMATED: where the stairs between the two scanned levels are (anchored on the single scan position taken
mid-flight), and the time to climb them. The scan shows no elevator, so none is invented.
"""

import json
import math
from collections import defaultdict
from pathlib import Path

from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "jrr"
WALK_MPS = 1.3
MAX_LINK_M = 8.0  # longest straight hop between two waypoints
INSIDE_TOLERANCE_M = 0.4
DOOR_SLACK_M = 0.35  # a line may cross a wall this close to a doorway's edge
SAME_SPOT_M = 0.6
STAIRS_UP_S, STAIRS_DOWN_S, STAIRS_M = 30, 25, 12  # ASSUMED: one level (4 m) with a stretcher
STAIRS_ANCHOR = (1.4, -9.1)  # the single scan position taken between the two levels (z = 2 m)

model = json.loads((FIXTURES / "interior.json").read_text(encoding="utf-8"))["models"][0]
level_of_floor = {f["id"]: int(f["label"].split()[-1]) for f in model["floors"]}  # "Floor 2" -> 2
rooms = model["rooms"]
kind_of = {i: (r.get("classifications") or [{}])[0].get("label") for i, r in enumerate(rooms)}
name_of = {i: (r.get("label") or kind_of[i] or "room") for i, r in enumerate(rooms)}
level_of_room = {i: level_of_floor[r["floor"]["id"]] for i, r in enumerate(rooms) if r.get("floor")}


def polygon_from(region):
    segments = []
    for e in (region or {}).get("edges", []):
        (ax, ay), (bx, by) = ((v["position"]["x"], v["position"]["y"]) for v in e["vertices"])
        segments.append(LineString([(ax, ay), (bx, by)]))
    polys = list(polygonize(unary_union(segments))) if segments else []
    return max(polys, key=lambda p: p.area) if polys else None


outline = {}
for i, r in enumerate(rooms):
    poly = polygon_from(r.get("boundary"))
    for hole in r.get("holes") or []:
        h = polygon_from(hole)
        if poly is not None and h is not None:
            poly = poly.difference(h)
    outline[i] = poly

# walls and doorways per level
walls: dict[int, list[LineString]] = defaultdict(list)
openings: dict[int, list[tuple[float, float, float]]] = defaultdict(list)  # x, y, half-width
door_points: list[tuple[int, float, float]] = []
for i, r in enumerate(rooms):
    level = level_of_room.get(i)
    if level is None:
        continue
    for e in (r.get("boundary") or {}).get("edges", []):
        (ax, ay), (bx, by) = ((v["position"]["x"], v["position"]["y"]) for v in e["vertices"])
        if e["type"] == "wall":
            walls[level].append(LineString([(ax, ay), (bx, by)]))
        for o in e.get("openings") or []:
            if o["type"] in ("doorway", "opening"):
                t = o["relativeCenter"]
                x, y = ax + (bx - ax) * t, ay + (by - ay) * t
                openings[level].append((x, y, o["width"] / 2))
                door_points.append((i, x, y))

walkable = {}
for level in {1, 2, 3} & set(level_of_room.values()):
    parts = [
        outline[i]
        for i in outline
        if level_of_room.get(i) == level and kind_of[i] != "Void" and outline[i] is not None
    ]
    walkable[level] = unary_union(parts).buffer(INSIDE_TOLERANCE_M)


def can_walk(level: int, a: tuple[float, float], b: tuple[float, float]) -> bool:
    segment = LineString([a, b])
    if not walkable[level].contains(segment):
        return False
    for wall in walls[level]:
        if segment.intersects(wall):
            cross = segment.intersection(wall)
            point = cross if cross.geom_type == "Point" else cross.centroid
            if not any(
                math.hypot(point.x - ox, point.y - oy) <= half + DOOR_SLACK_M
                for ox, oy, half in openings[level]
            ):
                return False
    return True


# ---- nodes: the scan's camera positions on each level
nodes: list[dict] = []
pos: dict[str, tuple[float, float]] = {}
level_nodes: dict[int, list[str]] = defaultdict(list)


def add_node(node_id, level, x, y, kind, label=None, tag=None):
    nodes.append(
        {
            "id": node_id,
            "floor": level,
            "x": round(x, 2),
            "y": round(y, 2),
            "kind": kind,
            "label": label,
            "tag_id": tag,
        }
    )
    pos[node_id] = (round(x, 2), round(y, 2))
    level_nodes[level].append(node_id)


skipped = 0
mid_flight = None
for n, loc in enumerate(model["locations"]):
    level = level_of_floor[loc["floor"]["id"]]
    x, y, z = loc["position"]["x"], loc["position"]["y"], loc["position"]["z"]
    if 0.5 < z < 3.5:  # taken between the levels: it marks the staircase, not a floor
        mid_flight = (x, y)
        continue
    if level not in walkable or not walkable[level].contains(Point(x, y)):
        skipped += 1  # a camera position outside the room outlines (for example on a balcony edge)
        continue
    add_node(f"s{n}", level, x, y, "corridor")

# ---- the way in: the scan marks no exterior doorway, so the entrance is INFERRED. On the lower level there is
# one tiny alcove (well under 2.5 m2) with a single doorway on the hall's edge: a door vestibule.
lower = min(level_nodes)
upper = max(level_nodes)
doorways_of: dict[int, list[tuple[float, float]]] = defaultdict(list)
for room, x, y in door_points:
    doorways_of[room].append((x, y))
alcoves = [
    i
    for i in outline
    if level_of_room.get(i) == lower
    and kind_of[i] != "Hallway"
    and outline[i] is not None
    and outline[i].area < 2.5
    and len(doorways_of[i]) == 1
]
for k, i in enumerate(alcoves, start=1):
    door_x, door_y = doorways_of[i][0]
    far = outline[i].representative_point()
    add_node(
        f"entrance{k}",
        lower,
        far.x,
        far.y,
        "entrance",
        "Entrance (door alcove on the atrium hall's edge; position inferred)",
        "TAG-ENTRANCE-01" if k == 1 else None,
    )
    add_node(
        f"entrance{k}_door", lower, door_x, door_y, "door", "Entrance door into the atrium hall"
    )

# ---- edges
edges: list[dict] = []
joined = 0


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


node_level = {n["id"]: n["floor"] for n in nodes}
for level, ids in level_nodes.items():
    ids = [i for i in ids if not i.startswith("entrance")]
    for i, a in enumerate(ids):
        for b in ids[i + 1 :]:
            d = math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])
            if d <= MAX_LINK_M and can_walk(level, pos[a], pos[b]):
                link(a, b)
                joined += 1
# the entrance alcove joins the hall through its doorway, whatever the wall test says
for k in range(1, len(alcoves) + 1):
    link(f"entrance{k}", f"entrance{k}_door", "door")
    door_id = f"entrance{k}_door"
    inside = [i for i in level_nodes[lower] if not i.startswith("entrance")]
    for i in sorted(
        inside, key=lambda i: math.hypot(pos[i][0] - pos[door_id][0], pos[i][1] - pos[door_id][1])
    )[:2]:
        link(door_id, i, "door")

# ---- the stairs (estimated): anchored on the single mid-flight scan position
anchor = mid_flight or STAIRS_ANCHOR


def nearest(level, point):
    return min(
        (i for i in level_nodes[level] if not i.startswith("entrance")),
        key=lambda i: math.hypot(pos[i][0] - point[0], pos[i][1] - point[1]),
    )


stair_low, stair_up = nearest(lower, anchor), nearest(upper, anchor)
for node in nodes:
    if node["id"] == stair_low:
        node.update(kind="stairs", label="Stairs (lower level, estimated position)")
    if node["id"] == stair_up:
        node.update(kind="stairs", label="Stairs (upper level, estimated position)")
edges += [
    {
        "from": stair_low,
        "to": stair_up,
        "meters": STAIRS_M,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": STAIRS_UP_S,
    },
    {
        "from": stair_up,
        "to": stair_low,
        "meters": STAIRS_M,
        "kind": "stairs",
        "stretcher_ok": True,
        "seconds": STAIRS_DOWN_S,
    },
]

# ---- patient locations (labels the agent can search for)
by_id = {n["id"]: n for n in nodes}


def label_nearest(level, point, label, tag=None, inside=None):
    pool = [
        i
        for i in level_nodes[level]
        if not i.startswith("entrance") and by_id[i]["kind"] == "corridor"
    ]
    if inside is not None:
        pool = [i for i in pool if inside.buffer(0.3).contains(Point(pos[i]))] or pool
    best = min(pool, key=lambda i: math.hypot(pos[i][0] - point[0], pos[i][1] - point[1]))
    by_id[best].update(kind="door", label=label, tag_id=tag)
    return best


destinations = {}
class_idx = next(i for i, n in name_of.items() if n == "Classroom")
c = outline[class_idx].representative_point()
destinations["classroom"] = label_nearest(
    upper, (c.x, c.y), "Classroom (patient)", "TAG-CLASSROOM-01", outline[class_idx]
)
landings = [i for i, n in name_of.items() if n == "Landing" and level_of_room.get(i) == upper]
for k, i in enumerate(sorted(landings, key=lambda i: -outline[i].centroid.y)):
    p = outline[i].representative_point()
    side = "north" if k == 0 else "south"
    destinations[f"landing_{side}"] = label_nearest(
        upper, (p.x, p.y), f"Upper level landing, {side} side (patient)", None, outline[i]
    )
ring = outline[
    next(i for i, n in name_of.items() if kind_of[i] == "Hallway" and level_of_room.get(i) == upper)
]
rx, ry, rX, rY = ring.bounds
destinations["upper_corridor"] = label_nearest(
    upper, (rX - 1.0, (ry + rY) / 2), "Upper level corridor, east side (patient)"
)
hall = walkable[lower].centroid
destinations["atrium"] = label_nearest(
    lower, (hall.x, hall.y), "Atrium hall, lower level (patient)"
)

graph = {"building_id": "jrr", "nodes": nodes, "edges": edges}
(FIXTURES / "graph.json").write_text(json.dumps(graph, indent=2) + "\n", encoding="utf-8")
print(
    f"wrote graph.json: {len(nodes)} nodes ({len(level_nodes[lower])} lower, {len(level_nodes[upper])} upper), {len(edges)} edges ({joined} walking links)"
)
print(
    f"skipped {skipped} camera positions outside the room outlines | entrance alcoves: {len(alcoves)} | stairs anchor {tuple(round(v, 1) for v in anchor)}: {stair_low} -> {stair_up}"
)
print("patient locations:", {k: by_id[v]["label"] for k, v in destinations.items()})
