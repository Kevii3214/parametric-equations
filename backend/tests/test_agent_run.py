import asyncio
from itertools import cycle
from pathlib import Path

from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage

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


def tool_call(name, args, call_id):
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


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


def run(db, model, fallback_models=(), **kwargs):
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


HAPPY_PATH = [
    tool_call("make_plan", {"steps": ["Find the building", "Find the suite and its floor"]}, "1"),
    tool_call(
        "task",
        {"subagent_type": "records", "description": "Find Suite 1800 at 1415 Louisiana St"},
        "2",
    ),
    tool_call("resolve_building", {"address": "1415 Louisiana St"}, "3"),
    tool_call("find_suite", {"building_id": "233928", "suite": "1800"}, "4"),
    AIMessage(content="Building 233928 is 1415 Louisiana. Suite 1800 is Regus, floor 18."),
    AIMessage(content="The patient is at Regus Suite 1800 on floor 18 of 1415 Louisiana."),
]


def test_agent_traces_its_plan_subagent_tools_and_final_answer():
    db = new_db()
    run(db, script(*HAPPY_PATH))
    steps = db.rows("plan_steps")
    assert [s["kind"] for s in steps] == [
        "plan",
        "subagent",
        "tool_call",  # resolve_building, run by the records subagent
        "tool_result",
        "tool_call",  # find_suite
        "tool_result",
        "tool_result",  # the records subagent reports back
        "final",
    ]
    assert [s["seq"] for s in steps] == list(range(1, 9))
    assert all(s["incident_id"] == INCIDENT for s in steps)
    assert steps[1]["title"].startswith("records subagent")
    assert steps[2]["title"].startswith("resolve_building(")
    assert "Regus" in steps[-1]["title"] or "Regus" in steps[-1]["detail"]["answer"]


def test_agent_saves_the_building_on_the_incident():
    db = new_db()
    run(db, script(*HAPPY_PATH))
    assert db.rows("incidents")[0]["building_id"] == "233928"


def test_agent_stops_cleanly_and_says_so_when_the_model_is_down():
    db = new_db()
    run(db, DeadModel(messages=iter([])))
    final = db.rows("plan_steps")[-1]
    assert final["kind"] == "final" and "stopped" in final["title"].lower()
    assert "Gemini is down" in final["detail"]["error"]


def test_a_looping_agent_is_cut_off_by_the_call_limit():
    db = new_db()
    loop = ScriptedModel(messages=cycle([tool_call("make_plan", {"steps": ["again"]}, "x")]))
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


def test_the_agent_cannot_run_shell_commands_or_write_real_files(tmp_path, monkeypatch):
    """deepagents adds execute and file tools; with no sandbox they must stay harmless."""
    monkeypatch.chdir(tmp_path)
    db = new_db()
    model = script(
        tool_call("execute", {"command": "echo PWNED"}, "1"),
        tool_call("write_file", {"file_path": "/beeline_probe.txt", "content": "hi"}, "2"),
        AIMessage(content="done"),
    )
    run(db, model)
    results = [s["detail"]["output"] for s in db.rows("plan_steps") if s["kind"] == "tool_result"]
    assert "not available" in results[0].lower()
    assert not list(tmp_path.iterdir())  # nothing written to the working directory
    assert not (Path("/") / "beeline_probe.txt").exists()


def test_subagents_fail_over_to_the_fallback_model_too():
    """A quota error on the main model must not stop the records subagent (this happened live)."""
    db = new_db()
    run(db, DeadModel(messages=iter([])), fallback_models=[script(*HAPPY_PATH)])
    kinds = [s["kind"] for s in db.rows("plan_steps")]
    assert kinds[0] == "plan" and kinds[-1] == "final"
    assert "subagent" in kinds and "stopped" not in db.rows("plan_steps")[-1]["title"].lower()
    assert db.rows("incidents")[0]["building_id"] == "233928"
