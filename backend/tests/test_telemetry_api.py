from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.telemetry import EngineRegistry, get_registry
from app.db import get_db
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"
DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
BASE_PRESSURE = 100000.0
client = TestClient(app)


def demo_route(closures=()):
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    return [s.model_dump() for s in find_route(graph, "st_main", "phone_door", closures)]


def route_row(version=1, steps=None):
    steps = steps or demo_route()
    return {"incident_id": INCIDENT, "version": version, "steps": steps, "entrance_node": "st_main"}


@pytest.fixture
def db():
    fake = FakeSupabase(
        incidents=[{"id": INCIDENT, "building_id": "233928", "status": "en_route"}],
        routes=[route_row()],
        cues=[],
        positions=[],
    )
    registry = EngineRegistry(stride_m=0.7, recheck_s=0, provider=SnapshotProvider())
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: registry
    yield fake
    app.dependency_overrides.clear()


def post(t, steps, heading=90.0, pressure=BASE_PRESSURE, btn=0, tag=None, incident=INCIDENT):
    body = {
        "t": t,
        "steps": steps,
        "heading": heading,
        "pressure": pressure,
        "btn": btn,
        "tag": tag,
    }
    return client.post(f"/incidents/{incident}/telemetry", json=body)


def test_a_sample_is_accepted(db):
    assert post(0, 1000).json() == {"ok": True}


def test_unknown_incident_is_a_404(db):
    assert post(0, 1000, incident="nope").status_code == 404


def test_samples_before_a_route_exists_are_accepted_and_ignored(db):
    db.rows("routes").clear()
    assert post(0, 1000).json() == {"ok": True}
    assert db.rows("positions") == [] and db.rows("cues") == []


def test_positions_are_saved_at_most_once_a_second(db):
    for i in range(10):
        post(i * 200, 1000 + i)  # 2 seconds of samples
    assert 2 <= len(db.rows("positions")) <= 3
    first = db.rows("positions")[0]
    assert first["incident_id"] == INCIDENT and first["route_version"] == 1
    assert (first["step_index"], first["floor"], first["off_route"]) == (0, 1, False)


def test_a_turn_cue_is_saved_once_when_the_turn_is_close(db):
    post(0, 1000)
    post(200, 1000 + 13)  # 9.1 m of the 15 m first step: the LEFT turn is now within 6 m
    post(400, 1000 + 14)
    cues = db.rows("cues")
    assert [(c["cue"], c["route_version"], c["incident_id"]) for c in cues] == [
        ("LEFT", 1, INCIDENT)
    ]
    assert cues[0]["text"].startswith("LEFT in ") and cues[0]["dist_m"] <= 6


def test_a_tag_scan_moves_the_crew_to_that_spot(db):
    post(0, 1000)
    post(200, 1000, tag="TAG-SUITE-1800")  # the suite door on floor 18
    last = db.rows("positions")[-1] if len(db.rows("positions")) > 1 else None
    post(1400, 1000)  # a later sample so a row is due after the snap
    row = db.rows("positions")[-1]
    assert (row["step_index"], row["floor"]) == (5, 18)
    assert last is None or last["floor"] in (1, 18)


def test_arriving_marks_the_incident_arrived_and_cues_it(db):
    one_step = [
        {"index": 0, "from_node": "a", "to_node": "b", "cue": "ARRIVE", "meters": 3.0,
         "seconds": 3, "floor": 1, "text": "Walk 3 m."}
    ]  # fmt: skip
    db.rows("routes")[:] = [route_row(steps=one_step)]
    post(0, 1000)
    post(200, 1000 + 5)  # 3.5 m walked
    assert db.rows("incidents")[0]["status"] == "arrived"
    assert [c["cue"] for c in db.rows("cues")] == ["ARRIVE"]


def test_a_new_route_version_restarts_the_tracking(db):
    post(0, 1000)
    post(200, 1000 + 13)  # LEFT cue for version 1
    db.rows("routes").append(route_row(version=2, steps=demo_route(closures={"el1->el18"})))
    post(400, 1000 + 14)
    post(1600, 1000 + 14)  # a row is due
    assert db.rows("positions")[-1]["route_version"] == 2
    assert db.rows("positions")[-1]["step_index"] == 0  # tracking restarted on the new route


def test_off_route_is_saved_as_a_cue_and_in_the_position(db):
    post(0, 1000)
    post(200, 1000 + 22)  # past the end of the 15 m first step
    post(400, 1000 + 40, heading=90)  # kept going straight: more than 5 m past the turn
    assert "OFF_ROUTE" in [c["cue"] for c in db.rows("cues")]
    post(2000, 1000 + 41)
    assert db.rows("positions")[-1]["off_route"] is True


def test_elevator_out_button_is_accepted(db):
    post(0, 1000)
    assert post(200, 1000, btn=2).json() == {"ok": True}


def test_a_database_problem_does_not_make_the_wearable_see_an_error(db):
    db.fail_tables.add("positions")
    assert post(0, 1000).json() == {"ok": True}


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"t": 0, "steps": 1, "heading": 400, "pressure": 100000, "btn": 0, "tag": None},
        {"t": 0, "steps": 1, "heading": 90, "pressure": 100000, "btn": 3, "tag": None},
        {"t": -5, "steps": 1, "heading": 90, "pressure": 100000, "btn": 0, "tag": None},
        {"t": 0, "steps": 1, "heading": 90, "pressure": 0, "btn": 0, "tag": None},
    ],
)
def test_bad_samples_are_rejected(db, body):
    assert client.post(f"/incidents/{INCIDENT}/telemetry", json=body).status_code == 422
