import asyncio
from uuid import uuid4

from app.agent.trace import PlanTrace, TraceHandler
from tests.fakes import FakeSupabase

INCIDENT = "inc-1"


def run(coro):
    return asyncio.run(coro)


def steps(db):
    return db.rows("plan_steps")


def test_trace_writes_numbered_rows_for_the_incident():
    db = FakeSupabase()
    trace = PlanTrace(db, INCIDENT)

    async def go():
        await trace.add("plan", "Plan: look up the building", {"steps": ["a", "b"]})
        await trace.add("tool_call", "resolve_building(...)")

    run(go())
    assert [(r["seq"], r["kind"], r["incident_id"]) for r in steps(db)] == [
        (1, "plan", INCIDENT),
        (2, "tool_call", INCIDENT),
    ]
    assert steps(db)[0]["detail"] == {"steps": ["a", "b"]}
    assert steps(db)[1]["detail"] == {}


def test_trace_numbers_stay_in_order_when_writes_overlap():
    db = FakeSupabase()
    trace = PlanTrace(db, INCIDENT)

    async def go():
        await asyncio.gather(*(trace.add("tool_call", f"call {i}") for i in range(10)))

    run(go())
    assert sorted(r["seq"] for r in steps(db)) == list(range(1, 11))


def test_a_failing_database_never_breaks_the_agent():
    db = FakeSupabase()
    db.fail_tables.add("plan_steps")
    run(PlanTrace(db, INCIDENT).add("plan", "Plan"))  # must not raise


def test_long_titles_and_details_are_trimmed():
    db = FakeSupabase()
    run(PlanTrace(db, INCIDENT).add("tool_result", "x" * 1000, {"output": "y" * 20000}))
    row = steps(db)[0]
    assert len(row["title"]) <= 200
    assert len(row["detail"]["output"]) <= 4000


# ------------------------------------------------------------ callback handler


def handler_with_trace():
    db = FakeSupabase()
    return TraceHandler(PlanTrace(db, INCIDENT)), db


def test_make_plan_tool_becomes_a_plan_step():
    handler, db = handler_with_trace()

    async def go():
        run_id = uuid4()
        await handler.on_tool_start(
            {"name": "make_plan"},
            "",
            run_id=run_id,
            inputs={"steps": ["find building", "find suite"]},
        )
        await handler.on_tool_end("Plan recorded.", run_id=run_id)

    run(go())
    (row,) = steps(db)  # the tool's own reply is not repeated as a result
    assert row["kind"] == "plan"
    assert row["detail"]["steps"] == ["find building", "find suite"]
    assert "find building" in row["title"]


def test_task_tool_becomes_a_subagent_step_and_its_result():
    handler, db = handler_with_trace()

    async def go():
        run_id = uuid4()
        await handler.on_tool_start(
            {"name": "task"},
            "",
            run_id=run_id,
            inputs={
                "subagent_type": "records",
                "description": "Find Suite 1800 at 1415 Louisiana St",
            },
        )
        await handler.on_tool_end("Suite 1800 is on floor 18", run_id=run_id)

    run(go())
    start, end = steps(db)
    assert start["kind"] == "subagent" and "records" in start["title"]
    assert start["detail"]["description"].startswith("Find Suite 1800")
    assert end["kind"] == "tool_result" and "Suite 1800 is on floor 18" in end["detail"]["output"]


def test_other_tools_become_a_call_and_a_result():
    handler, db = handler_with_trace()

    async def go():
        run_id = uuid4()
        await handler.on_tool_start(
            {"name": "resolve_building"}, "", run_id=run_id, inputs={"address": "1415 Louisiana St"}
        )
        await handler.on_tool_end('{"building_id": "233928"}', run_id=run_id)

    run(go())
    call, result = steps(db)
    assert (call["kind"], call["detail"]["args"]) == ("tool_call", {"address": "1415 Louisiana St"})
    assert call["title"].startswith("resolve_building(")
    assert result["kind"] == "tool_result" and "233928" in result["detail"]["output"]


def test_a_tool_error_is_traced_as_a_result():
    handler, db = handler_with_trace()

    async def go():
        run_id = uuid4()
        await handler.on_tool_start({"name": "get_building_record"}, "", run_id=run_id, inputs={})
        await handler.on_tool_error(RuntimeError("boom"), run_id=run_id)

    run(go())
    assert steps(db)[-1]["kind"] == "tool_result" and "boom" in steps(db)[-1]["detail"]["error"]


def test_a_subagent_reply_is_traced_as_its_message_text_not_a_command_dump():
    from langchain_core.messages import ToolMessage
    from langgraph.types import Command

    handler, db = handler_with_trace()
    reply = Command(
        update={
            "messages": [ToolMessage(content="Suite 1800 is Regus, floor 18.", tool_call_id="t")]
        }
    )

    async def go():
        run_id = uuid4()
        await handler.on_tool_start(
            {"name": "task"},
            "",
            run_id=run_id,
            inputs={"subagent_type": "records", "description": "d"},
        )
        await handler.on_tool_end(reply, run_id=run_id)

    run(go())
    output = steps(db)[-1]["detail"]["output"]
    assert output == "Suite 1800 is Regus, floor 18."
    assert "Command(" not in steps(db)[-1]["title"]
