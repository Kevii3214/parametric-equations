import asyncio
import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.db import get_db
from app.intake import NoteParser
from app.models import IncidentCreate

logger = logging.getLogger(__name__)
router = APIRouter()


@lru_cache
def get_parser() -> NoteParser:
    return NoteParser()


@router.post("/incidents")
async def create_incident(
    body: IncidentCreate,
    parse: Annotated[NoteParser, Depends(get_parser)],
    db: Annotated[Client, Depends(get_db)],
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
    return {"incident_id": result.data[0]["id"]}
