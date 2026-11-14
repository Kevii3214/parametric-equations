import asyncio
import socket

import pytest

from app.providers.base import BuildingProvider
from app.providers.snapshot import SnapshotProvider

DEMO_ID = "233928"  # 1415 Louisiana, Houston


@pytest.fixture
def provider():
    return SnapshotProvider()


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """The demo must survive bad Wi-Fi: any attempt to reach another machine fails the test.

    Loopback is allowed because asyncio itself uses it on Windows to start its event loop.
    """
    real_connect = socket.socket.connect

    def guard(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise AssertionError(f"SnapshotProvider tried to reach {host}")
        return real_connect(self, address, *args, **kwargs)

    monkeypatch.setattr(socket.socket, "connect", guard)


def run(coro):
    return asyncio.run(coro)


def test_is_a_building_provider(provider):
    assert isinstance(provider, BuildingProvider)


@pytest.mark.parametrize(
    "address",
    ["1415 Louisiana St, Houston, TX", "1415 louisiana street houston", "1415 Louisiana"],
)
def test_resolve_finds_demo_building(provider, address):
    assert run(provider.resolve(address)) == DEMO_ID


def test_resolve_unknown_address_raises(provider):
    with pytest.raises(LookupError):
        run(provider.resolve("1 Nowhere Lane, Atlantis"))


def test_record_has_building_facts(provider):
    record = run(provider.record(DEMO_ID))
    assert record["name"] == "1415 Louisiana"
    assert record["stories_above_grade"] == 43
    assert any(e["type"] == "Passenger" and e["count"] == 15 for e in record["elevators"])
    assert record["current_tenants"]


def test_record_has_no_contact_details(provider):
    text = str(run(provider.record(DEMO_ID))).lower()
    assert "@" not in text and "phone" not in text


def test_aerial_returns_jpeg_bytes(provider):
    image = run(provider.aerial(DEMO_ID))
    assert isinstance(image, bytes)
    assert image[:2] == b"\xff\xd8"


def test_interior_has_the_lobby_scan_with_walls(provider):
    interior = run(provider.interior(DEMO_ID))
    lobby = next(m for m in interior["models"] if m["name"] == "Lobby")
    edges = [e for room in lobby["rooms"] for e in room["boundary"]["edges"]]
    assert len(edges) > 0


@pytest.mark.parametrize("method", ["record", "aerial", "interior", "graph", "scans"])
def test_unknown_building_id_raises(provider, method):
    with pytest.raises(LookupError):
        run(getattr(provider, method)("does-not-exist"))


def test_graph_is_the_routing_graph_for_the_building(provider):
    graph = run(provider.graph(DEMO_ID))
    assert graph["building_id"] == DEMO_ID
    assert {n["id"] for n in graph["nodes"]} >= {"st_main", "gar1", "phone_door"}
    assert graph["edges"]


def test_scans_has_the_sweeps_the_fly_through_flies_to(provider):
    scans = run(provider.scans(DEMO_ID))
    (model,) = scans["models"]
    assert model["id"] == "LJn59uoV759" and len(model["sweeps"]) == 14
    assert {"id", "x", "y", "z", "level", "neighbors"} <= set(model["sweeps"][0])
