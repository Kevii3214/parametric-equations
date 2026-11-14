import itertools
from pathlib import Path

import pytest

from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.models import Telemetry
from app.position.engine import PositionEngine
from app.position.simulate import simulate

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
STRIDE = 0.7


def route_on(graph_file, start, goal):
    graph = BuildingGraph.model_validate_json(graph_file.read_text(encoding="utf-8"))
    return graph, find_route(graph, start, goal)


@pytest.fixture(scope="module")
def fixture_route():
    return route_on(FIXTURES / "building_graph.json", "n1", "n10")[1]


@pytest.fixture(scope="module")
def demo():
    return route_on(FIXTURES / "buildings" / "233928" / "graph.json", "st_main", "phone_door")


def follow(steps, tag_nodes=None, tags_at=None):
    """Run the simulated wearable through a fresh engine; return the engine and everything it wrote."""
    engine = PositionEngine(steps, tag_nodes=tag_nodes or {}, stride_m=STRIDE)
    cues, effects = [], []
    for raw in simulate(steps, stride_m=STRIDE, tags_at=tags_at):
        update = engine.update(Telemetry(**raw))
        cues += [c.cue for c in update.cues]
        effects += update.effects
    return engine, cues, effects


def test_samples_follow_the_telemetry_contract(fixture_route):
    samples = list(simulate(fixture_route, stride_m=STRIDE))
    assert all(set(s) == {"t", "steps", "heading", "pressure", "btn", "tag"} for s in samples)
    assert all(Telemetry(**s) for s in samples)
    assert [b["t"] - a["t"] for a, b in itertools.pairwise(samples)] == [200] * (len(samples) - 1)
    assert all(b["steps"] >= a["steps"] for a, b in itertools.pairwise(samples))


def test_the_simulated_wearable_walks_the_fixture_route_to_the_end(fixture_route):
    engine, cues, effects = follow(fixture_route)
    assert engine.arrived and not engine.off_route and engine.floor == 14
    assert cues == ["LEFT", "FLOOR_UP", "RIGHT", "LEFT", "ARRIVE"]
    assert "arrived" in effects


def test_the_simulated_wearable_walks_the_demo_building_route_to_the_patient(demo):
    _graph, steps = demo
    engine, cues, _ = follow(steps)
    assert engine.arrived and not engine.off_route and engine.floor == 18
    assert cues[0] == "LEFT" and "FLOOR_UP" in cues and cues[-1] == "ARRIVE"
    assert "OFF_ROUTE" not in cues
    assert cues.count("FLOOR_UP") == 1


def test_rfid_scans_at_tagged_nodes_do_not_confuse_the_engine(demo):
    graph, steps = demo
    tag_nodes = {n.tag_id: n.id for n in graph.nodes if n.tag_id}
    engine, cues, _ = follow(
        steps, tag_nodes=tag_nodes, tags_at={v: k for k, v in tag_nodes.items()}
    )
    assert engine.arrived and not engine.off_route and "OFF_ROUTE" not in cues


def test_scans_are_emitted_where_asked(fixture_route):
    samples = list(
        simulate(
            fixture_route,
            stride_m=STRIDE,
            tags_at={"n1": "TAG-ENTRANCE-01", "n10": "TAG-SUITE-1420"},
        )
    )
    assert [s["tag"] for s in samples if s["tag"]] == ["TAG-ENTRANCE-01", "TAG-SUITE-1420"]


def test_a_faster_walker_makes_fewer_samples(fixture_route):
    slow = len(list(simulate(fixture_route, stride_m=STRIDE, speed_mps=1.0)))
    fast = len(list(simulate(fixture_route, stride_m=STRIDE, speed_mps=2.0)))
    assert fast < slow


def test_the_lift_ride_shows_up_as_a_pressure_drop(fixture_route):
    pressures = [
        s["pressure"] for s in simulate(fixture_route, stride_m=STRIDE, base_pressure=100000.0)
    ]
    assert min(pressures) < 100000.0 - 35 * 13  # 13 floors up
