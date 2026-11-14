import json
import math
from pathlib import Path

import pytest

from app.graph.router import WALK_SPEED_MPS, find_route
from app.graph.schema import BuildingGraph

DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928"
PATIENT = "phone_door"


@pytest.fixture(scope="module")
def graph() -> BuildingGraph:
    return BuildingGraph.model_validate_json((DEMO / "graph.json").read_text(encoding="utf-8"))


def total_seconds(steps):
    return sum(s.seconds for s in steps)


def nodes_of(steps):
    return [steps[0].from_node] + [s.to_node for s in steps]


def test_graph_is_well_formed(graph):
    ids = [n.id for n in graph.nodes]
    assert len(ids) == len(set(ids))
    assert all(e.from_node in ids and e.to_node in ids for e in graph.edges)
    tags = [n.tag_id for n in graph.nodes if n.tag_id]
    assert len(tags) == len(set(tags))


def test_edge_times_are_never_faster_than_the_router_heuristic(graph):
    """Keeps A* optimal: an edge must not be quicker than walking its length at 1.3 m/s."""
    for e in graph.edges:
        assert e.seconds >= e.meters / WALK_SPEED_MPS - 1e-9, (e.from_node, e.to_node)


def doorway_positions(model_id):
    interior = json.loads((DEMO / "interior.json").read_text(encoding="utf-8"))
    model = next(m for m in interior["models"] if m["id"] == model_id)
    for room in model["rooms"]:
        for edge in (room.get("boundary") or {}).get("edges", []):
            (ax, ay), (bx, by) = (
                (v["position"]["x"], v["position"]["y"]) for v in edge["vertices"]
            )
            for opening in edge.get("openings") or []:
                t = opening["relativeCenter"]
                yield ax + (bx - ax) * t, ay + (by - ay) * t


@pytest.mark.parametrize("node_id", ["door18", "phone_door"])
def test_suite_doors_sit_on_measured_matterport_doorways(graph, node_id):
    node = next(n for n in graph.nodes if n.id == node_id)
    nearest = min(math.hypot(node.x - x, node.y - y) for x, y in doorway_positions("LJn59uoV759"))
    assert nearest < 0.05


def test_main_entrance_reaches_the_patient_by_elevator(graph):
    steps = find_route(graph, "st_main", PATIENT)
    assert nodes_of(steps) == [
        "st_main", "lob1", "el1", "el18", "hall18", "door18", "rec_a", "rec_b", PATIENT,
    ]  # fmt: skip
    assert steps[-1].cue == "ARRIVE" and steps[-1].floor == 18
    assert [s.cue for s in steps].count("FLOOR_UP") == 1
    assert total_seconds(steps) == 111


def test_garage_entrance_also_reaches_the_patient(graph):
    steps = find_route(graph, "gar1", PATIENT)
    assert nodes_of(steps)[:3] == ["gar1", "el1", "el18"]
    assert total_seconds(steps) < total_seconds(find_route(graph, "st_main", PATIENT))


def test_elevators_out_falls_back_to_stairs(graph):
    steps = find_route(graph, "st_main", PATIENT, closures={"el1->el18"})
    assert "stair1" in nodes_of(steps) and "stair18" in nodes_of(steps)
    assert total_seconds(steps) == 487
    assert steps[-1].cue == "ARRIVE"


def test_route_text_names_the_destination(graph):
    assert "phone room" in find_route(graph, "st_main", PATIENT)[-1].text.lower()
