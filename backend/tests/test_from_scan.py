import json
import math
from pathlib import Path

import networkx as nx
import pytest

from app.graph.from_scan import Hints, build_graph_from_scan
from app.graph.router import NoRouteError, build_digraph, find_route
from app.graph.schema import BuildingGraph

BUILDINGS = Path(__file__).resolve().parents[2] / "fixtures" / "buildings"
LEVELS = {"jrr": {"Floor 2": 2, "Floor 3": 3}, "233903": {"Floor 1": 56}, "233928": {"Floor 1": 18}}


def scan_of(building_id):
    interior = json.loads((BUILDINGS / building_id / "interior.json").read_text(encoding="utf-8"))[
        "models"
    ][0]
    sweeps = json.loads((BUILDINGS / building_id / "sweeps.json").read_text(encoding="utf-8"))[
        "models"
    ][0]
    return interior, sweeps


def build(building_id, hints=None):
    interior, sweeps = scan_of(building_id)
    return build_graph_from_scan(building_id, interior, sweeps, LEVELS[building_id], hints)


def seconds(graph, start, goal, closures=()):
    return sum(s.seconds for s in find_route(graph, start, goal, closures))


@pytest.fixture(scope="module")
def jrr():
    # the opening-view hints Person 2 read off the Rabinowitz thumbnail: the glass doors at pixel 1330 of 2000
    return build("jrr", Hints(entrance_px=1330, stairs_px=300))


@pytest.fixture(scope="module")
def williams():
    return build("233903")


@pytest.fixture(scope="module")
def louisiana():
    return build("233928")


def label_of(graph, text):
    return next(n.id for n in graph.nodes if n.label and text.lower() in n.label.lower())


# ------------------------------------------------------------------ it must reproduce the hand-built maps


def test_the_graph_is_valid_and_one_connected_piece(jrr, williams, louisiana):
    for result in (jrr, williams, louisiana):
        BuildingGraph.model_validate(result.graph.model_dump(by_alias=True))
        assert nx.number_weakly_connected_components(build_digraph(result.graph, [])) == 1
        for e in result.graph.edges:
            assert e.seconds >= e.meters / 1.3 - 1e-9


def test_a_stairs_hint_puts_the_stairs_where_the_glass_staircase_is(jrr):
    stairs = [n for n in jrr.graph.nodes if n.kind == "stairs"]
    assert {n.floor for n in stairs} == {2, 3}
    lower = next(n for n in stairs if n.floor == 2)
    assert math.hypot(lower.x - 1.61, lower.y - 5.27) < 2.5
    assert any("stairs hint" in item for item in jrr.report["inferred"])


def test_stacked_scan_positions_are_not_taken_for_stairs():
    """Rabinowitz has 8 sweeps stacked on both levels along the balcony edge: stacking proves nothing about stairs."""
    interior, sweeps = scan_of("jrr")
    result = build_graph_from_scan("jrr", interior, sweeps, LEVELS["jrr"], Hints(entrance_px=1330))
    stairs = [n for n in result.graph.nodes if n.kind == "stairs"]
    assert (
        len(stairs) == 2
    )  # exactly one staircase, taken from the one sweep taken between the levels
    assert any("between the levels" in item for item in result.report["inferred"])
    lower = next(n for n in stairs if n.floor == 2)
    assert (
        math.hypot(lower.x - 1.4, lower.y - (-9.1)) < 4.0
    )  # the south staircase that sweep was taken on


def test_with_no_evidence_of_stairs_the_builder_says_the_levels_are_not_connected():
    interior, sweeps = scan_of("jrr")
    sweeps = json.loads(json.dumps(sweeps))
    sweeps["sweeps"] = [
        s for s in sweeps["sweeps"] if abs(s["z"] - 2.0) > 0.5
    ]  # drop the one sweep taken mid-flight
    result = build_graph_from_scan("jrr", interior, sweeps, LEVELS["jrr"], Hints(entrance_px=1330))
    assert not [n for n in result.graph.nodes if n.kind == "stairs"]
    assert any("not connected" in w for w in result.report["warnings"])
    assert nx.number_weakly_connected_components(build_digraph(result.graph, [])) == 2


def test_rabinowitz_classroom_route_matches_the_hand_built_one(jrr):
    entrance = next(n.id for n in jrr.graph.nodes if n.kind == "entrance")
    assert (
        41 <= seconds(jrr.graph, entrance, label_of(jrr.graph, "classroom")) <= 61
    )  # hand-built: 51 s


def test_the_entrance_hint_lands_on_the_east_wall(jrr):
    entrance = next(n for n in jrr.graph.nodes if n.kind == "entrance")
    assert 14.0 < entrance.x < 15.7 and 2.0 < entrance.y < 7.0
    assert any("hint" in item for item in jrr.report["inferred"])


def test_williams_entrance_is_the_suites_glass_door_found_in_the_scan(williams):
    entrance = next(n for n in williams.graph.nodes if n.kind == "entrance")
    assert (
        math.hypot(entrance.x - (-0.16), entrance.y - 0.7) < 0.5
    )  # the 2 m glass doorway at the scan origin
    assert any("exterior doorway" in item for item in williams.report["inferred"])


def test_williams_conference_room_is_reachable_and_about_as_far_as_the_hand_built_map(williams):
    entrance = next(n.id for n in williams.graph.nodes if n.kind == "entrance")
    hand = BuildingGraph.model_validate_json(
        (BUILDINGS / "233903" / "graph.json").read_text(encoding="utf-8")
    )
    expected = seconds(hand, "door56", "room29")
    got = seconds(williams.graph, entrance, label_of(williams.graph, "conference"))
    assert abs(got - expected) <= 12, (got, expected)


# ---------------------------------------------------- any room, not just the ones someone labelled by hand


def test_every_room_of_the_scan_that_a_person_could_be_in_is_a_destination(
    williams, jrr, louisiana
):
    for result in (williams, jrr, louisiana):
        stats = result.report["stats"]
        assert (
            stats["rooms_with_a_destination"] >= stats["rooms_considered"] - stats["rooms_skipped"]
        )
        assert stats["rooms_with_a_destination"] >= 3


def test_williams_has_a_destination_for_each_of_its_offices(williams):
    offices = [n for n in williams.graph.nodes if n.label and n.label.startswith("Office ")]
    assert len(offices) >= 15  # the scan has 20 offices; the hand-built map offered four rooms


def test_every_destination_can_be_reached_from_the_entrance(williams, jrr, louisiana):
    for result in (williams, jrr, louisiana):
        entrance = next(n.id for n in result.graph.nodes if n.kind == "entrance")
        patients = [n for n in result.graph.nodes if n.label and n.label.endswith("(patient)")]
        assert patients
        for n in patients:
            steps = find_route(result.graph, entrance, n.id)
            assert steps[-1].cue == "ARRIVE" and steps[-1].floor == n.floor, n.label


def test_labels_are_unique_so_the_agent_can_tell_rooms_apart(williams):
    labels = [n.label for n in williams.graph.nodes if n.label and n.label.endswith("(patient)")]
    assert len(labels) == len(set(labels))


# ---------------------------------------------------------------------------- honesty about what is inferred


def test_without_any_hint_or_exterior_door_the_scan_start_is_used_and_flagged():
    interior, sweeps = scan_of("jrr")
    result = build_graph_from_scan("jrr", interior, sweeps, LEVELS["jrr"], None)
    entrance = next(n for n in result.graph.nodes if n.kind == "entrance")
    assert any("scan start" in item for item in result.report["inferred"])
    assert math.hypot(entrance.x, entrance.y) < 2.0  # the start pose is the origin


def test_a_single_level_building_has_no_stairs_and_says_so(williams):
    assert not [n for n in williams.graph.nodes if n.kind in ("stairs", "elevator")]
    assert not any(
        "stairs" in w for w in williams.report["warnings"]
    )  # nothing to connect, so nothing to warn about


def test_nothing_is_invented(jrr, williams):
    for result in (jrr, williams):
        assert not [n for n in result.graph.nodes if n.kind in ("aed", "elevator")]


def test_closing_the_only_stairs_cuts_off_the_upper_level(jrr):
    entrance = next(n.id for n in jrr.graph.nodes if n.kind == "entrance")
    stairs = next(e for e in jrr.graph.edges if e.kind == "stairs")
    upper = next(
        n.id for n in jrr.graph.nodes if n.floor == 3 and n.label and n.label.endswith("(patient)")
    )
    with pytest.raises(NoRouteError):
        find_route(jrr.graph, entrance, upper, closures={f"{stairs.from_node}->{stairs.to_node}"})


# --------------------------------------------- a building nobody drew by hand: an apartment unit from the CoStar kit

LEVELS["thea-2br"] = {"Floor 1": 1}


@pytest.fixture(scope="module")
def apartment():
    return build("thea-2br")


def test_an_apartment_unit_is_built_with_no_hints_and_every_room_reachable(apartment):
    entrance = next(n.id for n in apartment.graph.nodes if n.kind == "entrance")
    patients = [n for n in apartment.graph.nodes if n.label and n.label.endswith("(patient)")]
    assert len(patients) >= 12
    for n in patients:
        assert find_route(apartment.graph, entrance, n.id)[-1].cue == "ARRIVE", n.label
    assert any(
        "exterior doorway" in item for item in apartment.report["inferred"]
    )  # the front door, found in the scan


def test_rooms_are_named_by_what_the_scan_says_they_are(apartment):
    labels = {n.label for n in apartment.graph.nodes if n.label and n.label.endswith("(patient)")}
    assert {
        "Bedroom 1 (patient)",
        "Bedroom 2 (patient)",
        "Bathroom 1 (patient)",
        "Bathroom 3 (patient)",
    } <= labels
    assert "Kitchen (patient)" in labels  # one kitchen: no number
    assert "Laundry (patient)" in labels and "Pantry (patient)" in labels
    assert not [
        label for label in labels if label.startswith("Room ")
    ]  # nothing left as an anonymous "Room N"
