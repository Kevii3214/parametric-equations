"""Turn a route into a fly-through "tour" for the 3D viewer. Pure code: no I/O, no model.

The router decides where the crew walks. This only decides how the viewer follows that route through the
Matterport scan: which sweep (camera position) to fly to, which way to face, how long to stay, and which parts
of the route no scan covers (the viewer should show the map or aerial view there instead).
"""

import heapq
import math
from typing import Literal

from pydantic import BaseModel

from app.graph.schema import BuildingGraph, RouteStep

COVER_M = 3.0  # a route stop counts as scanned if a sweep on its level is this close
WALK_MPS = 1.3
MIN_HOP_MS = 1200  # the shortest move between two stops, so the flight never jerks
TURN_DWELL_MS = 700  # pause at a turn so the caption can be read
END_DWELL_MS = 2000
DEFAULT_SPEED_UP = 6.0  # a 100 s walk plays in about 17 s


class Point(BaseModel):
    x: float
    y: float
    z: float


class StartPose(BaseModel):
    """A scan's opening camera view: lets the frontend check the viewer's compass against the plan's."""

    position: Point
    bearing_deg: float
    pitch_deg: float


class Keyframe(BaseModel):
    i: int
    t_ms: int  # when the viewer should arrive here
    dwell_ms: int  # how long to stay before moving on (already included in the next t_ms)
    kind: Literal["scanned", "gap"]
    frame: Literal[
        "scan", "plan"
    ]  # scan: metres in the scan's frame; plan: the graph's plan frame (not scanned)
    node: str
    step_index: int  # the route step that arrives here; -1 for the start
    waypoint: bool  # a stop on the route itself (False: an in-between sweep along the way)
    model_id: str | None
    sweep_id: str | None
    position: Point
    level: int
    bearing_deg: float  # compass bearing to face (0 = +y, 90 = +x), toward the next stop
    pitch_deg: float
    transition: Literal["none", "fly", "fade"]
    caption: str
    cue: str | None


class Segment(BaseModel):
    kind: Literal["scanned", "gap"]
    from_step: int
    to_step: int
    model_id: str | None = None
    reason: str | None = None


class Tour(BaseModel):
    version: int = 1
    speed_up: float
    duration_ms: int
    segments: list[Segment]
    keyframes: list[Keyframe]
    models: dict[str, StartPose]


def _dist(a, b) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _bearing(a, b) -> float:
    return round(math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360, 1)


def _sweep_path(
    sweeps: dict[str, dict], start: str, goal: str, level: int | None
) -> list[str] | None:
    """Shortest chain of visible-from-each-other sweeps from start to goal (staying on one level if given)."""
    if start == goal:
        return [start]
    adjacency: dict[str, set[str]] = {sid: set() for sid in sweeps}
    for sid, s in sweeps.items():
        for other in s["neighbors"]:
            if other in sweeps:
                adjacency[sid].add(other)
                adjacency[other].add(sid)
    best = {start: 0.0}
    came: dict[str, str] = {}
    queue = [(0.0, start)]
    while queue:
        cost, here = heapq.heappop(queue)
        if here == goal:
            chain = [goal]
            while chain[-1] != start:
                chain.append(came[chain[-1]])
            return chain[::-1]
        if cost > best.get(here, math.inf):
            continue
        for nxt in adjacency[here]:
            if level is not None and sweeps[nxt]["level"] != level:
                continue
            nc = cost + _dist(
                (sweeps[here]["x"], sweeps[here]["y"]), (sweeps[nxt]["x"], sweeps[nxt]["y"])
            )
            if nc < best.get(nxt, math.inf):
                best[nxt], came[nxt] = nc, here
                heapq.heappush(queue, (nc, nxt))
    return None


def build_tour(
    steps: list[RouteStep],
    graph: BuildingGraph,
    scans: dict | None,
    speed_up: float = DEFAULT_SPEED_UP,
) -> dict | None:
    """The tour for a route as JSON, or None when the building has no scan data to fly through."""
    if not steps or not scans or not scans.get("models"):
        return None
    nodes = {n.id: n for n in graph.nodes}
    path = [steps[0].from_node] + [s.to_node for s in steps]

    sweeps: dict[str, dict] = {}
    model_of: dict[str, str] = {}
    for model in scans["models"]:
        for s in model["sweeps"]:
            sweeps[s["id"]] = s
            model_of[s["id"]] = model["id"]
    by_level: dict[int, list[dict]] = {}
    for s in sweeps.values():
        by_level.setdefault(s["level"], []).append(s)

    def nearest_sweep(node_id: str) -> dict | None:
        n = nodes[node_id]
        candidates = by_level.get(n.floor, [])
        if not candidates:
            return None
        best = min(candidates, key=lambda s: _dist((s["x"], s["y"]), (n.x, n.y)))
        return best if _dist((best["x"], best["y"]), (n.x, n.y)) <= COVER_M else None

    stop = [
        nearest_sweep(p) for p in path
    ]  # the sweep each route stop maps to, or None when not scanned
    if not any(stop):
        return None

    # ---- the stops, with in-between sweeps where two scanned stops are joined by a chain of sweeps
    raw: list[dict] = []

    def add(node_id, step_index, sweep, waypoint, transition):
        n = nodes[node_id]
        raw.append(
            {
                "node": node_id,
                "step_index": step_index,
                "sweep": sweep,
                "waypoint": waypoint,
                "transition": transition,
                "plan": (n.x, n.y),
                "level": n.floor,
            }
        )

    for k, node_id in enumerate(path):
        step = steps[k - 1] if k > 0 else None
        sweep = stop[k]
        if k == 0:
            add(node_id, -1, sweep, True, "none")
            continue
        previous = stop[k - 1]
        if sweep is not None and previous is not None:
            same_level = previous["level"] == sweep["level"]
            chain = (
                _sweep_path(sweeps, previous["id"], sweep["id"], previous["level"])
                if same_level
                else None
            )
            if chain:
                for mid in chain[1:-1]:
                    add(node_id, k - 1, sweeps[mid], False, "fly")
                transition = "fly" if previous["id"] != sweep["id"] else "none"
            else:
                transition = "fade"  # a change of level (or no visible chain): cut, don't fly through the ceiling
            add(node_id, k - 1, sweep, True, transition)
        else:
            add(node_id, k - 1, sweep, True, "fade" if sweep is not None else "none")

    # ---- facing, timing and wording
    keyframes: list[Keyframe] = []
    t = 0
    for idx, r in enumerate(raw):
        scanned = r["sweep"] is not None
        here = (r["sweep"]["x"], r["sweep"]["y"]) if scanned else r["plan"]
        step = steps[r["step_index"]] if r["step_index"] >= 0 else None
        # face the next stop when it is in the same frame and level; otherwise keep the previous heading
        bearing = keyframes[-1].bearing_deg if keyframes else 0.0
        if idx + 1 < len(raw):
            nxt = raw[idx + 1]
            n_scanned = nxt["sweep"] is not None
            there = (nxt["sweep"]["x"], nxt["sweep"]["y"]) if n_scanned else nxt["plan"]
            if n_scanned == scanned and nxt["level"] == r["level"] and _dist(here, there) > 0.05:
                bearing = _bearing(here, there)
        if idx == 0:
            caption = f"Start: {nodes[r['node']].label or r['node']}"
        elif r["waypoint"]:
            caption = step.text
        else:
            caption = ""
        cue = step.cue if (step and r["waypoint"]) else None
        dwell = TURN_DWELL_MS if cue in ("LEFT", "RIGHT", "UTURN", "FLOOR_UP", "FLOOR_DOWN") else 0
        if idx == len(raw) - 1:
            dwell = END_DWELL_MS
        if idx > 0:
            prev = keyframes[-1]
            hop_m = (
                _dist((prev.position.x, prev.position.y), here)
                if prev.frame == ("scan" if scanned else "plan")
                else 0.0
            )
            if (
                step is not None
                and step.floor != steps[max(r["step_index"] - 1, 0)].floor
                and r["waypoint"]
                and r["step_index"] > 0
                or (step is not None and r["waypoint"] and step.meters == 0)
            ):
                move_ms = step.seconds * 1000 / speed_up  # a lift ride or climb takes its real time
            elif not scanned:
                move_ms = (step.seconds * 1000 / speed_up) if step is not None else 0
            else:
                move_ms = hop_m / (WALK_MPS * speed_up) * 1000
            t += prev.dwell_ms + max(MIN_HOP_MS, int(move_ms))
        keyframes.append(
            Keyframe(
                i=idx,
                t_ms=t,
                dwell_ms=dwell,
                kind="scanned" if scanned else "gap",
                frame="scan" if scanned else "plan",
                node=r["node"],
                step_index=r["step_index"],
                waypoint=r["waypoint"],
                model_id=model_of[r["sweep"]["id"]] if scanned else None,
                sweep_id=r["sweep"]["id"] if scanned else None,
                position=Point(x=here[0], y=here[1], z=r["sweep"]["z"] if scanned else 0.0),
                level=r["sweep"]["level"] if scanned else r["level"],
                bearing_deg=bearing,
                pitch_deg=0.0,
                transition=r["transition"],
                caption=caption,
                cue=cue,
            )
        )

    # ---- segments: consecutive steps whose both ends are scanned are flown; the rest are gaps
    step_scanned = [stop[i] is not None and stop[i + 1] is not None for i in range(len(steps))]
    segments: list[Segment] = []
    i = 0
    while i < len(steps):
        j = i
        while j + 1 < len(steps) and step_scanned[j + 1] == step_scanned[i]:
            j += 1
        if step_scanned[i]:
            segments.append(
                Segment(kind="scanned", from_step=i, to_step=j, model_id=model_of[stop[i]["id"]])
            )
        else:
            segments.append(
                Segment(
                    kind="gap",
                    from_step=i,
                    to_step=j,
                    reason="not scanned: show the map or aerial view here",
                )
            )
        i = j + 1

    models = {
        m["id"]: StartPose.model_validate(m["start_pose"])
        for m in scans["models"]
        if m.get("start_pose")
    }
    last = keyframes[-1]
    return Tour(
        speed_up=speed_up,
        duration_ms=last.t_ms + last.dwell_ms,
        segments=segments,
        keyframes=keyframes,
        models=models,
    ).model_dump(mode="json")
