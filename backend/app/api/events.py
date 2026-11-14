import asyncio
import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.agent.replan import replan
from app.api.telemetry import EngineRegistry, get_registry
from app.db import get_db
from app.models import EventIn
from app.notes import Embedder, default_embedder, save_note

logger = logging.getLogger(__name__)
router = APIRouter()


@lru_cache
def get_embedder() -> Embedder:
    return default_embedder()


@router.post("/incidents/{incident_id}/events")
async def events(
    incident_id: str,
    event: EventIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    embed: Annotated[Embedder, Depends(get_embedder)],
) -> dict:
    if not await registry.knows(incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    building_id = registry.building_of(incident_id)

    if event.type == "note":
        text = (event.text or "").strip()
        if not text:
            raise HTTPException(status_code=422, detail="A note needs text")
        if not building_id:
            raise HTTPException(status_code=409, detail="This incident has no building yet")
        try:
            await save_note(db, embed, building_id, text)
        except Exception as error:
            logger.exception("Could not save a note")
            raise HTTPException(status_code=503, detail="Could not save the note") from error
    elif event.type == "arrived":
        await asyncio.to_thread(
            lambda: (
                db.table("incidents").update({"status": "arrived"}).eq("id", incident_id).execute()
            )
        )
    else:  # elevator_out or obstacle
        tracked = await registry.get(incident_id, db)
        if tracked is None or not building_id:
            raise HTTPException(status_code=409, detail="This incident has no route yet")
        async with tracked.lock:
            await replan(
                db,
                registry.provider,
                incident_id,
                building_id,
                event.type,
                tracked.engine,
                event.text,
            )
    return {"ok": True}
