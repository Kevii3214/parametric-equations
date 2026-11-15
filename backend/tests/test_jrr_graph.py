import asyncio
import json
import math
from pathlib import Path

import networkx as nx
import pytest

from app.graph.router import WALK_SPEED_MPS, NoRouteError, build_digraph, find_route
from app.graph.schema import BuildingGraph
from app.models import Telemetry
from app.position.engine import PositionEngine
from app.position.simulate import simulate
from app.providers.snapshot import SnapshotProvider

JRR = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "jrr"
UPPER_PATIENTS = ["Classroom", "landing, north", "landing, south", "corridor, east"]


@pytest.fixture(scope="module")
def graph() -> BuildingGraph:
    return BuildingGraph.model_validate_json((JRR / "graph.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def patients(graph):
    return {n.label: n for n in graph.nodes if n.label and "(patient)" in n.label}


def total_seconds(steps):
    return sum(s.seconds for s in steps)


def test_graph_is_well_formed_and_one_connected_piece(graph):
    ids = [n.id for n in graph.nodes]
    assert len(ids) == len(set(ids))
    assert all(e.from_node in ids and e.to_node in ids for e in graph.edges)
    assert nx.number_weakly_connected_components(build_digraph(graph, [])) == 1
    tags = [n.tag_id for n in graph.nodes if n.tag_id]
    assert len(tags) == len(set(tags))


def test_edge_times_are_never_faster_than_the_router_heuristic(graph):
    for e in graph.edges:
        assert e.seconds >= e.meters / WALK_SPEED_MPS - 1e-9, (e.from_node, e.to_node)


def test_nothing_is_invented_that_the_scan_does_not_show(graph):
    assert not [n for n in graph.nodes if n.kind in ("aed", "elevator")]
    assert len([n for n in graph.nodes if n.kind == "entrance"]) == 1


def test_waypoints_sit_where_the_scan_camera_stood(graph):
    model = json.loads((JRR / "interior.json").read_text(encoding="utf-8"))["models"][0]
    camera = [(l["position"]["x"], l["position"]["y"]) for l in model["locations"]]
    waypoints = [n for n in graph.nodes if n.id.startswith("s")]
    assert len(waypoints) >= 60
    for n in waypoints:
        assert min(math.hypot(n.x - x, n.y - y) for x, y in camera) < 0.02, n.id


def test_the_glass_entrance_is_on_the_east_wall_where_the_opening_view_shows_it(graph):
    """From the scan's start (0, 0) facing bearing 55.5 deg, the arched glass doors are right of centre."""
    entrance = next(n for n in graph.nodes if n.kind == "entrance")
    assert entrance.floor == 2 and 14.0 < entrance.x < 15.7 and 2.0 < entrance.y < 7.0
    model = json.loads((JRR / "interior.json").read_text(encoding="utf-8"))["models"][0]
    camera = [(l["position"]["x"], l["position"]["y"]) for l in model["locations"]]
    assert (
        min(math.hypot(entrance.x - x, entrance.y - y) for x, y in camera) < 2.5
    )  # people scanned right there


def test_the_stairs_are_where_the_opening_view_shows_the_glass_staircase(graph):
    """To the left of the start's view, 6 to 9 m out, against the north wall; the levels' scan positions stack there."""
    stairs = [n for n in graph.nodes if n.kind == "stairs"]
    assert {n.floor for n in stairs} == {2, 3}
    for n in stairs:
        assert math.hypot(n.x - 2.5, n.y - 6.5) < 3.0
    lower, upper = sorted(stairs, key=lambda n: n.floor)
    assert math.hypot(lower.x - upper.x, lower.y - upper.y) < 0.5


def test_the_classroom_route_goes_in_the_glass_entrance_across_the_hall_and_up_the_stairs(
    graph, patients
):
    classroom = next(n for label, n in patients.items() if "Classroom" in label)
    steps = find_route(graph, "entrance1", classroom.id)
    visited = [steps[0].from_node] + [s.to_node for s in steps]
    stairs = [n.id for n in graph.nodes if n.kind == "stairs"]
    assert all(s in visited for s in stairs)
    assert total_seconds(steps) < 70


def test_there_are_five_scanned_patient_locations_and_two_lower_level_demo_stops(patients):
    scanned = {k: n for k, n in patients.items() if not k.startswith("Demo stop")}
    assert len(scanned) == 5 and len(patients) == 7
    assert {n.floor for n in patients.values()} == {2, 3}


def test_the_demo_stops_give_a_straight_walk_with_one_right_and_one_left_turn_and_no_stairs(
    graph, patients
):
    for name, turn in ("Demo stop A", "RIGHT"), ("Demo stop B", "LEFT"):
        node = next(n for label, n in patients.items() if label.startswith(name))
        steps = find_route(graph, "entrance1", node.id)
        assert [s.cue for s in steps if s.cue in ("LEFT", "RIGHT", "UTURN")] == [turn]
        assert node.floor == 2 and {s.floor for s in steps} == {2}


def test_the_hall_is_reached_without_stairs_and_the_upper_level_with_one_climb(graph, patients):
    for label, node in patients.items():
        steps = find_route(graph, "entrance1", node.id)
        assert steps[-1].cue == "ARRIVE" and steps[-1].floor == node.floor
        climbs = [s.cue for s in steps].count("FLOOR_UP")
        assert climbs == (1 if node.floor == 3 else 0), label
        assert 5 < total_seconds(steps) < 120, label


def test_the_stairs_are_the_only_way_up_so_closing_them_cuts_off_the_upper_level(graph, patients):
    stairs = [e for e in graph.edges if e.kind == "stairs"]
    assert len(stairs) == 2 and {graph_node_floor(graph, e.from_node) for e in stairs} == {2, 3}
    closed = f"{stairs[0].from_node}->{stairs[0].to_node}"
    upper = next(n for n in patients.values() if n.floor == 3)
    with pytest.raises(NoRouteError):
        find_route(graph, "entrance1", upper.id, closures={closed})


def graph_node_floor(graph, node_id):
    return next(n.floor for n in graph.nodes if n.id == node_id)


@pytest.mark.parametrize("label_part", ["Classroom", "Atrium", "corridor, east"])
def test_the_simulated_wearable_walks_to_the_patient(graph, patients, label_part):
    goal = next(n for label, n in patients.items() if label_part in label)
    steps = find_route(graph, "entrance1", goal.id)
    tag_nodes = {n.tag_id: n.id for n in graph.nodes if n.tag_id}
    engine = PositionEngine(steps, tag_nodes=tag_nodes, stride_m=0.7)
    cues = []
    for raw in simulate(steps, stride_m=0.7, tags_at={v: k for k, v in tag_nodes.items()}):
        cues += [c.cue for c in engine.update(Telemetry(**raw)).cues]
    assert engine.arrived and not engine.off_route and "OFF_ROUTE" not in cues
    assert engine.floor == goal.floor and cues[-1] == "ARRIVE"


# ----------------------------------------------------------- the saved snapshot


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "address",
    ["JRR", "the JRR building, Princeton", "Rabinowitz Hall, Princeton University", "Rabinowitz"],
)
def test_the_building_is_found_by_its_names(address):
    assert run(SnapshotProvider().resolve(address)) == "jrr"


def test_other_buildings_are_still_found():
    provider = SnapshotProvider()
    assert run(provider.resolve("1415 Louisiana St")) == "233928"
    assert run(provider.resolve("Williams Tower")) == "233903"


def test_the_record_says_plainly_that_it_is_not_from_costar():
    record = run(SnapshotProvider().record("jrr"))
    assert record["name"] == "Rabinowitz Hall (JRR)"
    assert "not in the CoStar kit" in record["source"]
    assert any("Not a CoStar building" in note for note in record["data_quality_notes"])
    assert record["elevators"] == []
