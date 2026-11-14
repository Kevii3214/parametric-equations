from deepagents import SubAgent

from app.agent.tools import make_records_tools

RECORDS_PROMPT = """You are the records specialist for an ambulance crew's route planner.
Your job: from the call details you are given, find the building and the patient's suite and floor.

1. Call resolve_building with the street address.
2. Call get_building_record for its elevators, parking and warnings.
3. If a suite is given, call find_suite.

Report briefly: the building id and name, the suite, who is there, the floor, how many passenger
elevators there are, and any data-quality warning. Say clearly when something is a guess, such as a floor
worked out from a suite number. If a tool returns an error, say so; never invent a building, suite or floor."""


def records_subagent(provider, db, incident_id: str, model, middleware=()) -> SubAgent:
    return {
        "name": "records",
        "description": (
            "Looks up the building, the patient's suite and its floor, and the elevator and parking facts "
            "from CoStar building data. Give it the street address and suite from the call."
        ),
        "system_prompt": RECORDS_PROMPT,
        "tools": make_records_tools(provider, db, incident_id),
        "model": model,
        "middleware": list(
            middleware
        ),  # subagents do not inherit the main agent's fallback and call limit
    }
