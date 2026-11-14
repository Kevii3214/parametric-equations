import asyncio

import pytest

from app.agent.tools import make_route_tools
from app.graph.schema import RouteStep
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"
BUILDING = "233928"


@pytest.fixture
def db():
    return FakeSupabase(
        incidents=[{"id": INCIDENT, "status": "planning", "building_id": BUILDING}],
        closures=[],
        routes=[],
    )


@pytest.fixture
def tools(db):
    return {t.name: t for t in make_route_tools(SnapshotProvider(), db, INCIDENT)}


def call(tool, **args):
    return asyncio.run(tool.ainvoke(args))


def test_the_route_tools_are_the_four_the_agent_needs(tools):
    assert set(tools) == {"list_entrances", "find_destination_nodes", "plan_route", "choose_route"}


def test_list_entrances_names_each_way_in(tools):
    entrances = call(tools["list_entrances"], building_id=BUILDING)["entrances"]
    assert {e["node_id"] for e in entrances} == {"st_main", "gar1"}
    assert all(e["label"] and e["floor"] == 1 for e in entrances)


def test_find_destination_nodes_matches_labels_ignoring_case(tools):
    nodes = call(tools["find_destination_nodes"], building_id=BUILDING, text="PHONE room")["nodes"]
    assert "phone_door" in {n["node_id"] for n in nodes}
    assert all("phone room" in n["label"].lower() for n in nodes)


def test_find_destination_nodes_finds_every_node_for_a_suite(tools):
    ids = {
        n["node_id"]
        for n in call(tools["find_destination_nodes"], building_id=BUILDING, text="1800")["nodes"]
    }
    assert ids == {"door18", "phone_door"}


def test_find_destination_nodes_with_no_match_says_so(tools):
    assert call(tools["find_destination_nodes"], building_id=BUILDING, text="zzz")["nodes"] == []


def test_plan_route_returns_the_routers_steps_without_saving_anything(tools, db):
    result = call(
        tools["plan_route"], building_id=BUILDING, start_node="st_main", goal_node="phone_door"
    )
    assert result["total_seconds"] == 111
    assert result["steps"][-1]["cue"] == "ARRIVE"
    assert db.rows("routes") == []


def test_plan_route_avoids_what_is_closed_for_this_incident_only(tools, db):
    db.rows("closures").extend(
        [
            {"incident_id": INCIDENT, "node_or_edge": "el1->el18", "reason": "elevator out"},
            {"incident_id": "someone-else", "node_or_edge": "stair1", "reason": "other incident"},
        ]
    )
    result = call(
        tools["plan_route"], building_id=BUILDING, start_node="st_main", goal_node="phone_door"
    )
    assert result["total_seconds"] == 487  # by stairs: the other incident's closure is ignored


@pytest.mark.parametrize(
    "args",
    [
        {"building_id": BUILDING, "start_node": "nope", "goal_node": "phone_door"},
        {"building_id": "no-such-building", "start_node": "st_main", "goal_node": "phone_door"},
    ],
)
def test_plan_route_reports_bad_input_as_an_error_result(tools, args):
    assert "error" in call(tools["plan_route"], **args)


def test_plan_route_reports_when_there_is_no_route(tools, db):
    db.rows("closures").append({"incident_id": INCIDENT, "node_or_edge": "el1->el18"})
    db.rows("closures").append({"incident_id": INCIDENT, "node_or_edge": "stair1->stair18"})
    result = call(
        tools["plan_route"], building_id=BUILDING, start_node="st_main", goal_node="phone_door"
    )
    assert "no stretcher-safe route" in result["error"].lower()


def test_choose_route_saves_the_routers_route_and_moves_the_incident_on(tools, db):
    result = call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="Take the garage entrance, ride to 18, left of the elevators.",
    )
    assert result == {"route_version": 1, "total_seconds": 109, "step_count": 7}
    (row,) = db.rows("routes")
    assert (row["incident_id"], row["version"], row["entrance_node"]) == (INCIDENT, 1, "gar1")
    assert row["total_seconds"] == 109 and row["briefing"].startswith("Take the garage")
    assert [RouteStep.model_validate(s).index for s in row["steps"]] == list(range(7))
    assert row["steps"][-1]["cue"] == "ARRIVE"
    assert db.rows("incidents")[0]["status"] == "en_route"


def test_choose_route_numbers_new_versions_after_a_replan(tools, db):
    args = {
        "building_id": BUILDING,
        "start_node": "st_main",
        "goal_node": "phone_door",
        "briefing": "b",
    }
    call(tools["choose_route"], **args)
    call(tools["choose_route"], **args)
    assert [r["version"] for r in db.rows("routes")] == [1, 2]


def test_the_model_cannot_supply_route_steps(tools):
    """Golden rule: the router picks the path, never the LLM."""
    assert set(tools["choose_route"].args) == {"building_id", "start_node", "goal_node", "briefing"}


def test_choose_route_with_a_bad_node_saves_nothing(tools, db):
    result = call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="nope",
        goal_node="phone_door",
        briefing="b",
    )
    assert "error" in result and db.rows("routes") == []
    assert db.rows("incidents")[0]["status"] == "planning"


def test_long_briefings_are_trimmed(tools, db):
    call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="st_main",
        goal_node="phone_door",
        briefing="x" * 3000,
    )
    assert len(db.rows("routes")[0]["briefing"]) <= 600


def test_a_blank_briefing_is_written_from_the_route(tools, db):
    call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="  ",
    )
    assert "elevator" in db.rows("routes")[0]["briefing"].lower()


def test_a_long_briefing_is_cut_to_about_ten_seconds(tools, db):
    call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing=" ".join(["word"] * 100),
    )
    assert len(db.rows("routes")[0]["briefing"].split()) <= 35


def test_choose_route_also_saves_the_fly_through_tour(tools, db):
    call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="b",
    )
    tour = db.rows("routes")[0]["tour"]
    assert tour["version"] == 1 and [s["kind"] for s in tour["segments"]] == ["gap", "scanned"]
    assert tour["keyframes"][-1]["node"] == "phone_door" and tour["keyframes"][-1]["sweep_id"]


def test_a_new_route_version_gets_its_own_tour(tools, db):
    args = {
        "building_id": BUILDING,
        "start_node": "gar1",
        "goal_node": "phone_door",
        "briefing": "b",
    }
    call(tools["choose_route"], **args)
    db.rows("closures").append({"incident_id": INCIDENT, "node_or_edge": "el1->el18"})
    call(tools["choose_route"], **args)
    first, second = (r["tour"] for r in db.rows("routes"))
    assert second["duration_ms"] > first["duration_ms"]  # the climb by stairs takes longer


def test_the_route_is_still_saved_when_the_database_has_no_tour_column_yet(tools, db):
    db.missing_columns["routes"] = {"tour"}
    result = call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="b",
    )
    assert result["route_version"] == 1
    (row,) = db.rows("routes")
    assert "tour" not in row and row["total_seconds"] == 109
    assert db.rows("incidents")[0]["status"] == "en_route"


def test_a_building_with_no_scan_data_saves_a_route_without_a_tour(db):
    class NoScans(SnapshotProvider):
        async def scans(self, building_id):
            raise LookupError("no scans")

    tools = {t.name: t for t in make_route_tools(NoScans(), db, INCIDENT)}
    call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="b",
    )
    assert "tour" not in db.rows("routes")[0]


def test_a_failing_tour_never_stops_the_route_being_saved(tools, db, monkeypatch):
    import app.agent.tools as agent_tools

    def boom(*args, **kwargs):
        raise RuntimeError("tour bug")

    monkeypatch.setattr(agent_tools, "build_tour", boom)
    result = call(
        tools["choose_route"],
        building_id=BUILDING,
        start_node="gar1",
        goal_node="phone_door",
        briefing="b",
    )
    assert result["route_version"] == 1 and "tour" not in db.rows("routes")[0]
