"""Fastest stretcher-safe route through a building: A* over the graph. No I/O.

The router picks the path, never the LLM. See contracts/api.md for how each step's cue is chosen.
"""

import itertools
import math
from collections.abc import Iterable

import networkx as nx

from app.graph.schema import BuildingGraph, Cue, RouteStep

WALK_SPEED_MPS = 1.3  # used only by the A* heuristic
STAIRS_PENALTY_S = 1000.0  # makes stairs a last resort; not counted in a route's seconds
TURN_DEGREES = 45  # a heading change of at least this is a LEFT or RIGHT
UTURN_DEGREES = 135  # at least this is a U-turn


class NoRouteError(Exception):
    """There is no stretcher-safe path between the two nodes with the given closures."""


def build_digraph(graph: BuildingGraph, closures: Iterable[str]) -> nx.DiGraph:
    """Directed graph for A*. Edge cost = seconds, plus a large penalty on stairs.

    A closure is a node id ("n3") or an edge ("n3->n7"); a closed edge is blocked in both directions.
    """
    closed_nodes: set[str] = set()
    closed_edges: set[tuple[str, str]] = set()
    for closure in closures:
        if "->" in closure:
            a, b = (part.strip() for part in closure.split("->"))
            closed_edges |= {(a, b), (b, a)}
        else:
            closed_nodes.add(closure)

    digraph = nx.DiGraph()
    for node in graph.nodes:
        digraph.add_node(
            node.id, floor=node.floor, x=node.x, y=node.y, kind=node.kind, label=node.label
        )
    for edge in graph.edges:
        if not edge.stretcher_ok:
            continue
        if edge.from_node in closed_nodes or edge.to_node in closed_nodes:
            continue
        if (edge.from_node, edge.to_node) in closed_edges:
            continue
        cost = edge.seconds + (STAIRS_PENALTY_S if edge.kind == "stairs" else 0)
        digraph.add_edge(
            edge.from_node,
            edge.to_node,
            cost=cost,
            seconds=edge.seconds,
            meters=edge.meters,
            kind=edge.kind,
        )
    return digraph


def turn_cue(before: float, after: float) -> Cue:
    """Cue for changing from compass heading `before` to `after` (degrees, 0 = north, clockwise)."""
    delta = (after - before + 540) % 360 - 180  # -180 (inclusive) to 180 (exclusive)
    if abs(delta) >= UTURN_DEGREES:
        return "UTURN"
    if delta >= TURN_DEGREES:
        return "RIGHT"
    if delta <= -TURN_DEGREES:
        return "LEFT"
    return "STRAIGHT"


def find_route(
    graph: BuildingGraph, start: str, goal: str, closures: Iterable[str] = ()
) -> list[RouteStep]:
    """Turn-by-turn steps from `start` to `goal`. Empty if they are the same node.

    Raises LookupError for an unknown node and NoRouteError when no stretcher-safe path exists.
    """
    digraph = build_digraph(graph, frozenset(closures))
    for node_id in (start, goal):
        if node_id not in digraph:
            raise LookupError(f"Unknown node {node_id!r} in building {graph.building_id!r}")
    if start == goal:
        return []

    def heuristic(a: str, b: str) -> float:
        na, nb = digraph.nodes[a], digraph.nodes[b]
        if na["floor"] != nb["floor"]:
            return 0.0
        return math.hypot(na["x"] - nb["x"], na["y"] - nb["y"]) / WALK_SPEED_MPS

    try:
        path = nx.astar_path(digraph, start, goal, heuristic=heuristic, weight="cost")
    except nx.NetworkXNoPath as error:
        raise NoRouteError(f"No stretcher-safe route from {start} to {goal}") from error
    return _steps(digraph, path)


def _bearing(digraph: nx.DiGraph, a: str, b: str) -> float | None:
    """Compass bearing of the walk a -> b, or None when it changes floor or has no length."""
    na, nb = digraph.nodes[a], digraph.nodes[b]
    dx, dy = nb["x"] - na["x"], nb["y"] - na["y"]
    if na["floor"] != nb["floor"] or math.hypot(dx, dy) == 0:
        return None
    return math.degrees(math.atan2(dx, dy)) % 360


def _steps(digraph: nx.DiGraph, path: list[str]) -> list[RouteStep]:
    pairs = list(itertools.pairwise(path))
    steps = []
    for index, (a, b) in enumerate(pairs):
        edge = digraph.edges[a, b]
        floor_a, floor_b = digraph.nodes[a]["floor"], digraph.nodes[b]["floor"]
        last = index == len(pairs) - 1

        if last:
            cue: Cue = "ARRIVE"
        elif floor_b != floor_a:
            cue = "FLOOR_UP" if floor_b > floor_a else "FLOOR_DOWN"
        else:
            here, ahead = _bearing(digraph, a, b), _bearing(digraph, *pairs[index + 1])
            cue = "STRAIGHT" if here is None or ahead is None else turn_cue(here, ahead)

        steps.append(
            RouteStep(
                index=index,
                from_node=a,
                to_node=b,
                cue=cue,
                meters=edge["meters"],
                seconds=edge["seconds"],
                floor=floor_b,
                text=_text(cue, edge, digraph.nodes[b], floor_a, floor_b),
            )
        )
    return steps


def _text(cue: Cue, edge: dict, to_node: dict, floor_a: int, floor_b: int) -> str:
    if floor_a != floor_b:
        how = "Climb the stairs" if edge["kind"] == "stairs" else "Take the elevator"
        return f"{how} {'up' if floor_b > floor_a else 'down'} to floor {floor_b}."
    walk = f"Walk {edge['meters']:g} m"
    label = to_node["label"]
    match cue:
        case "ARRIVE":
            return f"{walk}. {label or 'Your destination'} is ahead."
        case "LEFT":
            return f"{walk}, then turn left."
        case "RIGHT":
            return f"{walk}, then turn right."
        case "UTURN":
            return f"{walk}, then turn around."
        case _:
            return f"{walk} to {label}." if label else f"{walk}."
