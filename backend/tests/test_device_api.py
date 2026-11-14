import pytest
from fastapi.testclient import TestClient

from app.api.device import DeviceRegistry, get_devices
from app.api.telemetry import EngineRegistry, get_registry
from app.db import get_db
from app.device.replay import telemetry_to_batches
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from app.position.simulate import simulate
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase
from tests.test_telemetry_api import DEMO, INCIDENT, route_row

client = TestClient(app)
DEVICE = "pi-01"


@pytest.fixture
def db():
    fake = FakeSupabase(
        incidents=[{"id": INCIDENT, "building_id": "233928", "status": "en_route"}],
        routes=[route_row()],
        cues=[],
        positions=[],
        devices=[],
        device_events=[],
    )
    registry = EngineRegistry(stride_m=0.7, recheck_s=0, provider=SnapshotProvider())
    devices = DeviceRegistry()
    app.dependency_overrides[get_db] = lambda: fake
    app.dependency_overrides[get_registry] = lambda: registry
    app.dependency_overrides[get_devices] = lambda: devices
    yield fake
    app.dependency_overrides.clear()


def link(device=DEVICE, incident=INCIDENT):
    return client.put(f"/api/device/{device}/link", json={"incident_id": incident})


def send(events, t=0, device=DEVICE):
    return client.post(f"/api/device/{device}/events", json={"t": t, "events": events})


def test_linking_an_unknown_incident_is_a_404(db):
    assert link(incident="nope").status_code == 404


def test_an_unlinked_device_is_a_404(db):
    assert send([]).status_code == 404


def test_linking_is_saved_and_can_be_repeated(db):
    assert link().json() == {"ok": True, "incident_id": INCIDENT}
    assert link().status_code == 200
    assert [(r["device_id"], r["incident_id"]) for r in db.rows("devices")] == [(DEVICE, INCIDENT)]


def test_a_link_survives_a_server_restart(db):
    link()
    fresh = DeviceRegistry()  # a new process knows nothing in memory
    app.dependency_overrides[get_devices] = lambda: fresh
    assert send([{"kind": "steps", "n": 1}]).status_code == 200


def test_before_a_route_exists_there_are_no_commands(db):
    db.rows("routes").clear()
    link()
    body = send([{"kind": "steps", "n": 2}]).json()
    assert body == {"commands": [], "incident_id": INCIDENT, "status": "no_route"}


def test_a_turn_cue_comes_back_once_as_a_command_and_is_saved_for_the_web_app(db):
    link()
    send([], t=0)
    first = send([{"kind": "steps", "n": 13}], t=200).json()  # 9.1 m of the 15 m: LEFT is near
    again = send([{"kind": "steps", "n": 1}], t=400).json()
    assert (first["commands"], again["commands"]) == (["CUE L"], [])
    assert first["status"] == "tracking"
    assert [c["cue"] for c in db.rows("cues")] == ["LEFT"]


def test_walking_the_whole_demo_route_as_events_arrives(db):
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    route = find_route(graph, "st_main", "phone_door")
    link()
    commands = []
    for batch in telemetry_to_batches(simulate(route)):
        events = [e.model_dump(exclude_none=True) for e in batch.events]
        commands += send(events, t=batch.t).json()["commands"]
    assert commands[-1] == "CUE A"
    assert "CUE UP" in commands and ("CUE L" in commands or "CUE R" in commands)
    assert db.rows("incidents")[0]["status"] == "arrived"


def test_elevator_out_replans_once(db):
    link()
    send([], t=0)
    for t in (200, 400, 600):  # the button is held for several samples
        send([{"kind": "button", "n": 2}], t=t)
    assert len(db.rows("closures")) == 1


def test_a_fall_is_logged_and_acknowledged(db):
    link()
    body = send([{"kind": "fall"}, {"kind": "air", "level": "warn", "ppm": 900}]).json()
    assert body["commands"] == []
    rows = db.rows("device_events")
    assert [(r["kind"], r["device_id"], r["incident_id"]) for r in rows] == [
        ("fall", DEVICE, INCIDENT),
        ("air", DEVICE, INCIDENT),
    ]
    assert rows[1]["data"] == {"level": "warn", "ppm": 900}


def test_a_bad_event_is_a_422(db):
    link()
    assert send([{"kind": "dance"}]).status_code == 422
