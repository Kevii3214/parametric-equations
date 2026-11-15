import pytest
from langchain.agents.structured_output import ToolStrategy
from pydantic import ValidationError

from app.agent.findings import NotesFindings, RecordsFindings, SiteFindings
from app.agent.knowledge import AGENTS_MD, knowledge_files
from app.agent.subagents import notes_subagent, records_subagent, site_subagent
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase


async def embed(text):
    return [0.0]


@pytest.fixture
def subagents():
    db = FakeSupabase(incidents=[], notes=[])
    p = SnapshotProvider()
    return {
        "records": records_subagent(p, db, "i", "m"),
        "site": site_subagent(p, db, "i", "m"),
        "crew-notes": notes_subagent(p, db, "i", "m", embed),
    }


def test_each_subagent_has_only_its_own_lookup_tools(subagents):
    tools = {name: {t.name for t in sa["tools"]} for name, sa in subagents.items()}
    assert tools == {
        "records": {"resolve_building", "get_building_record", "find_suite"},
        "site": {"resolve_building", "list_entrances", "find_destination_nodes"},
        "crew-notes": {"resolve_building", "search_notes"},
    }
    for sa in subagents.values():  # none of them can save a route or a note
        assert not {t.name for t in sa["tools"]} & {"choose_route", "plan_route", "save_note"}


def test_each_subagent_reports_a_typed_result(subagents):
    formats = {name: sa["response_format"] for name, sa in subagents.items()}
    assert all(isinstance(f, ToolStrategy) for f in formats.values())
    assert [f.schema for f in formats.values()] == [RecordsFindings, SiteFindings, NotesFindings]


def test_subagents_get_the_guard_middleware_and_the_model_passed_in():
    guard = ["limit", "fallback"]
    sa = site_subagent(SnapshotProvider(), FakeSupabase(), "i", "fast-model", guard)
    assert sa["middleware"] == guard and sa["middleware"] is not guard
    assert sa["model"] == "fast-model"


def test_findings_default_to_empty_and_reject_the_wrong_shape():
    assert SiteFindings().entrances == [] and SiteFindings().goal_node is None
    assert NotesFindings().tips == []
    with pytest.raises(ValidationError):
        SiteFindings(entrances="gar1")


def test_the_virtual_file_system_has_the_playbook_and_every_buildings_notes():
    files = knowledge_files()
    assert "/AGENTS.md" in files and AGENTS_MD in files["/AGENTS.md"]["content"]
    assert {"/buildings/233928/GRAPH_NOTES.md", "/buildings/233903/GRAPH_NOTES.md"} <= set(files)
    assert "/buildings/jrr/GRAPH_NOTES.md" in files
    assert "estimated" in files["/buildings/233928/GRAPH_NOTES.md"]["content"].lower()
