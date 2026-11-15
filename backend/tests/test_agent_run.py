import asyncio
from itertools import cycle
from pathlib import Path
from typing import Any

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from app.agent.agent import RUN_CALL_LIMIT, run_incident
from app.providers.snapshot import SnapshotProvider
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"
NOTE = "65M chest pain, Regus Suite 1800, 1415 Louisiana St"


class ScriptedModel(GenericFakeChatModel):
    """A chat model that replays prepared messages, including tool calls."""

    def bind_tools(self, tools, **kwargs):
        return self


class DeadModel(ScriptedModel):
    def _generate(self, *args, **kwargs):
        raise RuntimeError("Gemini is down")


class Routed(ScriptedModel):
    """One model standing in for the main agent and the three subagents, which run at the same time.

    Each caller has its own script, chosen by a phrase in its system prompt, so the order they run in does not
    matter. `calls` counts the model calls each one made.
    """

    scripts: dict[str, Any] = Field(default_factory=dict)
    calls: dict[str, int] = Field(default_factory=dict)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        system = " ".join(str(m.content) for m in messages if m.type == "system")
        for marker, replies in self.scripts.items():
            if marker in system:
                self.calls[marker] = self.calls.get(marker, 0) + 1
                return ChatResult(generations=[ChatGeneration(message=next(replies))])
        raise RuntimeError(f"no script for a caller whose prompt starts: {system[:60]}")


def routed(**scripts):
    return Routed(messages=iter([]), scripts={k: iter(v) for k, v in scripts.items()})


MAIN, RECORDS, SITE, CREW = (
    "You plan how an ambulance crew",
    "records specialist",
    "site specialist",
    "crew-notes specialist",
)


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def calls(*named):
    """One model turn that makes several tool calls at once (they run in parallel)."""
    return AIMessage(
        content="",
        tool_calls=[{"name": n, "args": a, "id": f"{n}-{i}"} for i, (n, a) in enumerate(named)],
    )


def script(*messages):
    return ScriptedModel(messages=iter(messages))


def new_db(parsed=None):
    return FakeSupabase(
        incidents=[
            {
                "id": INCIDENT,
                "note": NOTE,
                "parsed": parsed,
                "building_id": None,
                "status": "planning",
            }
        ]
    )


async def no_embeddings(text):
    raise RuntimeError("no embeddings in tests")  # crew-note search falls back to words


def run(db, model, fallback_models=(), **kwargs):
    kwargs.setdefault("embedder", no_embeddings)
    asyncio.run(
        run_incident(
            INCIDENT,
            db=db,
            provider=SnapshotProvider(),
            model=model,
            fallback_models=list(fallback_models),
            **kwargs,
        )
    )


ADDRESS = {"address": "1415 Louisiana St"}
TODOS = {"todos": [{"content": "Look up the building", "status": "pending"}]}
THREE_TASKS = calls(
    ("task", {"subagent_type": "records", "description": "Suite 1800 at 1415 Louisiana St"}),
    ("task", {"subagent_type": "site", "description": "Entrances and the phone room"}),
    ("task", {"subagent_type": "crew-notes", "description": "Tips for 1415 Louisiana St"}),
)
RECORDS_SCRIPT = [
    calls(
        ("get_building_record", {"building_id": "233928"}),
        ("find_suite", {"building_id": "233928", "suite": "1800"}),
    ),
    tool_call(
        "RecordsFindings",
        {"building_id": "233928", "suite": "1800", "tenant": "Regus", "floor": 18},
        "r3",
    ),
]
SITE_SCRIPT = [
    calls(
        ("list_entrances", {"building_id": "233928"}),
        ("find_destination_nodes", {"building_id": "233928", "text": "phone room"}),
        ("read_file", {"file_path": "/buildings/233928/GRAPH_NOTES.md"}),
    ),
    tool_call(
        "SiteFindings",
        {
            "building_id": "233928",
            "entrances": [{"node_id": "st_main"}, {"node_id": "gar1"}],
            "goal_node": "phone_door",
            "estimates": "Only the suite is measured.",
        },
        "s3",
    ),
]
CREW_SCRIPT = [
    tool_call("search_notes", {"building_id": "233928", "query": "access"}, "c2"),
    tool_call("NotesFindings", {"building_id": "233928", "tips": []}, "c3"),
]
MAIN_SCRIPT = [
    tool_call("write_todos", TODOS, "m1"),
    THREE_TASKS,
    calls(
        (
            "plan_route",
            {"building_id": "233928", "start_node": "st_main", "goal_node": "phone_door"},
        ),
        ("plan_route", {"building_id": "233928", "start_node": "gar1", "goal_node": "phone_door"}),
    ),
    tool_call(
        "choose_route",
        {
            "building_id": "233928",
            "start_node": "gar1",
            "goal_node": "phone_door",
            "briefing": "Use the garage entrance, take the elevator to 18, then the phone room is ahead.",
        },
        "m4",
    ),
    AIMessage(content="Route saved: garage entrance, about 109 seconds."),
]


def happy_model(**overrides):
    scripts = {MAIN: MAIN_SCRIPT, RECORDS: RECORDS_SCRIPT, SITE: SITE_SCRIPT, CREW: CREW_SCRIPT}
    return routed(**{**scripts, **overrides})


def test_the_three_lookup_subagents_run_and_the_main_agent_saves_the_fastest_route():
    db = new_db()
    run(db, happy_model())
    steps = db.rows("plan_steps")
    assert [s["seq"] for s in steps] == list(range(1, len(steps) + 1))
    assert steps[0]["kind"] == "plan" and steps[-1]["kind"] == "final"
    subagents = [s["detail"]["subagent"] for s in steps if s["kind"] == "subagent"]
    assert sorted(subagents) == ["crew-notes", "records", "site"]
    called = [s["detail"]["tool"] for s in steps if s["kind"] == "tool_call"]
    assert (
        "resolve_building" not in called
    )  # the building was found in code, before the agent started
    assert called.count("plan_route") == 2 and called[-1] == "choose_route"
    assert {
        "get_building_record",
        "find_suite",
        "list_entrances",
        "search_notes",
        "read_file",
    } <= set(called)
    (route,) = db.rows("routes")
    assert (route["entrance_node"], route["total_seconds"], route["version"]) == ("gar1", 109, 1)
    assert route["steps"][-1]["cue"] == "ARRIVE" and "garage" in route["briefing"].lower()
    assert db.rows("incidents")[0]["status"] == "en_route"
    assert db.rows("incidents")[0]["building_id"] == "233928"
    assert "109" in steps[-1]["title"]


def test_the_main_agent_needs_only_five_model_turns():
    """The speed-up: the lookups run side by side, so the main agent never waits on them one at a time."""
    model = happy_model()
    run(new_db(), model)
    assert (
        model.calls[MAIN] == 5
    )  # todos, the three subagents, every entrance, the choice, the summary
    assert (
        model.calls[RECORDS] == model.calls[SITE] == model.calls[CREW] == 2
    )  # lookups, then the report


def test_the_site_subagent_reads_the_building_notes_from_the_virtual_file_system():
    db = new_db()
    run(db, happy_model())
    reads = [s for s in db.rows("plan_steps") if s["detail"].get("tool") == "read_file"]
    output = next(s["detail"]["output"] for s in reads if s["kind"] == "tool_result")
    assert "measured" in output and "Regus Suite 1800" in output


def test_the_playbook_is_loaded_as_memory():
    seen = []

    class Spy(Routed):
        def _generate(self, messages, *args, **kwargs):
            seen.append(" ".join(str(m.content) for m in messages if m.type == "system"))
            return super()._generate(messages, *args, **kwargs)

    spy = Spy(messages=iter([]), scripts={MAIN: [AIMessage(content="ok")]})
    run(new_db(), spy)
    assert "Never invent a building, node, route" in seen[0]
    assert "/buildings/<building_id>/GRAPH_NOTES.md" in seen[0]


def test_no_goal_node_means_no_route_is_saved_and_the_agent_says_so():
    site_found_nothing = [
        tool_call(
            "SiteFindings",
            {"building_id": "233928", "entrances": [{"node_id": "gar1"}], "error": "no such room"},
            "s2",
        ),
    ]
    main = [
        tool_call("write_todos", TODOS, "m1"),
        THREE_TASKS,
        AIMessage(content="I could not find the patient's room on the map, so no route was saved."),
    ]
    db = new_db()
    run(db, happy_model(**{MAIN: main, SITE: site_found_nothing}))
    assert db.rows("routes") == []
    assert db.rows("plan_steps")[-1]["kind"] == "final"
    assert "no route" in db.rows("plan_steps")[-1]["title"].lower()


def test_a_second_write_todos_only_ticks_items_off_and_adds_no_second_plan_row():
    main = [tool_call("write_todos", TODOS, "m1"), tool_call("write_todos", TODOS, "m2")]
    main += [AIMessage(content="done")]
    db = new_db()
    run(db, routed(**{MAIN: main}))
    assert [s["kind"] for s in db.rows("plan_steps")] == ["plan", "final"]


def test_agent_stops_cleanly_and_says_so_when_the_model_is_down():
    db = new_db()
    run(db, DeadModel(messages=iter([])))
    final = db.rows("plan_steps")[-1]
    assert final["kind"] == "final" and "stopped" in final["title"].lower()
    assert "Gemini is down" in final["detail"]["error"]


def test_a_looping_agent_is_cut_off_by_the_call_limit():
    db = new_db()
    loop = ScriptedModel(messages=cycle([tool_call("write_todos", TODOS, "x")]))
    run(db, loop)
    steps = db.rows("plan_steps")
    assert steps[-1]["kind"] == "final"
    assert len(steps) <= RUN_CALL_LIMIT + 5


def test_unknown_incident_is_ignored_without_raising():
    db = FakeSupabase(incidents=[])
    asyncio.run(
        run_incident(
            "missing", db=db, provider=SnapshotProvider(), model=script(), fallback_models=[]
        )
    )
    assert db.rows("plan_steps") == []


def test_agent_gets_the_note_and_the_parsed_fields():
    seen = []

    class Spy(ScriptedModel):
        def _generate(self, messages, *args, **kwargs):
            seen.append(" ".join(str(m.content) for m in messages))
            return super()._generate(messages, *args, **kwargs)

    parsed = {"address": "1415 Louisiana St", "suite": "1800", "floor": None}
    run(new_db(parsed), Spy(messages=iter([AIMessage(content="ok")])))
    assert NOTE in seen[0] and '"suite": "1800"' in seen[0]


def test_the_agent_cannot_run_shell_commands_or_change_files(tmp_path, monkeypatch):
    """deepagents adds execute and file tools: no shell, and the seeded files are read-only."""
    monkeypatch.chdir(tmp_path)
    db = new_db()
    model = script(
        tool_call("execute", {"command": "echo PWNED"}, "1"),
        tool_call("write_file", {"file_path": "/beeline_probe.txt", "content": "hi"}, "2"),
        tool_call(
            "edit_file", {"file_path": "/AGENTS.md", "old_string": "Never", "new_string": "Do"}, "3"
        ),
        AIMessage(content="done"),
    )
    run(db, model)
    results = [s["detail"]["output"] for s in db.rows("plan_steps") if s["kind"] == "tool_result"]
    assert "not available" in results[0].lower()
    assert "permission" in results[1].lower() and "permission" in results[2].lower()
    assert not list(tmp_path.iterdir())  # nothing written to the working directory
    assert not (Path("/") / "beeline_probe.txt").exists()


def test_subagents_fail_over_to_the_fallback_model_too():
    """A quota error on the main model must not stop the subagents (this happened live)."""
    db = new_db()
    dead = DeadModel(messages=iter([]))
    run(db, dead, fallback_models=[happy_model()], subagent_model=dead)
    kinds = [s["kind"] for s in db.rows("plan_steps")]
    assert kinds[0] == "plan" and kinds[-1] == "final"
    assert kinds.count("subagent") == 3
    assert "stopped" not in db.rows("plan_steps")[-1]["title"].lower()
    assert len(db.rows("routes")) == 1


def test_agent_run_does_not_save_a_route_it_was_not_given_by_the_router():
    """A made-up node means no route is saved, and the agent is told why."""
    db = new_db()
    bad = [
        tool_call(
            "choose_route",
            {
                "building_id": "233928",
                "start_node": "made_up",
                "goal_node": "phone_door",
                "briefing": "b",
            },
            "1",
        ),
        AIMessage(content="I could not save a route."),
    ]
    run(db, script(*bad))
    assert db.rows("routes") == []
    assert any(
        "unknown node" in s["detail"].get("output", "").lower() for s in db.rows("plan_steps")
    )


def test_a_failure_after_the_route_was_saved_is_reported_as_saved():
    """The crew's route matters most: a model error while writing the summary must not look like a failure."""
    db = new_db()
    saved_then_dies = [
        tool_call(
            "choose_route",
            {
                "building_id": "233928",
                "start_node": "gar1",
                "goal_node": "phone_door",
                "briefing": "b",
            },
            "1",
        )
    ]  # the model has nothing more to say, so the next call fails
    run(db, script(*saved_then_dies))
    assert len(db.rows("routes")) == 1
    final = db.rows("plan_steps")[-1]
    assert final["kind"] == "final" and final["title"].startswith("Route saved")
    assert "error" in final["detail"]


def test_the_building_is_found_in_code_saved_and_given_to_the_agent_before_it_starts():
    seen = []

    class Spy(Routed):
        def _generate(self, messages, *args, **kwargs):
            seen.append(" ".join(str(m.content) for m in messages))
            return super()._generate(messages, *args, **kwargs)

    db = new_db()
    run(db, Spy(messages=iter([]), scripts={MAIN: [AIMessage(content="ok")]}))
    assert db.rows("incidents")[0]["building_id"] == "233928"  # no model call was needed for it
    assert "Building id: 233928 (already looked up" in seen[0]


def test_an_unknown_building_is_left_for_the_subagents_to_report():
    seen = []

    class Spy(Routed):
        def _generate(self, messages, *args, **kwargs):
            seen.append(" ".join(str(m.content) for m in messages))
            return super()._generate(messages, *args, **kwargs)

    db = new_db()
    db.rows("incidents")[0]["note"] = "65M chest pain, 1 Nowhere Lane, Atlantis"
    run(db, Spy(messages=iter([]), scripts={MAIN: [AIMessage(content="ok")]}))
    assert db.rows("incidents")[0]["building_id"] is None
    assert "Building id: unknown: each subagent must call resolve_building" in seen[0]
