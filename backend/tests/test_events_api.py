import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.events import get_embedder
from app.api.telemetry import EngineRegistry, get_registry
from app.db import get_db
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"
DEMO = Path(__file__).resolve().parents[2] / "fixtures" / "buildings" / "233928" / "graph.json"
client = TestClient(app)


def demo_route():
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    return [s.model_dump() for s in find_route(graph, "st_main", "phone_door")]


async def fake_embedder(text):
    return [float(len(text)), 1.0]


@pytest.fixture
def db():
    fake = FakeSupabase(
        incidents=[{"id": INCIDENT, "building_id": "233928", "status": "en_route"}],
        routes=[
            {
                "incident_id": INCIDENT,
                "version": 1,
                "steps": demo_route(),
                "entrance_node": "st_main",
                "briefing": "x",
            }
        ],
        closures=[],
        plan_steps=[
            {"incident_id": INCIDENT, "seq": 3, "kind": "final", "title": "Final", "detail": {}}
        ],
        notes=[],
    )
    registry = EngineRegistry(stride_m=0.7, recheck_s=0, provider=SnapshotProvider())
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_embedder] = lambda: fake_embedder
    yield fake
    app.dependency_overrides.clear()


def event(type_, text=None, incident=INCIDENT):
    return client.post(f"/incidents/{incident}/events", json={"type": type_, "text": text})


def test_unknown_incident_is_a_404(db):
    assert event("note", "x", incident="nope").status_code == 404


def test_an_id_that_is_not_a_uuid_is_a_404_not_a_server_error(db):
    db.strict_uuid = True
    assert event("note", "x", incident="nope").status_code == 404


def test_unknown_event_type_is_rejected(db):
    assert event("bogus").status_code == 422


def test_elevator_out_closes_the_lift_and_saves_a_stairs_route(db):
    assert event("elevator_out").json() == {"ok": True}
    assert [c["node_or_edge"] for c in db.rows("closures")] == ["el1->el18"]
    versions = {r["version"]: r for r in db.rows("routes")}
    assert sorted(versions) == [1, 2]
    new_steps = {(s["from_node"], s["to_node"]) for s in versions[2]["steps"]}
    assert ("stair1", "stair18") in new_steps and ("el1", "el18") not in new_steps
    assert versions[2]["steps"][0]["from_node"] == "st_main"  # nobody has moved yet


def test_elevator_out_writes_a_replan_step_after_the_existing_trace(db):
    event("elevator_out")
    step = db.rows("plan_steps")[-1]
    assert (step["kind"], step["seq"], step["incident_id"]) == ("replan", 4, INCIDENT)
    assert "elevator" in step["title"].lower()


def test_obstacle_closes_the_current_walk_and_reports_no_route_clearly(db):
    # every way up goes through el1->el18 or stairs; closing the first walk of the route blocks it all
    response = event("obstacle", "locked door")
    assert response.status_code == 200
    assert db.rows("closures")[0]["reason"].endswith("(locked door)")
    last = db.rows("plan_steps")[-1]
    assert last["kind"] == "replan"


def test_no_route_left_is_reported_in_the_trace_not_as_a_crash(db):
    db.rows("closures").append({"incident_id": INCIDENT, "node_or_edge": "stair1->stair18"})
    response = event("elevator_out")
    assert response.status_code == 200
    assert len(db.rows("routes")) == 1  # nothing new saved
    assert "no route" in db.rows("plan_steps")[-1]["title"].lower()


def test_elevator_out_when_the_route_has_no_lift_changes_nothing(db):
    event("elevator_out")  # route 2 uses the stairs
    assert event("elevator_out").status_code == 200
    assert len(db.rows("routes")) == 2
    assert "left as it is" in db.rows("plan_steps")[-1]["title"]


def test_elevator_out_without_a_route_is_a_409(db):
    db.rows("routes").clear()
    assert event("elevator_out").status_code == 409


def test_arrived_marks_the_incident(db):
    event("arrived")
    assert db.rows("incidents")[0]["status"] == "arrived"


def test_a_note_is_stored_with_an_embedding_for_the_building(db):
    assert event("note", "Freight lift is faster after 6 pm").json() == {"ok": True}
    row = db.rows("notes")[0]
    assert row["building_id"] == "233928"
    assert row["text"] == "Freight lift is faster after 6 pm"
    assert row["embedding"] == [float(len("Freight lift is faster after 6 pm")), 1.0]


def test_a_blank_note_is_rejected(db):
    assert event("note", "  ").status_code == 422


def test_a_note_is_still_saved_when_embedding_fails(db):
    async def broken(text):
        raise RuntimeError("no key")

    app.dependency_overrides[get_embedder] = lambda: broken
    assert event("note", "Lobby desk has the key").status_code == 200
    assert db.rows("notes")[0]["embedding"] is None


def test_the_wearable_elevator_out_button_replans_too(db):
    body = {"t": 0, "steps": 100, "heading": 90.0, "pressure": 100000.0, "btn": 2, "tag": None}
    assert client.post(f"/incidents/{INCIDENT}/telemetry", json=body).json() == {"ok": True}
    assert [c["node_or_edge"] for c in db.rows("closures")] == ["el1->el18"]
    assert max(r["version"] for r in db.rows("routes")) == 2


def test_skip_floor_moves_the_position_past_the_lift_and_saves_it(db):
    db.tables.setdefault("positions", [])
    db.tables.setdefault("cues", [])
    engine = asyncio.run(app.dependency_overrides[get_registry]().get(INCIDENT, db)).engine
    lift = next(i for i in range(1, len(engine.steps)) if engine._is_floor_change(i))
    engine.step_index = lift  # the crew is standing at the lift
    assert event("skip_floor").json() == {"ok": True}
    assert engine.step_index == lift + 1
    assert db.rows("positions")[-1]["floor"] == engine.steps[lift].floor


def test_skip_floor_without_a_route_is_a_409(db):
    db.rows("routes").clear()
    assert event("skip_floor").status_code == 409


def test_rejoin_clears_off_route_and_saves_the_position(db):
    db.tables.setdefault("positions", [])
    engine = asyncio.run(app.dependency_overrides[get_registry]().get(INCIDENT, db)).engine
    engine.off_route = True
    assert event("rejoin").json() == {"ok": True}
    assert engine.off_route is False and db.rows("positions")[-1]["off_route"] is False
