import asyncio
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from supabase import Client

from app.db import get_db
from app.intake import NoteParser
from app.models import IncidentCreate

logger = logging.getLogger(__name__)
router = APIRouter()


@lru_cache
def get_parser() -> NoteParser:
    return NoteParser()


def get_agent_runner() -> Callable[[str], Awaitable[None]]:
    async def runner(incident_id: str) -> None:
        from app.agent.agent import run_incident

        await run_incident(incident_id, db=get_db())

    return runner


@router.post("/incidents")
async def create_incident(
    body: IncidentCreate,
    parse: Annotated[NoteParser, Depends(get_parser)],
    db: Annotated[Client, Depends(get_db)],
    background: BackgroundTasks,
    run_agent: Annotated[Callable[[str], Awaitable[None]], Depends(get_agent_runner)],
) -> dict:
    parsed = None
    try:
        parsed = (await parse(body.note)).model_dump()
    except Exception:  # the call must be recorded even if Gemini fails; the agent can parse again
        logger.exception("Could not parse the call note; saving the incident without parsed fields")

    row = {"note": body.note, "parsed": parsed, "status": "planning"}
    try:
        result = await asyncio.to_thread(lambda: db.table("incidents").insert(row).execute())
    except Exception as error:  # any database failure means the call was not recorded
        logger.exception("Could not save the incident")
        raise HTTPException(status_code=503, detail="Could not save the incident") from error
    incident_id = result.data[0]["id"]
    background.add_task(
        run_agent, incident_id
    )  # the agent runs after the reply, never blocking the request
    return {"incident_id": incident_id}
