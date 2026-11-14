import asyncio
import json
import logging

from deepagents import create_deep_agent
from langchain.agents.middleware import ModelCallLimitMiddleware, ModelFallbackMiddleware

from app.agent.subagents import records_subagent
from app.agent.tools import make_plan_tool, make_route_tools
from app.agent.trace import PlanTrace, TraceHandler
from app.config import get_settings
from app.intake import model_names
from app.providers.snapshot import SnapshotProvider

logger = logging.getLogger(__name__)

RUN_CALL_LIMIT = 25  # model calls per run: a looping agent is cut off here
RECURSION_LIMIT = 60  # LangGraph's own cap on steps
MODEL_TIMEOUT_S = 25

MAIN_PROMPT = """You plan how an ambulance crew gets to a patient inside a building.
You never invent the walking route: a separate, tested router computes it. You choose between router
results and write the briefing.

1. Call make_plan first, listing the real work steps you will take (not the act of planning itself).
2. Delegate the building and suite lookup to the records subagent with the task tool, giving it the
   street address and suite from the call.
3. Call list_entrances, then find_destination_nodes to pick the goal node. Use the most specific place the
   call gives: a room beats a suite. If the call only names a suite, choose that suite's entrance and say
   so in the briefing.
4. Call plan_route for EVERY entrance in the same step (parallel tool calls, not one after another), then
   compare total_seconds.
5. Call choose_route for the fastest one, with a briefing of two or three plain sentences for the crew:
   which entrance, the key turns and floor changes, and anything uncertain (such as a floor that is only
   a guess).
6. Finish with one or two sentences saying what was saved.
If a tool returns an error, say so plainly and stop; never invent a building, node, route or time."""


def default_models() -> tuple:
    """The main Gemini model and the fallbacks, from GEMINI_MODEL and GEMINI_FALLBACK_MODEL."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    models = [
        ChatGoogleGenerativeAI(
            model=name,
            google_api_key=settings.google_api_key,
            temperature=0,
            timeout=MODEL_TIMEOUT_S,
            max_retries=0,
        )
        for name in model_names(settings.gemini_model, settings.gemini_fallback_model)
    ]
    return models[0], models[1:]


def _guard_middleware(fallback_models) -> list:
    """Call limit plus model fallback. Each agent needs its own copy, subagents included."""
    middleware = [ModelCallLimitMiddleware(run_limit=RUN_CALL_LIMIT, exit_behavior="end")]
    if fallback_models:
        middleware.append(ModelFallbackMiddleware(*fallback_models))
    return middleware


def build_agent(*, model, fallback_models, provider, db, incident_id: str):
    return create_deep_agent(
        model=model,
        tools=[make_plan_tool(), *make_route_tools(provider, db, incident_id)],
        system_prompt=MAIN_PROMPT,
        subagents=[
            records_subagent(provider, db, incident_id, model, _guard_middleware(fallback_models))
        ],
        middleware=_guard_middleware(fallback_models),
        name="beeline",
    )


def _briefing(incident: dict) -> str:
    parsed = incident.get("parsed")
    fields = json.dumps(parsed) if parsed else "not available, so read the note yourself"
    return f"Call note: {incident['note']}\nParsed fields: {fields}"


def _last_text(messages) -> str:
    content = getattr(messages[-1], "content", "") if messages else ""
    if isinstance(content, list):  # Gemini can return a list of parts
        content = " ".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    return str(content).strip()


async def run_incident(
    incident_id: str, *, db, provider=None, model=None, fallback_models=None
) -> None:
    """Run the agent for one incident, writing its trail to plan_steps. Never raises."""
    try:
        rows = await asyncio.to_thread(
            lambda: db.table("incidents").select("*").eq("id", incident_id).execute()
        )
        if not rows.data:
            logger.warning("Agent asked to run for unknown incident %s", incident_id)
            return
        incident = rows.data[0]
    except Exception:
        logger.exception("Could not load incident %s for the agent", incident_id)
        return

    trace = PlanTrace(db, incident_id)
    try:
        if model is None:
            model, fallback_models = default_models()
        agent = build_agent(
            model=model,
            fallback_models=fallback_models or [],
            provider=provider or SnapshotProvider(),
            db=db,
            incident_id=incident_id,
        )
        result = await agent.ainvoke(
            {"messages": [("user", _briefing(incident))]},
            config={"recursion_limit": RECURSION_LIMIT, "callbacks": [TraceHandler(trace)]},
        )
        answer = _last_text(result["messages"])
        await trace.add("final", f"Final: {answer}", {"answer": answer})
    except Exception as error:
        logger.exception("Agent failed for incident %s", incident_id)
        if await _route_saved(db, incident_id):  # the crew's route exists; only the write-up failed
            title = "Route saved; the summary could not be written"
        else:
            title = f"Agent stopped: {type(error).__name__}"
        await trace.add("final", title, {"error": str(error)})


async def _route_saved(db, incident_id: str) -> bool:
    try:
        rows = await asyncio.to_thread(
            lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
        )
        return bool(rows.data)
    except Exception:  # noqa: BLE001 - if we cannot tell, report it as a stop
        return False
