from deepagents import SubAgent
from langchain.agents.structured_output import ToolStrategy

from app.agent.findings import NotesFindings, RecordsFindings, SiteFindings
from app.agent.tools import make_notes_tools, make_records_tools, make_route_tools

# Three lookups that do not depend on each other. The main agent starts all three in one step, so they run
# at the same time instead of one model turn after another.

RECORDS_PROMPT = """You are the records specialist for an ambulance crew's route planner.
Your job: from the call details you are given, find the building and the patient's suite and floor.

1. Call resolve_building with the street address.
2. Call get_building_record for its elevators, parking and warnings.
3. If a suite NUMBER is given (like 1800), call find_suite. Do not call it for a room name such as a classroom,
   or for a building name. Use only your own tools: there are no files to search.

Say clearly when something is a guess, such as a floor worked out from a suite number (floor_is_guess).
If a tool returns an error, put it in `error`; never invent a building, suite or floor."""

SITE_PROMPT = """You are the site specialist for an ambulance crew's route planner. You read the building's
indoor map: where the crew can get in and where the patient is.

1. Call resolve_building with the street address.
2. With the building id, call list_entrances, find_destination_nodes and read_file on
   /buildings/<building_id>/GRAPH_NOTES.md in the same step (parallel tool calls).
3. For the goal node use the most specific place the call gives: a room beats a suite. Try the room name first
   (for example 'phone room'), then the suite number. If the call only names a suite, use that suite's node and
   say so. If nothing matches, leave goal_node empty; never invent a node id.
4. Put one or two sentences from the notes file in `estimates`: which parts of the map are measured and which
   are estimated.
Use only your own tools. If a tool returns an error, put it in `error`."""

NOTES_PROMPT = """You are the crew-notes specialist for an ambulance crew's route planner. Earlier crews save
tips about buildings.

1. Call resolve_building with the street address.
2. Call search_notes with that building id and the query "access, elevators, entrances, hazards".
3. Report only tips that matter for getting in. If there are none, return an empty list.
Use only your own tools. If a tool returns an error, put it in `error`."""


def _pick(tools: list, *names: str) -> list:
    return [t for t in tools if t.name in names]


def _subagent(name, description, prompt, tools, findings, model, middleware) -> SubAgent:
    return {
        "name": name,
        "description": description,
        "system_prompt": prompt,
        "tools": tools,
        "model": model,
        "response_format": ToolStrategy(findings),
        # subagents do not inherit the main agent's fallback and call limit
        "middleware": list(middleware),
    }


def records_subagent(provider, db, incident_id: str, model, middleware=()) -> SubAgent:
    return _subagent(
        "records",
        "Looks up the building, the patient's suite and its floor, and the elevator and parking facts "
        "from CoStar building data. Give it the street address and suite from the call.",
        RECORDS_PROMPT,
        make_records_tools(provider, db, incident_id),
        RecordsFindings,
        model,
        middleware,
    )


def site_subagent(provider, db, incident_id: str, model, middleware=()) -> SubAgent:
    tools = _pick(make_records_tools(provider, db, incident_id), "resolve_building") + _pick(
        make_route_tools(provider, db, incident_id), "list_entrances", "find_destination_nodes"
    )
    return _subagent(
        "site",
        "Reads the building's indoor map: every entrance, the goal node for the patient's room or suite, "
        "and which parts of the map are estimates. Give it the street address and the room or suite.",
        SITE_PROMPT,
        tools,
        SiteFindings,
        model,
        middleware,
    )


def notes_subagent(provider, db, incident_id: str, model, embedder, middleware=()) -> SubAgent:
    tools = _pick(make_records_tools(provider, db, incident_id), "resolve_building") + _pick(
        make_notes_tools(db, embedder), "search_notes"
    )
    return _subagent(
        "crew-notes",
        "Searches tips that earlier crews saved for this building (lifts, doors, access, hazards). "
        "Give it the street address.",
        NOTES_PROMPT,
        tools,
        NotesFindings,
        model,
        middleware,
    )
