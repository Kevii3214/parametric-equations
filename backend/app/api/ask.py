import asyncio
import json
import logging
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.api.events import get_embedder
from app.db import get_db
from app.models import AskIn
from app.notes import Embedder, search_notes
from app.providers.snapshot import SnapshotProvider

logger = logging.getLogger(__name__)
router = APIRouter()

Answerer = Callable[[str, str], Awaitable[str]]

SYSTEM_PROMPT = """You answer quick questions from an ambulance crew who are on their way to a patient.
Answer ONLY from the context given. If the context does not say, reply "I don't have that information."
Never invent building details, directions or medical advice. Keep it to one or two short sentences."""

MAX_TENANTS = 40


def _model_chain():
    from app.agent.agent import default_models

    primary, fallbacks = default_models()
    return [primary, *fallbacks]


@lru_cache
def get_answerer() -> Answerer:
    async def answer(question: str, context: str) -> str:
        error: Exception | None = None
        for model in _model_chain():
            try:
                reply = await model.ainvoke(
                    [
                        ("system", SYSTEM_PROMPT),
                        ("human", f"Context:\n{context}\n\nQuestion: {question}"),
                    ]
                )
                content = reply.content
                if isinstance(content, list):
                    content = " ".join(
                        p.get("text", "") if isinstance(p, dict) else str(p) for p in content
                    )
                return str(content).strip()
            except Exception as failure:  # noqa: BLE001 - try the next model
                error = failure
        raise error or RuntimeError("No model configured")

    return answer


@lru_cache
def get_provider() -> SnapshotProvider:
    return SnapshotProvider()


def building_facts(record: dict) -> str:
    keep = [
        "name",
        "address",
        "city",
        "state",
        "property_type",
        "stories_above_grade",
        "typical_floor_sqft",
        "elevators",
        "parking",
        "data_quality_notes",
    ]
    facts = {k: record.get(k) for k in keep if record.get(k) is not None}
    tenants = (record.get("current_tenants") or [])[:MAX_TENANTS]
    facts["tenants"] = [f"Suite {t.get('suite')}: {t.get('company')}" for t in tenants]
    return json.dumps(facts, default=str)


@router.post("/ask")
async def ask(
    body: AskIn,
    db: Annotated[Client, Depends(get_db)],
    answerer: Annotated[Answerer, Depends(get_answerer)],
    embed: Annotated[Embedder, Depends(get_embedder)],
    provider: Annotated[SnapshotProvider, Depends(get_provider)],
) -> dict:
    incident_rows = await asyncio.to_thread(
        lambda: db.table("incidents").select("*").eq("id", body.incident_id).execute()
    )
    if not incident_rows.data:
        raise HTTPException(status_code=404, detail="Unknown incident")
    incident = incident_rows.data[0]
    building_id = incident.get("building_id")

    route_rows = await asyncio.to_thread(
        lambda: db.table("routes").select("*").eq("incident_id", body.incident_id).execute()
    )
    route = max(route_rows.data, key=lambda r: r["version"], default=None)

    sections = [f"Call note: {incident.get('note')}"]
    if building_id:
        try:
            sections.append("Building facts: " + building_facts(await provider.record(building_id)))
        except LookupError:
            pass
        try:
            notes = await search_notes(db, embed, building_id, body.question)
        except Exception:
            logger.exception("Could not search notes for /ask")
            notes = []
        if notes:
            sections.append("Crew notes from earlier calls: " + " | ".join(notes))
    if route:
        steps = " ".join(s["text"] for s in route["steps"])
        sections.append(
            f"Current route (version {route['version']}, about {route['total_seconds']} s). "
            f"Briefing: {route['briefing']} Steps: {steps}"
        )
    try:
        return {"answer": await answerer(body.question, "\n".join(sections))}
    except Exception:
        logger.exception("The answer model failed")
        fallback = route["briefing"] if route else "no route yet"
        return {"answer": f"I can't reach the assistant right now. Route briefing: {fallback}"}
