import asyncio

import pytest

from app.agent.tools import make_records_tools
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"


@pytest.fixture
def db():
    return FakeSupabase(
        incidents=[{"id": INCIDENT, "note": "n", "building_id": None, "status": "planning"}]
    )


@pytest.fixture
def tools(db):
    return {t.name: t for t in make_records_tools(SnapshotProvider(), db, INCIDENT)}


def call(tool, **args):
    return asyncio.run(tool.ainvoke(args))


def test_the_records_subagent_gets_three_tools(tools):
    assert set(tools) == {"resolve_building", "get_building_record", "find_suite"}


def test_resolve_building_returns_the_id_and_saves_it_on_the_incident(tools, db):
    result = call(tools["resolve_building"], address="1415 Louisiana St, Houston")
    assert result == {"building_id": "233928"}
    assert db.rows("incidents")[0]["building_id"] == "233928"


def test_resolve_building_reports_an_unknown_address_instead_of_raising(tools, db):
    result = call(tools["resolve_building"], address="1 Nowhere Lane")
    assert "error" in result
    assert db.rows("incidents")[0]["building_id"] is None


def test_building_record_is_a_short_summary_of_the_facts_that_matter(tools):
    record = call(tools["get_building_record"], building_id="233928")
    assert record["name"] == "1415 Louisiana"
    assert record["stories_above_grade"] == 43
    assert {"type": "Passenger", "count": 15, "exists": True} in record["elevators"]
    assert any(p["type"] == "Covered" and p["spaces"] == 1604 for p in record["parking"])
    assert "data_quality_notes" in record
    assert "current_tenants" not in record  # use find_suite for tenants


def test_building_record_for_an_unknown_building_is_an_error_result(tools):
    assert "error" in call(tools["get_building_record"], building_id="nope")


def test_find_suite_finds_the_tenant_and_guesses_the_floor_from_the_number(tools):
    result = call(tools["find_suite"], building_id="233928", suite="1800")
    assert result["tenant"] == "Regus"
    assert result["floor_guess"] == 18
    assert "suite number" in result["floor_basis"]


def test_find_suite_accepts_the_word_suite_and_spaces(tools):
    assert call(tools["find_suite"], building_id="233928", suite="Suite 1800 ")["floor_guess"] == 18


def test_find_suite_for_an_unlisted_suite_still_guesses_the_floor(tools):
    result = call(tools["find_suite"], building_id="233928", suite="2210")
    assert result["tenant"] is None and result["floor_guess"] == 22


def test_find_suite_does_not_guess_when_the_number_has_no_floor_in_it(tools):
    assert call(tools["find_suite"], building_id="233928", suite="B")["floor_guess"] is None
