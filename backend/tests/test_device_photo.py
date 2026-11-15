import time

import pytest
from fastapi.testclient import TestClient

from app.api.device import get_sign_reader
from app.device.replay import telemetry_to_batches
from app.device.signs import SignReader, match_sign
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.main import app
from app.position.simulate import simulate
from tests.test_device_api import DEVICE, INCIDENT, db, link, send, state  # noqa: F401
from tests.test_telemetry_api import DEMO

CAMERA_OFF = pytest.mark.skip(
    reason="camera features are disabled in the backend for the demo (see device.py)"
)

NODES = [
    {"id": "door", "label": "Regus Suite 1800 entrance"},
    {"id": "phone", "label": "Regus Suite 1800 phone room (patient)"},
    {"id": "lift", "label": "Elevators (floor 18)"},
]


def test_a_sign_matches_the_node_with_the_shortest_label():
    assert match_sign(["SUITE 1800"], NODES) == "door"
    assert match_sign(["1800"], NODES) == "door"


def test_signs_that_name_nothing_on_the_route_match_nothing():
    assert match_sign(["SUITE 1900"], NODES) is None
    assert match_sign([], NODES) is None
    assert match_sign(["EXIT"], NODES) is None
    assert (
        match_sign(
            ["Floor 18"],
            [{"id": "a", "label": "Floor 18 east"}, {"id": "b", "label": "Floor 18 west"}],
        )
        is None
    )  # a tie


def test_a_reader_with_no_picture_or_no_answer_returns_nothing():
    class Broken:
        async def ainvoke(self, _):
            raise RuntimeError("503")

    import asyncio

    assert asyncio.run(SignReader(chains=[Broken()])(b"")) == []
    assert asyncio.run(SignReader(chains=[Broken()])(b"jpeg")) == []


def photo(client, jpeg=b"\xff\xd8fake", device=DEVICE):
    return client.post(
        f"/api/device/{device}/photo",
        files={"image": ("snap.jpg", jpeg, "image/jpeg")},
        data={"ts": "1700000000000", "n": "1", "reason": "scan"},
    )


def wait_for(condition, seconds=5):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if condition():
            return True
        time.sleep(0.05)
    return False


@CAMERA_OFF
def test_a_photo_of_a_suite_sign_snaps_the_position_and_is_never_stored(db):  # noqa: F811
    seen = []

    async def reader(image):
        seen.append(image)
        return ["SUITE 1800"]

    app.dependency_overrides[get_sign_reader] = lambda: reader
    link()
    send([state(0, 100)])
    with TestClient(app) as client:
        reply = photo(client)
        assert (reply.status_code, reply.json()) == (200, {"commands": []})
        assert wait_for(lambda: any(r["kind"] == "sign" for r in db.rows("device_events")))
    assert seen == [b"\xff\xd8fake"]
    sign = next(r for r in db.rows("device_events") if r["kind"] == "sign")
    assert sign["data"]["text"] == ["SUITE 1800"] and sign["data"]["node"] == "door18"
    assert b"fake" not in repr(db.tables).encode()  # the picture itself is not in the database
    assert any(p.get("progress_m") == 0.0 for p in db.rows("positions"))


def test_a_photo_without_a_readable_sign_changes_nothing(db):  # noqa: F811
    async def reader(_):
        return []

    app.dependency_overrides[get_sign_reader] = lambda: reader
    link()
    send([state(0, 100)])
    with TestClient(app) as client:
        assert photo(client).status_code == 200
        time.sleep(0.3)
    assert not [r for r in db.rows("device_events") if r["kind"] == "sign"]


def test_bad_photo_bodies_still_get_an_answer(db):  # noqa: F811
    link()
    client = TestClient(app)
    assert client.post(f"/api/device/{DEVICE}/photo", content=b"junk").status_code == 200
    assert client.post("/api/device/nobody/photo", files={"image": ("a.jpg", b"x")}).json() == {
        "commands": []
    }


@CAMERA_OFF
def test_the_camera_starts_scanning_near_the_destination_once_and_stops_on_arrival(db):  # noqa: F811
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    route = find_route(graph, "st_main", "phone_door")
    link()
    commands = []
    for events in telemetry_to_batches(simulate(route)):
        commands += send(events).json()["commands"]
    assert commands.count("SCAN ON") == 1
    assert commands.index("SCAN ON") < commands.index("ARRIVED") < commands.index("SCAN OFF")


def test_with_the_camera_disabled_a_photo_is_ignored_and_scan_on_is_never_sent(db):  # noqa: F811
    called = []

    async def reader(image):
        called.append(image)
        return ["SUITE 1800"]

    app.dependency_overrides[get_sign_reader] = lambda: reader
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    route = find_route(graph, "st_main", "phone_door")
    link()
    commands = []
    with TestClient(app) as client:
        for i, events in enumerate(telemetry_to_batches(simulate(route))):
            commands += send(events).json()["commands"]
            if i == 5:
                assert photo(client).status_code == 200
        time.sleep(0.3)
    assert called == []
    assert not [r for r in db.rows("device_events") if r["kind"] == "sign"]
    assert "SCAN ON" not in commands and "ARRIVED" in commands
