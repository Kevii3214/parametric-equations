import asyncio
import json
import logging

from deepagents import create_deep_agent
from langchain.agents.middleware import (
    ModelCallLimitMiddleware,
    ModelFallbackMiddleware,
    TodoListMiddleware,
)

from app.agent.knowledge import READ_ONLY, knowledge_files
from app.agent.subagents import notes_subagent, records_subagent, site_subagent
from app.agent.tools import make_notes_tools, make_route_tools
from app.agent.trace import PlanTrace, TraceHandler
from app.config import get_settings
from app.intake import model_names
from app.notes import default_embedder
from app.providers.snapshot import SnapshotProvider

logger = logging.getLogger(__name__)

RUN_CALL_LIMIT = 25  # model calls per run: a looping agent is cut off here
RECURSION_LIMIT = 60  # LangGraph's own cap on steps
MODEL_TIMEOUT_S = 25

MAIN_PROMPT = """You plan how an ambulance crew gets to a patient inside a building.
You never invent the walking route: a separate, tested router computes it. You choose between router
results and write the briefing. Your dispatch playbook is in your memory (/AGENTS.md).

1. Call write_todos first, listing the real work steps you will take (not the act of planning itself).
2. In ONE step, start three subagents with the task tool at the same time (parallel tool calls, not one
   after another), each given the street address and the room or suite from the call:
   - records: the CoStar facts (floor, elevators, data-quality warnings),
   - site: the building's entrances, the goal node for the patient, and which parts of the map are estimates,
   - crew-notes: tips earlier crews saved for this building.
   Each reports back as JSON.
3. Call plan_route for EVERY entrance the site subagent listed, in the same step (parallel tool calls), with
   its goal_node, then compare total_seconds. If the site subagent found no goal_node, say so and stop.
4. Call choose_route for the fastest one, with a spoken briefing for the crew, 30 words at most (about ten
   seconds): which entrance, the key turns and floor changes, anything relevant from the crew notes, and
   anything uncertain (such as a floor that is only a guess, or the estimates the site subagent reported).
5. Finish with one or two sentences saying what was saved.
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


def default_subagent_model(main):
    """The model for the lookup subagents: a faster one if GEMINI_SUBAGENT_MODEL is set, else the main model."""
    from langchain_google_genai import ChatGoogleGenerativeAI

    settings = get_settings()
    if not settings.gemini_subagent_model:
        return main
    return ChatGoogleGenerativeAI(
        model=settings.gemini_subagent_model,
        google_api_key=settings.google_api_key,
        temperature=0,
        timeout=MODEL_TIMEOUT_S,
        max_retries=0,
    )


def _guard_middleware(fallback_models) -> list:
    """Call limit plus model fallback. Each agent needs its own copy, subagents included."""
    middleware = [ModelCallLimitMiddleware(run_limit=RUN_CALL_LIMIT, exit_behavior="end")]
    if fallback_models:
        middleware.append(ModelFallbackMiddleware(*fallback_models))
    return middleware


def build_agent(
    *, model, fallback_models, provider, db, incident_id: str, embedder=None, subagent_model=None
):
    embedder = embedder or default_embedder()
    lookup_model = subagent_model or model  # the lookups are simple, so they may use a faster model
    guard = _guard_middleware(fallback_models)
    return create_deep_agent(
        model=model,
        # the route tools plus save_note: the lookup tools belong to the subagents
        tools=[
            *make_route_tools(provider, db, incident_id),
            *[t for t in make_notes_tools(db, embedder) if t.name == "save_note"],
        ],
        system_prompt=MAIN_PROMPT,
        subagents=[
            records_subagent(provider, db, incident_id, lookup_model, guard),
            site_subagent(provider, db, incident_id, lookup_model, guard),
            notes_subagent(provider, db, incident_id, lookup_model, embedder, guard),
        ],
        middleware=[TodoListMiddleware(), *guard],
        memory=["/AGENTS.md"],  # the dispatch playbook, seeded into the virtual file system below
        permissions=READ_ONLY,  # the model may read the seeded files, never change them
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
    incident_id: str,
    *,
    db,
    provider=None,
    model=None,
    fallback_models=None,
    subagent_model=None,
    embedder=None,
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
            subagent_model = default_subagent_model(model)
        agent = build_agent(
            model=model,
            fallback_models=fallback_models or [],
            provider=provider or SnapshotProvider(),
            db=db,
            incident_id=incident_id,
            subagent_model=subagent_model,
            embedder=embedder,
        )
        result = await agent.ainvoke(
            {"messages": [("user", _briefing(incident))], "files": knowledge_files()},
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
