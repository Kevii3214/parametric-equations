import itertools
import json
from pathlib import Path

import networkx as nx
import pytest

from app.graph.router import STAIRS_PENALTY_S, NoRouteError, build_digraph, find_route, turn_cue
from app.graph.schema import BuildingGraph, RouteStep

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"


@pytest.fixture
def graph() -> BuildingGraph:
    return BuildingGraph.model_validate_json(
        (FIXTURES / "building_graph.json").read_text(encoding="utf-8")
    )


def nodes_of(steps):
    return [steps[0].from_node] + [s.to_node for s in steps]


def total_seconds(steps):
    return sum(s.seconds for s in steps)


def graph_with(graph, edge_changes):
    """Copy of the graph with the given (from, to) edges changed, e.g. {("n3", "n7"): {"stretcher_ok": False}}."""
    data = graph.model_dump(by_alias=True)
    for edge in data["edges"]:
        edge.update(edge_changes.get((edge["from"], edge["to"]), {}))
    return BuildingGraph.model_validate(data)


# ---------------------------------------------------------------- the fixture graph


def test_fixture_graph_is_valid(graph):
    assert len(graph.nodes) == 12
    assert all(isinstance(n.floor, int) for n in graph.nodes)


def test_main_entrance_to_suite_matches_fixture_route(graph):
    steps = find_route(graph, "n1", "n10")
    expected = json.loads((FIXTURES / "route.json").read_text(encoding="utf-8"))
    keys = ["index", "from_node", "to_node", "cue", "meters", "seconds", "floor"]
    assert [{k: getattr(s, k) for k in keys} for s in steps] == [
        {k: e[k] for k in keys} for e in expected
    ]
    assert total_seconds(steps) == 90


def test_steps_follow_the_route_contract(graph):
    for step in find_route(graph, "n1", "n10"):
        RouteStep.model_validate(step.model_dump())
        assert step.text


def test_last_step_is_arrive(graph):
    assert find_route(graph, "n1", "n10")[-1].cue == "ARRIVE"


def test_start_equal_to_goal_is_an_empty_route(graph):
    assert find_route(graph, "n10", "n10") == []


def test_other_entrance_works(graph):
    steps = find_route(graph, "n4", "n10")
    assert nodes_of(steps)[0] == "n4" and nodes_of(steps)[-1] == "n10"
    assert "n3" in nodes_of(steps)


# ------------------------------------------------------------------ closures


def test_closed_elevator_reroutes_by_stairs(graph):
    steps = find_route(graph, "n1", "n10", closures={"n3->n7"})
    assert nodes_of(steps) == ["n1", "n12", "n2", "n3", "n6", "n11", "n8", "n9", "n10"]
    assert total_seconds(steps) == 254  # the stairs climb is 200 s on its own


def test_closed_edge_blocks_both_directions(graph):
    steps = find_route(graph, "n10", "n1", closures={"n3->n7"})
    assert "n7" not in nodes_of(steps)


def test_closed_node_is_avoided(graph):
    steps = find_route(graph, "n4", "n10", closures={"n2"})
    assert "n2" not in nodes_of(steps)


def test_no_route_when_elevator_and_stairs_are_closed(graph):
    with pytest.raises(NoRouteError):
        find_route(graph, "n1", "n10", closures={"n3->n7", "n6->n11"})


def test_closing_the_only_way_in_raises(graph):
    with pytest.raises(NoRouteError):
        find_route(graph, "n1", "n10", closures={"n3"})


# --------------------------------------------------------------- constraints


def test_edges_that_are_not_stretcher_safe_are_skipped(graph):
    changed = graph_with(graph, {("n3", "n7"): {"stretcher_ok": False}})
    assert "n6" in nodes_of(find_route(changed, "n1", "n10"))  # went by the stairs instead


def test_stairs_only_when_no_stretcher_path_raises(graph):
    changed = graph_with(
        graph,
        {("n3", "n7"): {"stretcher_ok": False}, ("n6", "n11"): {"stretcher_ok": False}},
    )
    with pytest.raises(NoRouteError):
        find_route(changed, "n1", "n10")


def test_elevator_is_preferred_even_when_stairs_are_faster(graph):
    faster_stairs = graph_with(graph, {("n6", "n11"): {"seconds": 5}})
    # Stairs now cost 5 s against 45 s for the elevator, but the penalty keeps the elevator.
    steps = find_route(faster_stairs, "n1", "n10")
    assert "n7" in nodes_of(steps) and "n6" not in nodes_of(steps)
    assert STAIRS_PENALTY_S > 45


def test_total_seconds_excludes_the_stairs_penalty(graph):
    steps = find_route(graph, "n1", "n10", closures={"n3->n7"})
    assert total_seconds(steps) < STAIRS_PENALTY_S


# ----------------------------------------------------------------- bad input


@pytest.mark.parametrize("start, goal", [("nope", "n10"), ("n1", "nope")])
def test_unknown_node_raises_lookup_error(graph, start, goal):
    with pytest.raises(LookupError):
        find_route(graph, start, goal)


# ------------------------------------------------------------------ A* is correct


def test_astar_matches_dijkstra_for_every_pair_of_nodes(graph):
    """A* with the 1.3 m/s heuristic must find the same cost as plain Dijkstra."""
    digraph = build_digraph(graph, closures=frozenset())
    for start, goal in itertools.permutations(digraph.nodes, 2):
        try:
            best = nx.dijkstra_path_length(digraph, start, goal, weight="cost")
        except nx.NetworkXNoPath:
            with pytest.raises(NoRouteError):
                find_route(graph, start, goal)
            continue
        steps = find_route(graph, start, goal)
        astar_cost = sum(digraph.edges[s.from_node, s.to_node]["cost"] for s in steps)
        assert astar_cost == pytest.approx(best), (start, goal)


# ------------------------------------------------------------------ turn cues


@pytest.mark.parametrize(
    "before, after, expected",
    [
        (0, 90, "RIGHT"),
        (90, 0, "LEFT"),
        (0, 44, "STRAIGHT"),
        (0, 45, "RIGHT"),
        (0, 315, "LEFT"),
        (0, 350, "STRAIGHT"),  # wraps around north
        (350, 10, "STRAIGHT"),
        (350, 80, "RIGHT"),
        (0, 180, "UTURN"),
        (90, 270, "UTURN"),
        (10, 160, "UTURN"),
    ],
)
def test_turn_cue(before, after, expected):
    assert turn_cue(before, after) == expected
