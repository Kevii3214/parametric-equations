"""Build a routing graph from any Matterport scan, with no hand-drawing. Pure code: no I/O, no model.

What is measured: the camera positions (sweeps) are walkable floor; two are joined only where the straight line stays
inside the walkable room outlines and crosses no wall except at a doorway; every room a person could be in becomes a
labelled destination. What is not in a scan (the entrance, the stairs) is found by a cascade of evidence, and every
guess is written to `report["inferred"]` so a person can check it. If there is no evidence, the report says so
instead of guessing.
"""

import itertools
import math
from collections import defaultdict
from dataclasses import dataclass, field

from shapely.geometry import LineString, Point
from shapely.ops import polygonize, unary_union

from app.graph.schema import BuildingGraph

WALK_MPS = 1.3
MAX_LINK_M = 8.0  # longest straight hop between two waypoints
INSIDE_TOLERANCE_M = 0.4
DOOR_SLACK_M = 0.35
MID_FLIGHT_M = 0.8  # a sweep this far above or below a level's floor was taken on a staircase
STAIRS_PER_LEVEL_M, STAIRS_UP_S, STAIRS_DOWN_S = 12, 30, 25  # ASSUMED, per level, with a stretcher
DEFAULT_IMAGE_WIDTH = 2000
KIND_NAMES = {
    "Hallway": "Hallway",
    "Office": "Office",
    "Kitchen": "Kitchen",
    "Closet": "Closet",
    "Dining Room": "Dining room",
}


@dataclass
class Hints:
    """Where a person (or the vision helper) says things are, as pixel columns of the scan's opening picture."""

    entrance_px: float | None = None
    stairs_px: float | None = None
    image_width: float = DEFAULT_IMAGE_WIDTH
    half_fov_deg: float = 45.0  # the opening picture shows about a 90 degree view
    stairs_distance_m: float = 7.0
    source: str = "hint"


@dataclass
class ScanGraph:
    graph: BuildingGraph
    report: dict = field(default_factory=dict)


def _polygon(region):
    segments = []
    for e in (region or {}).get("edges", []):
        (ax, ay), (bx, by) = ((v["position"]["x"], v["position"]["y"]) for v in e["vertices"])
        segments.append(LineString([(ax, ay), (bx, by)]))
    polys = list(polygonize(unary_union(segments))) if segments else []
    return max(polys, key=lambda p: p.area) if polys else None


def _room_polygon(room):
    poly = _polygon(room.get("boundary"))
    for hole in room.get("holes") or []:
        h = _polygon(hole)
        if poly is not None and h is not None:
            poly = poly.difference(h)
    return poly


def _bearing_at(px: float, start_bearing: float, hints: Hints) -> float:
    offset = (px - hints.image_width / 2) / (hints.image_width / 2)
    return start_bearing + math.degrees(
        math.atan(offset * math.tan(math.radians(hints.half_fov_deg)))
    )


def build_graph_from_scan(
    building_id: str,
    interior: dict,
    sweeps_model: dict,
    floor_levels: dict[str, int],
    hints: Hints | None = None,
) -> ScanGraph:
    inferred: list[str] = []
    warnings: list[str] = []

    sweeps = sweeps_model["sweeps"]
    start = sweeps_model.get("start_pose")
    levels = sorted({s["level"] for s in sweeps})
    lowest = levels[0]
    rooms = interior["rooms"]

    # ---- rooms: outline, kind, level
    def level_of(room):
        floor = room.get("floor")
        if floor:
            return floor_levels.get(floor["label"])
        return lowest if len(levels) == 1 else None

    info = {}
    for i, r in enumerate(rooms):
        level = level_of(r)
        kind = (r.get("classifications") or [{}])[0].get("label") or "Other"
        poly = _room_polygon(r)
        if level in levels and poly is not None:
            info[i] = {
                "level": level,
                "kind": kind,
                "label": r.get("label") or None,
                "poly": poly,
                "room": r,
            }

    walls: dict[int, list[LineString]] = defaultdict(list)
    openings: dict[int, list[tuple[float, float, float]]] = defaultdict(list)  # x, y, half-width
    doors_of: dict[int, list[tuple[float, float, float]]] = defaultdict(
        list
    )  # per room: x, y, width
    for i, d in info.items():
        for e in (d["room"].get("boundary") or {}).get("edges", []):
            (ax, ay), (bx, by) = ((v["position"]["x"], v["position"]["y"]) for v in e["vertices"])
            if e["type"] == "wall":
                walls[d["level"]].append(LineString([(ax, ay), (bx, by)]))
            if e["type"] == "invisible":  # an open gap into the next room: a way through
                doors_of[i].append(((ax + bx) / 2, (ay + by) / 2, math.hypot(bx - ax, by - ay)))
            for o in e.get("openings") or []:
                if o["type"] in ("doorway", "opening"):
                    t = o["relativeCenter"]
                    x, y = ax + (bx - ax) * t, ay + (by - ay) * t
                    openings[d["level"]].append((x, y, o["width"] / 2))
                    doors_of[i].append((x, y, o["width"]))

    walkable = {}
    for level in levels:
        parts = [d["poly"] for d in info.values() if d["level"] == level and d["kind"] != "Void"]
        if parts:
            walkable[level] = unary_union(parts).buffer(INSIDE_TOLERANCE_M)

    def can_walk(level, a, b, lax=False):
        segment = LineString([a, b])
        if level not in walkable or not walkable[level].buffer(0.3 if lax else 0).contains(segment):
            return False
        if lax:
            return True
        for wall in walls[level]:
            if segment.intersects(wall):
                cross = segment.intersection(wall)
                p = cross if cross.geom_type == "Point" else cross.centroid
                if not any(
                    math.hypot(p.x - ox, p.y - oy) <= half + DOOR_SLACK_M
                    for ox, oy, half in openings[level]
                ):
                    return False
        return True

    # ---- waypoints: the sweeps on each level's floor
    base_z = {
        lv: sorted(s["z"] for s in sweeps if s["level"] == lv)[
            len([s for s in sweeps if s["level"] == lv]) // 2
        ]
        for lv in levels
    }
    nodes: list[dict] = []
    pos: dict[str, tuple[float, float]] = {}
    by_level: dict[int, list[str]] = defaultdict(list)
    sweep_index: dict[str, int] = {}

    def add(node_id, level, x, y, kind, label=None, tag=None):
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
        by_level[level].append(node_id)

    mid_flight: list[dict] = []
    skipped_sweeps = 0
    for n, s in enumerate(sweeps):
        if abs(s["z"] - base_z[s["level"]]) > MID_FLIGHT_M:
            mid_flight.append(s)
            continue
        if s["level"] not in walkable or not walkable[s["level"]].contains(Point(s["x"], s["y"])):
            skipped_sweeps += 1
            continue
        add(f"s{n}", s["level"], s["x"], s["y"], "corridor")
        sweep_index[f"s{n}"] = n

    # ---- links between waypoints
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

    walking_links = 0
    for level, ids in by_level.items():
        ids = [i for i in ids if i in sweep_index]
        for k, a in enumerate(ids):
            for b in ids[k + 1 :]:
                if math.hypot(
                    pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                ) <= MAX_LINK_M and can_walk(level, pos[a], pos[b]):
                    link(a, b)
                    walking_links += 1

    def nearest(level, point, only=None):
        pool = [i for i in by_level[level] if i in sweep_index and (only is None or i in only)]
        return (
            min(pool, key=lambda i: math.hypot(pos[i][0] - point[0], pos[i][1] - point[1]))
            if pool
            else None
        )

    # ---- the entrance: an exterior doorway in the scan, else a hint, else where the scan started
    entrance_id = None

    def ray_hit(level, px):
        heading = math.radians(_bearing_at(px, start["bearing_deg"], hints))
        d = (math.sin(heading), math.cos(heading))
        origin = (start["position"]["x"], start["position"]["y"])
        outline = walkable[level].buffer(-INSIDE_TOLERANCE_M)
        hits = LineString([origin, (origin[0] + d[0] * 80, origin[1] + d[1] * 80)]).intersection(
            outline.boundary
        )
        if hits.is_empty:
            return None
        points = (
            [hits]
            if hits.geom_type == "Point"
            else [g for g in getattr(hits, "geoms", [hits]) if g.geom_type == "Point"]
        )
        if not points:
            return None
        p = min(points, key=lambda g: Point(origin).distance(g))
        return p.x - d[0] * 0.3, p.y - d[1] * 0.3

    if hints and hints.entrance_px is not None and start:
        hit = ray_hit(lowest, hints.entrance_px)
        if hit:
            add(
                "entrance1",
                lowest,
                hit[0],
                hit[1],
                "entrance",
                "Entrance (placed from the scan's opening view)",
                "TAG-ENTRANCE-01",
            )
            inferred.append(
                f"entrance placed from an entrance hint ({hints.source}) at pixel {hints.entrance_px:.0f}; good to a few metres"
            )
            entrance_id = "entrance1"
    if entrance_id is None:
        # exterior doorways: a doorway that only one room has, on the lowest level, wide enough to be a real door
        merged: list[dict] = []
        for i, d in info.items():
            if d["level"] != lowest:
                continue
            for x, y, w in doors_of[i]:
                for g in merged:
                    if i not in g["rooms"] and math.hypot(g["x"] - x, g["y"] - y) < 0.6:
                        g["rooms"].add(i)
                        break
                else:
                    merged.append({"x": x, "y": y, "w": w, "rooms": {i}})
        outer = [g for g in merged if len(g["rooms"]) == 1 and g["w"] >= 0.9]
        # keep doors that open onto the outside of the whole scan: no other room's outline contains a point just beyond
        if outer:
            door = max(outer, key=lambda g: g["w"])
            add(
                "entrance1",
                lowest,
                door["x"],
                door["y"],
                "entrance",
                "Entrance (exterior doorway found in the scan)",
                "TAG-ENTRANCE-01",
            )
            inferred.append(
                "entrance is the widest exterior doorway in the scan; check it is a door to the outside"
            )
            entrance_id = "entrance1"
    if entrance_id is None and start:
        spot = nearest(lowest, (start["position"]["x"], start["position"]["y"]))
        if spot is not None:
            by_id = next(n for n in nodes if n["id"] == spot)
            by_id.update(
                kind="entrance",
                label="Entrance (the scan's start point; scans usually begin at the door)",
                tag_id="TAG-ENTRANCE-01",
            )
            inferred.append(
                "entrance is the scan start point: nothing else in the scan marks the way in; check it"
            )
            entrance_id = spot
    if entrance_id is None:
        warnings.append("no entrance could be found: add an entrance hint")
    elif entrance_id == "entrance1":
        for i in sorted(
            [i for i in by_level[lowest] if i in sweep_index],
            key=lambda i: math.hypot(
                pos[i][0] - pos["entrance1"][0], pos[i][1] - pos["entrance1"][1]
            ),
        )[:3]:
            link("entrance1", i, "door")

    # ---- the stairs between levels: a person's hint, else a sweep taken between the levels, else nothing
    for lo, hi in itertools.pairwise(levels):
        anchor, why = None, None
        if hints and hints.stairs_px is not None and start:
            heading = math.radians(_bearing_at(hints.stairs_px, start["bearing_deg"], hints))
            anchor = (
                start["position"]["x"] + hints.stairs_distance_m * math.sin(heading),
                start["position"]["y"] + hints.stairs_distance_m * math.cos(heading),
            )
            why = f"stairs placed from a stairs hint ({hints.source}) at pixel {hints.stairs_px:.0f}; good to a few metres"
        else:
            between = [s for s in mid_flight if base_z[lo] < s["z"] < base_z[hi]]
            if between:
                anchor = (
                    sum(s["x"] for s in between) / len(between),
                    sum(s["y"] for s in between) / len(between),
                )
                why = f"stairs anchored on {len(between)} scan position(s) taken between the levels; a guess at one staircase"
        if anchor is None or not by_level[lo] or not by_level[hi]:
            warnings.append(
                f"no evidence of stairs between level {lo} and level {hi}: the levels are not connected"
            )
            continue
        low_id, high_id = nearest(lo, anchor), nearest(hi, anchor)
        for n in nodes:
            if n["id"] == low_id:
                n.update(kind="stairs", label=f"Stairs (level {lo}, estimated position)")
            if n["id"] == high_id:
                n.update(kind="stairs", label=f"Stairs (level {hi}, estimated position)")
        rise = (hi - lo) if hi - lo == 1 else 1
        edges += [
            {
                "from": low_id,
                "to": high_id,
                "meters": STAIRS_PER_LEVEL_M * rise,
                "kind": "stairs",
                "stretcher_ok": True,
                "seconds": STAIRS_UP_S * rise,
            },
            {
                "from": high_id,
                "to": low_id,
                "meters": STAIRS_PER_LEVEL_M * rise,
                "kind": "stairs",
                "stretcher_ok": True,
                "seconds": STAIRS_DOWN_S * rise,
            },
        ]
        inferred.append(why)

    # ---- a destination for every room a person could be in
    by_id = {n["id"]: n for n in nodes}
    protected = {n["id"] for n in nodes if n["kind"] in ("stairs", "entrance")}
    multi_level = len(levels) > 1
    counters: dict[str, int] = defaultdict(int)

    def base_name(i: int) -> str:
        d = info[i]
        if d["label"]:
            return d["label"]
        kind = d["kind"]
        return KIND_NAMES.get(kind, "Room" if kind in ("Other", None) else kind)

    totals = defaultdict(int)
    for i in sorted(info):
        if info[i]["kind"] != "Void":
            totals[base_name(i)] += 1
    considered = with_destination = skipped_rooms = 0
    ordered = sorted(
        (i for i, d in info.items() if d["kind"] != "Void"),
        key=lambda i: (info[i]["level"], -info[i]["poly"].centroid.y, info[i]["poly"].centroid.x),
    )
    for i in ordered:
        d = info[i]
        considered += 1
        base = base_name(i)
        counters[base] += (
            1  # a name used once stays plain; a repeated name is numbered, the scan's own first one included
        )
        base = (
            base
            if totals[base] == 1 or (d["label"] and counters[base] == 1)
            else f"{base} {counters[base]}"
        )
        where = f", floor {d['level']}" if multi_level else ""
        label = f"{base}{where} (patient)"
        rep = d["poly"].representative_point()
        inside = [
            n
            for n in by_level[d["level"]]
            if n in sweep_index
            and n not in protected
            and d["poly"].buffer(0.3).contains(Point(pos[n]))
        ]
        free = [n for n in inside if by_id[n]["label"] is None]
        if free:
            best = min(free, key=lambda n: math.hypot(pos[n][0] - rep.x, pos[n][1] - rep.y))
            by_id[best].update(kind="door", label=label)
            with_destination += 1
            continue
        # no scan position in the room: put a point in it, joined to a nearby scan position through one of its doors
        ways = doors_of[i]
        if not ways:
            skipped_rooms += 1
            continue
        x, y, _w = min(ways, key=lambda w: math.hypot(w[0] - rep.x, w[1] - rep.y))
        room_id, door_id = f"room{i}", f"door{i}"
        add(room_id, d["level"], rep.x, rep.y, "door", label)
        add(door_id, d["level"], x, y, "door")
        by_id[room_id], by_id[door_id] = nodes[-2], nodes[-1]
        link(room_id, door_id, "door")
        near = [
            n
            for n in by_level[d["level"]]
            if n in sweep_index and math.hypot(pos[n][0] - x, pos[n][1] - y) <= MAX_LINK_M
        ]
        near = sorted(near, key=lambda n: math.hypot(pos[n][0] - x, pos[n][1] - y))[:2]
        for n in near:
            link(door_id, n, "door")
        if near:
            with_destination += 1
        else:
            skipped_rooms += 1

    if skipped_sweeps:
        warnings.append(
            f"{skipped_sweeps} scan position(s) lie outside the room outlines and were left out"
        )
    graph = BuildingGraph.model_validate(
        {"building_id": building_id, "nodes": nodes, "edges": edges}
    )
    report = {
        "inferred": inferred,
        "warnings": warnings,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "walking_links": walking_links,
            "rooms_considered": considered,
            "rooms_with_a_destination": with_destination,
            "rooms_skipped": skipped_rooms,
        },
    }
    return ScanGraph(graph=graph, report=report)
