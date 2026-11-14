import asyncio
import json
import math
from pathlib import Path

import pytest

from app.graph.router import WALK_SPEED_MPS, find_route
from app.graph.schema import BuildingGraph
from app.providers.snapshot import SnapshotProvider

BUILDINGS = Path(__file__).resolve().parents[2] / "fixtures" / "buildings"
WILLIAMS = BUILDINGS / "233903"
DESTINATIONS = [
    "room29",
    "room23",
    "room27",
    "room5",
]  # conference room, kitchen, coworking space, north office


@pytest.fixture(scope="module")
def graph() -> BuildingGraph:
    return BuildingGraph.model_validate_json((WILLIAMS / "graph.json").read_text(encoding="utf-8"))


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
    assert not [
        n for n in graph.nodes if n.kind == "aed"
    ]  # nothing in the data shows where an AED is


def test_edge_times_are_never_faster_than_the_router_heuristic(graph):
    for e in graph.edges:
        assert e.seconds >= e.meters / WALK_SPEED_MPS - 1e-9, (e.from_node, e.to_node)


def measured_openings():
    interior = json.loads((WILLIAMS / "interior.json").read_text(encoding="utf-8"))
    for room in interior["models"][0]["rooms"]:
        for edge in (room.get("boundary") or {}).get("edges", []):
            (ax, ay), (bx, by) = (
                (v["position"]["x"], v["position"]["y"]) for v in edge["vertices"]
            )
            if edge["type"] == "invisible":
                yield (ax + bx) / 2, (ay + by) / 2
            for opening in edge.get("openings") or []:
                t = opening["relativeCenter"]
                yield ax + (bx - ax) * t, ay + (by - ay) * t


def test_the_suite_entrance_sits_on_a_measured_doorway(graph):
    door = next(n for n in graph.nodes if n.id == "door56")
    assert min(math.hypot(door.x - x, door.y - y) for x, y in measured_openings()) < 0.05


def test_every_passage_inside_the_suite_is_on_a_measured_doorway_or_gap(graph):
    passages = [n for n in graph.nodes if n.id.startswith("p")]
    assert len(passages) >= 20
    for node in passages:
        assert min(math.hypot(node.x - x, node.y - y) for x, y in measured_openings()) < 1.0, (
            node.id
        )


@pytest.mark.parametrize("start", ["st_main", "gar1"])
@pytest.mark.parametrize("goal", DESTINATIONS)
def test_every_patient_location_can_be_reached_from_both_entrances(graph, start, goal):
    steps = find_route(graph, start, goal)
    assert steps[-1].cue == "ARRIVE" and steps[-1].floor == 56
    assert [s.cue for s in steps].count("FLOOR_UP") == 1
    assert 60 < total_seconds(steps) < 300


def test_main_entrance_to_the_conference_room(graph):
    steps = find_route(graph, "st_main", "room29")
    assert nodes_of(steps)[:4] == ["st_main", "lob1", "el1", "el56"]
    assert "door56" in nodes_of(steps)
    assert total_seconds(steps) == 109


def test_the_garage_is_the_faster_way_in(graph):
    assert total_seconds(find_route(graph, "gar1", "room29")) < total_seconds(
        find_route(graph, "st_main", "room29")
    )


def test_elevators_out_means_a_very_long_climb(graph):
    steps = find_route(graph, "st_main", "room29", closures={"el1->el56"})
    assert "stair1" in nodes_of(steps) and "stair56" in nodes_of(steps)
    assert total_seconds(steps) > 1000
    assert steps[-1].cue == "ARRIVE"


# ----------------------------------------------------------- the saved snapshot


@pytest.fixture
def provider():
    return SnapshotProvider()


def run(coro):
    return asyncio.run(coro)


@pytest.mark.parametrize(
    "address", ["2800 Post Oak Blvd, Houston, TX", "Williams Tower", "williams tower houston"]
)
def test_williams_tower_is_found_by_address_or_name(provider, address):
    assert run(provider.resolve(address)) == "233903"


def test_the_first_building_is_still_found(provider):
    assert run(provider.resolve("1415 Louisiana St")) == "233928"


def test_the_snapshot_has_the_tower_facts_and_its_graph(provider):
    record = run(provider.record("233903"))
    assert record["name"] == "Williams Tower" and record["stories_above_grade"] == 64
    assert any(
        t["suite"] == "5600" and t["company"] == "Titan Global Advisory"
        for t in record["current_tenants"]
    )
    assert run(provider.graph("233903"))["building_id"] == "233903"
    assert run(provider.aerial("233903"))[:2] == b"\xff\xd8"


@pytest.mark.parametrize("goal", ["room29", "room5"])
def test_the_simulated_wearable_walks_the_williams_tower_routes_to_the_patient(graph, goal):
    from app.models import Telemetry
    from app.position.engine import PositionEngine
    from app.position.simulate import simulate

    steps = find_route(graph, "gar1", goal)
    tag_nodes = {n.tag_id: n.id for n in graph.nodes if n.tag_id}
    engine = PositionEngine(steps, tag_nodes=tag_nodes, stride_m=0.7)
    cues = []
    for raw in simulate(steps, stride_m=0.7, tags_at={v: k for k, v in tag_nodes.items()}):
        cues += [c.cue for c in engine.update(Telemetry(**raw)).cues]
    assert engine.arrived and engine.floor == 56 and not engine.off_route
    assert "OFF_ROUTE" not in cues and cues[-1] == "ARRIVE"
