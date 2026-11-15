import pytest
from fastapi.testclient import TestClient

from app.api.device import DeviceRegistry, get_devices
from app.api.telemetry import EngineRegistry, get_registry
from app.config import get_settings
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
DEVICE = "wearable-1"


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


def send(events, device=DEVICE):
    return client.post(f"/api/device/{device}/events", json={"events": events})


def state(steps, ts, fl=0):
    return {"t": "state", "ts": ts, "steps": steps, "d": steps * 0.7, "hd": 0, "fl": fl}


def test_linking_an_unknown_incident_is_a_404(db):
    assert link(incident="nope").status_code == 404
    db.strict_uuid = True  # the real database rejects a non-UUID with an error
    assert link(incident="nope").status_code == 404


def test_an_unbound_device_still_gets_a_200_and_an_empty_command_list(db):
    r = send([state(1, 100)])
    assert (r.status_code, r.json()["commands"]) == (200, [])


def test_bad_bodies_are_never_an_error(db):
    link()
    send([])
    for body in ({"events": "x"}, {"nope": 1}, [1, 2], {"events": [5, {"t": 3}, {"ts": 1}]}):
        assert client.post(f"/api/device/{DEVICE}/events", json=body).status_code == 200
    r = client.post(f"/api/device/{DEVICE}/events", content=b"not json")
    assert (r.status_code, "commands" in r.json()) == (200, True)


def test_a_failure_inside_is_logged_and_still_a_200(db):
    link()
    db.fail_tables.add("positions")
    db.fail_tables.add("device_events")
    assert send([{"t": "hello", "ts": 1}, state(0, 2)]).status_code == 200


def test_linking_queues_a_reset_that_is_delivered_once(db):
    link()
    link()  # a second link does not queue a second RESET
    assert send([]).json()["commands"] == ["RESET"]
    assert send([]).json()["commands"] == []
    assert [(r["device_id"], r["incident_id"]) for r in db.rows("devices")] == [(DEVICE, INCIDENT)]


def test_binding_from_the_incident_side(db):
    body = client.post(f"/incidents/{INCIDENT}/device", json={"device_id": DEVICE}).json()
    assert body == {"ok": True, "incident_id": INCIDENT, "device_id": DEVICE}
    assert send([]).json()["incident_id"] == INCIDENT
    assert client.post("/incidents/nope/device", json={"device_id": DEVICE}).status_code == 404


def test_a_link_survives_a_server_restart(db):
    link()
    fresh = DeviceRegistry()  # a new process knows nothing in memory
    app.dependency_overrides[get_devices] = lambda: fresh
    assert send([state(1, 1)]).json()["incident_id"] == INCIDENT


def test_before_a_route_exists_there_are_no_commands(db):
    db.rows("routes").clear()
    link()
    send([])  # takes the RESET
    body = send([state(2, 100)]).json()
    assert body == {"commands": [], "incident_id": INCIDENT, "status": "no_route"}


def test_the_same_batch_sent_twice_is_handled_once(db):
    link()
    send([])
    batch = [{"t": "fall", "ts": 77}, {"t": "btn", "ts": 78, "id": 1, "ev": "confirm"}]
    send(batch)
    send(batch)
    assert [r["kind"] for r in db.rows("device_events")] == ["fall", "btn"]


def test_a_resend_after_a_restart_is_still_recognised(db):
    link()
    send([{"t": "fall", "ts": 77}])
    app.dependency_overrides[get_devices] = lambda: DeviceRegistry()
    send([{"t": "fall", "ts": 77}])
    assert [r["kind"] for r in db.rows("device_events")] == ["fall"]


def test_a_turn_cue_comes_back_once_as_commands_and_is_saved_for_the_web_app(db):
    link()
    send([state(0, 100)])
    # 9.1 m of the 15 m: LEFT is near
    first = send([{"t": "step", "ts": 200, "n": 13}, state(13, 200)]).json()
    again = send([{"t": "step", "ts": 400, "n": 14}]).json()
    assert (
        first["commands"] == [] or first["commands"][0] != "RESET"
    )  # RESET went with the first call
    assert [c for c in first["commands"] if c.startswith("CUE")] == ["CUE L"]
    assert first["commands"][-1].startswith("TXT ") and len(first["commands"][-1]) <= 20
    assert again["commands"] == [] and first["status"] == "tracking"
    assert [c["cue"] for c in db.rows("cues")] == ["LEFT"]


def test_walking_the_whole_demo_route_as_the_real_pi_would_arrives(db):
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    route = find_route(graph, "st_main", "phone_door")
    link()
    commands = []
    for events in telemetry_to_batches(simulate(route)):
        commands += send(events).json()["commands"]
    assert commands[0] == "RESET"
    assert "ARRIVED" in commands and {"CUE L", "CUE R"} & set(commands)
    assert db.rows("incidents")[0]["status"] == "arrived"


def test_elevator_out_replans_once(db):
    link()
    send([state(0, 100)])
    for ts in (200, 400, 600):  # the button is held for several samples
        send([{"t": "btn", "ts": ts, "id": 2, "ev": "elevator_out"}])
    assert len(db.rows("closures")) == 1


def test_a_fall_and_an_air_warning_are_logged_with_their_incident(db):
    link()
    send([{"t": "fall", "ts": 5}, {"t": "air", "ts": 6, "v": 900, "warn": 1}, state(0, 7)])
    rows = db.rows("device_events")
    assert [(r["kind"], r["device_id"], r["incident_id"]) for r in rows] == [
        ("fall", DEVICE, INCIDENT),
        ("air", DEVICE, INCIDENT),
    ]
    assert rows[1]["data"] == {"ts": 6, "v": 900, "warn": 1}


def test_hello_is_remembered_on_the_device_row(db):
    link()
    send([{"t": "hello", "ts": 1, "fw": "pi-3", "imu": 1, "baro": 1, "cam": 1}])
    row = db.rows("devices")[0]
    assert row["fw"] == "pi-3" and row["sensors"] == {"imu": 1, "baro": 1, "cam": 1}
    assert row["last_seen_at"]


def test_the_default_device_follows_the_newest_active_incident(db, monkeypatch):
    monkeypatch.setenv("DEFAULT_DEVICE_ID", DEVICE)
    get_settings.cache_clear()
    db.rows("incidents").append(
        {"id": "old", "status": "arrived", "created_at": "2026-11-15T09:00"}
    )
    try:
        assert send([]).json()["commands"] == ["RESET"]  # not bound yet: took the active incident
        assert send([]).json()["incident_id"] == INCIDENT
    finally:
        get_settings.cache_clear()


def test_a_fall_opens_an_alert_and_button_one_clears_it(db):
    link()
    send([{"t": "fall", "ts": 10}])
    send([{"t": "fall", "ts": 11}])  # a second fall while one is open adds no second alert
    (alert,) = db.rows("alerts")
    assert (alert["kind"], alert["active"], alert["incident_id"], alert["device_id"]) == (
        "fall",
        True,
        INCIDENT,
        DEVICE,
    )
    send([{"t": "fall_cancel", "ts": 20}])
    assert [(a["active"], bool(a["cleared_at"])) for a in db.rows("alerts")] == [(False, True)]


def test_an_air_warning_opens_and_clears_an_alert_with_the_reading(db):
    link()
    send([{"t": "air", "ts": 10, "v": 2800, "warn": 1}])
    assert [(a["kind"], a["active"], a["detail"]) for a in db.rows("alerts")] == [
        ("air", True, {"v": 2800})
    ]
    send([{"t": "air", "ts": 20, "v": 900, "warn": 0}])
    assert db.rows("alerts")[0]["active"] is False


def test_an_alert_that_cannot_be_saved_does_not_stop_the_batch(db):
    link()
    db.fail_tables.add("alerts")
    assert send([{"t": "fall", "ts": 1}]).status_code == 200
    assert [r["kind"] for r in db.rows("device_events")] == ["fall"]
