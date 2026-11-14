import itertools
import json
import math
from pathlib import Path

import pytest

from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.tour import Tour, build_tour

BUILDINGS = Path(__file__).resolve().parents[2] / "fixtures" / "buildings"


def load(building_id):
    graph = BuildingGraph.model_validate_json(
        (BUILDINGS / building_id / "graph.json").read_text(encoding="utf-8")
    )
    scans = json.loads((BUILDINGS / building_id / "sweeps.json").read_text(encoding="utf-8"))
    return graph, scans


def tour_for(building_id, start, goal, closures=(), **kwargs):
    graph, scans = load(building_id)
    if goal.startswith("label:"):
        text = goal.split(":", 1)[1].lower()
        goal = next(n.id for n in graph.nodes if n.label and text in n.label.lower())
    steps = find_route(graph, start, goal, closures)
    return Tour.model_validate(build_tour(steps, graph, scans, **kwargs)), steps, scans


@pytest.fixture(scope="module")
def jrr():
    return tour_for("jrr", "entrance1", "label:classroom")


@pytest.fixture(scope="module")
def louisiana():
    return tour_for("233928", "gar1", "phone_door")


@pytest.fixture(scope="module")
def williams():
    return tour_for("233903", "gar1", "room29")


def sweep_lookup(scans):
    return {s["id"]: s for m in scans["models"] for s in m["sweeps"]}


# ----------------------------------------------------------------- Rabinowitz Hall: the whole route is scanned


def test_rabinowitz_is_one_scanned_segment_from_the_door_to_the_patient(jrr):
    tour, steps, _ = jrr
    assert [s.kind for s in tour.segments] == ["scanned"]
    assert tour.segments[0].from_step == 0 and tour.segments[0].to_step == len(steps) - 1
    assert all(k.kind == "scanned" and k.sweep_id and k.model_id for k in tour.keyframes)


def test_every_move_is_one_the_viewer_can_make(jrr):
    """Consecutive stops on the same level must be sweeps that can see each other; the stairs move is a deliberate jump."""
    tour, _, scans = jrr
    sweeps = sweep_lookup(scans)
    jumps = 0
    for a, b in itertools.pairwise(tour.keyframes):
        if a.sweep_id == b.sweep_id:
            continue
        if sweeps[a.sweep_id]["level"] != sweeps[b.sweep_id]["level"]:
            jumps += 1
            assert (
                b.transition == "fade"
            )  # a cut between levels: flying through the ceiling would look wrong
        else:
            assert b.sweep_id in sweeps[a.sweep_id]["neighbors"], (a.sweep_id, b.sweep_id)
    assert jumps == 1  # one climb on the way to the classroom


def test_a_hop_never_takes_a_shortcut_across_the_other_level(jrr):
    tour, _, scans = jrr
    sweeps = sweep_lookup(scans)
    levels = [sweeps[k.sweep_id]["level"] for k in tour.keyframes]
    # the level changes exactly once: lower level first, then upper
    assert levels == sorted(levels) and len(set(levels)) == 2


def test_the_tour_starts_at_the_entrance_and_ends_at_the_patient(jrr):
    tour, steps, _ = jrr
    assert (
        tour.keyframes[0].node == steps[0].from_node
        and tour.keyframes[-1].node == steps[-1].to_node
    )
    assert (
        tour.keyframes[-1].caption.lower().startswith("walk")
        or "ahead" in tour.keyframes[-1].caption
    )


# ------------------------------------------------- Louisiana and Williams: only the suite on one floor is scanned


def test_louisiana_flies_only_over_the_scanned_suite(louisiana):
    tour, steps, _ = louisiana
    kinds = [s.kind for s in tour.segments]
    assert kinds == ["gap", "scanned"]
    gap, scanned = tour.segments
    assert gap.from_step == 0 and "not scanned" in gap.reason
    assert scanned.to_step == len(steps) - 1 and scanned.model_id == "LJn59uoV759"
    assert [k.node for k in tour.keyframes if k.kind == "gap"] == ["gar1", "el1", "el18", "hall18"]
    assert all(not k.sweep_id for k in tour.keyframes if k.kind == "gap")
    assert [k.node for k in tour.keyframes if k.kind == "scanned" and k.waypoint] == [
        "door18",
        "rec_a",
        "rec_b",
        "phone_door",
    ]
    first = next(k for k in tour.keyframes if k.kind == "scanned")
    assert (
        first.transition == "fade"
    )  # a cut from the map into the scan: there is no continuous flight


def test_williams_flies_only_over_the_scanned_suite(williams):
    tour, _steps, _ = williams
    assert [s.kind for s in tour.segments] == ["gap", "scanned"]
    nodes = {k.node: k for k in tour.keyframes}
    assert (
        nodes["el56"].kind == "gap" and nodes["hall56"].kind == "gap"
    )  # the elevator corridor is not in the scan
    assert nodes["door56"].kind == "scanned" and nodes["room29"].kind == "scanned"
    assert tour.segments[1].model_id == "eJKnR3x44eh"


def test_gap_stops_use_the_plan_frame_and_say_so(louisiana):
    tour, _, _ = louisiana
    gap = next(k for k in tour.keyframes if k.kind == "gap")
    assert gap.frame == "plan" and gap.sweep_id is None and gap.model_id is None
    scanned = next(k for k in tour.keyframes if k.kind == "scanned")
    assert scanned.frame == "scan"


# ------------------------------------------------------------------------------------- timing and direction


@pytest.mark.parametrize("fixture", ["jrr", "louisiana", "williams"])
def test_times_only_move_forward_and_directions_are_compass_degrees(fixture, request):
    tour, _, _ = request.getfixturevalue(fixture)
    times = [k.t_ms for k in tour.keyframes]
    assert times[0] == 0 and all(b > a for a, b in itertools.pairwise(times))
    assert tour.duration_ms >= times[-1]
    assert all(0 <= k.bearing_deg < 360 for k in tour.keyframes)


def test_each_stop_faces_the_next_one(jrr):
    tour, _, _scans = jrr
    for a, b in itertools.pairwise(tour.keyframes):
        if a.sweep_id != b.sweep_id and a.level == b.level:
            expected = (
                math.degrees(math.atan2(b.position.x - a.position.x, b.position.y - a.position.y))
                % 360
            )
            diff = abs((a.bearing_deg - expected + 180) % 360 - 180)
            assert diff < 1.0


def test_a_faster_playback_makes_a_shorter_tour():
    slow, _, _ = tour_for("jrr", "entrance1", "label:classroom", speed_up=3.0)
    fast, _, _ = tour_for("jrr", "entrance1", "label:classroom", speed_up=12.0)
    assert fast.duration_ms < slow.duration_ms


def test_walking_through_a_scan_is_never_faster_than_a_brisk_walk(jrr):
    tour, _, _ = jrr
    for a, b in itertools.pairwise(tour.keyframes):
        if a.level != b.level or a.model_id != b.model_id:
            continue
        hop_m = math.hypot(b.position.x - a.position.x, b.position.y - a.position.y)
        seconds = (b.t_ms - a.t_ms - a.dwell_ms) / 1000
        assert hop_m / seconds <= 3.0, (a.i, hop_m, seconds)


def test_the_walk_goes_through_many_short_hops_so_it_flows(jrr):
    tour, _, _ = jrr
    hops = [
        math.hypot(b.position.x - a.position.x, b.position.y - a.position.y)
        for a, b in itertools.pairwise(tour.keyframes)
        if a.level == b.level
    ]
    assert len(tour.keyframes) >= 13
    assert max(hops) <= 6.0


def test_the_scans_opening_view_is_included_so_the_compass_can_be_calibrated(jrr):
    tour, _, _ = jrr
    pose = tour.models["P3S6VUTP3qB"]
    assert pose.bearing_deg == pytest.approx(55.5) and pose.position.z == pytest.approx(
        1.352, abs=0.01
    )


# ------------------------------------------------------------------------------------------------ edge cases


def test_a_building_without_scan_data_gets_no_tour():
    graph, _ = load("jrr")
    steps = find_route(
        graph, "entrance1", next(n.id for n in graph.nodes if n.label and "Classroom" in n.label)
    )
    assert build_tour(steps, graph, None) is None
    assert build_tour([], graph, {"models": []}) is None


def test_a_rerouted_route_gets_its_own_tour():
    normal, _, _ = tour_for("233928", "gar1", "phone_door")
    stairs, _steps, _ = tour_for("233928", "gar1", "phone_door", closures={"el1->el18"})
    assert stairs.duration_ms > normal.duration_ms
    assert any(k.cue == "FLOOR_UP" for k in stairs.keyframes)


def test_the_json_the_frontend_gets_matches_the_published_schema(jrr):
    tour, _, _ = jrr
    schema = Tour.model_json_schema()
    assert {"version", "keyframes", "segments", "duration_ms", "models"} <= set(
        schema["properties"]
    )
    dumped = tour.model_dump(mode="json")
    assert dumped["version"] == 1 and isinstance(dumped["keyframes"][0]["position"]["x"], float)
