"""The crew chat endpoints: who is on an incident, what they text back, and the link they are sent.

Only the Photon sidecar calls /crew-threads/resolve and /incidents/{id}/crew-report (with a shared secret).
The card page at /medic/{id} is public but needs the token that was texted to the crew.
"""

import asyncio
import hmac
import html
import logging
import re
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Query
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field
from supabase import Client

from app.api.ask import get_provider
from app.api.events import get_embedder
from app.api.telemetry import EngineRegistry, get_registry
from app.config import get_settings
from app.db import get_db
from app.graph.schema import BuildingGraph, RouteStep
from app.notes import Embedder
from app.photon import share
from app.photon.card import render_route_card, static_card
from app.photon.classify import CrewClassifier
from app.photon.client import SidecarClient, get_sidecar
from app.photon.crew import handle_crew_report
from app.photon.notify import notify_route
from app.providers.snapshot import SnapshotProvider

logger = logging.getLogger(__name__)
router = APIRouter()


@lru_cache
def get_classifier() -> CrewClassifier:
    return CrewClassifier()


def get_sidecar_client() -> SidecarClient:
    try:
        return get_sidecar()
    except RuntimeError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error


def require_photon_secret(x_photon_secret: Annotated[str | None, Header()] = None) -> None:
    secret = get_settings().photon_shared_secret
    if not secret:
        raise HTTPException(status_code=503, detail="PHOTON_SHARED_SECRET is not set")
    if not x_photon_secret or not hmac.compare_digest(secret, x_photon_secret):
        raise HTTPException(status_code=401, detail="Bad secret")


def normalize_handle(handle: str) -> str:
    """A phone number as +15551234567, or an email address in lower case. Anything else is rejected."""
    handle = handle.strip()
    if "@" in handle:
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", handle):
            raise ValueError("That is not an email address")
        return handle.lower()
    digits = re.sub(r"[\s().-]", "", handle)
    if not re.fullmatch(r"\+[1-9]\d{6,14}", digits):
        raise ValueError("Use a phone number with its country code, like +15551234567")
    return digits


class CrewIn(BaseModel):
    handle: str = Field(max_length=254)
    name: str | None = Field(default=None, max_length=100)


class ReportIn(BaseModel):
    text: str = Field(max_length=2000)
    sender: str = Field(max_length=254)
    channel: str = Field(default="imessage", max_length=40)


class ResolveIn(BaseModel):
    handle: str = Field(max_length=254)
    space_id: str = Field(max_length=100)
    user_id: str = Field(max_length=100)


async def _select(db, table: str, **match) -> list[dict]:
    def run():
        query = db.table(table).select("*")
        for column, value in match.items():
            query = query.eq(column, value)
        return query.execute().data

    return await asyncio.to_thread(run)


async def _latest_route(db, incident_id: str) -> dict | None:
    rows = await _select(db, "routes", incident_id=incident_id)
    return max(rows, key=lambda r: r["version"], default=None)


def _public(member: dict) -> dict:
    return {
        "handle": member["handle"],
        "name": member.get("name"),
        "assigned_phone_number": member.get("assigned_phone_number"),
        "joined": bool(member.get("photon_space_id")),
    }


# ---------------------------------------------------------------- dispatcher side


@router.post("/incidents/{incident_id}/crew")
async def add_crew(
    incident_id: str,
    body: CrewIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    sidecar: Annotated[SidecarClient, Depends(get_sidecar_client)],
) -> dict:
    """Put a crew member on the incident. They must text the returned number once, then they get the route."""
    if not await registry.knows(incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    try:
        handle = normalize_handle(body.handle)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    try:
        assigned = await sidecar.assign(handle=handle, name=body.name)
    except Exception as error:
        logger.exception("Photon would not assign a line to %s", handle)
        raise HTTPException(status_code=502, detail="Photon could not assign a line") from error
    number = assigned.get("assigned_phone_number")
    existing = [
        m
        for m in await _select(db, "crew_threads", incident_id=incident_id)
        if m["handle"] == handle
    ]
    if existing:
        fields = {"name": body.name, "assigned_phone_number": number}
        await asyncio.to_thread(
            lambda: (
                db.table("crew_threads")
                .update(fields)
                .eq("incident_id", incident_id)
                .eq("handle", handle)
                .execute()
            )
        )
    else:
        row = {
            "incident_id": incident_id,
            "handle": handle,
            "name": body.name,
            "assigned_phone_number": number,
        }
        await asyncio.to_thread(lambda: db.table("crew_threads").insert(row).execute())
    return {"ok": True, "handle": handle, "text_this_number": number}


@router.get("/incidents/{incident_id}/crew")
async def list_crew(incident_id: str, db: Annotated[Client, Depends(get_db)]) -> dict:
    return {
        "crew": [_public(m) for m in await _select(db, "crew_threads", incident_id=incident_id)]
    }


# ------------------------------------------------------------------ sidecar side


@router.post("/crew-threads/resolve", dependencies=[Depends(require_photon_secret)])
async def resolve_thread(
    body: ResolveIn, db: Annotated[Client, Depends(get_db)], background: BackgroundTasks
) -> dict:
    """Which active incident does a text from this phone belong to? Remembers the thread for later sends."""
    try:
        handle = normalize_handle(body.handle)
    except ValueError:
        handle = body.handle.strip()
    candidates = []
    for member in await _select(db, "crew_threads", handle=handle):
        incident = await _select(db, "incidents", id=member["incident_id"])
        if incident and incident[0].get("status") != "arrived":
            candidates.append(member)
    if not candidates:
        raise HTTPException(status_code=404, detail="Not assigned to an active incident")
    member = max(candidates, key=lambda m: m.get("id", 0))
    first_contact = not member.get("photon_space_id")
    if first_contact or member.get("photon_space_id") != body.space_id:
        fields = {"photon_space_id": body.space_id, "photon_user_id": body.user_id}
        await asyncio.to_thread(
            lambda: (
                db.table("crew_threads")
                .update(fields)
                .eq("incident_id", member["incident_id"])
                .eq("handle", member["handle"])
                .execute()
            )
        )
    if first_contact:  # they can be messaged now: if a route already exists, send it straight away
        route = await _latest_route(db, member["incident_id"])
        if route:
            background.add_task(
                notify_route, db, member["incident_id"], route.get("briefing"), member["handle"]
            )
    return {"incident_id": member["incident_id"], "first_contact": first_contact}


@router.post("/incidents/{incident_id}/crew-report", dependencies=[Depends(require_photon_secret)])
async def crew_report(
    incident_id: str,
    body: ReportIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    classifier: Annotated[CrewClassifier, Depends(get_classifier)],
    provider: Annotated[SnapshotProvider, Depends(get_provider)],
    embed: Annotated[Embedder, Depends(get_embedder)],
) -> dict:
    """A crew text. Returns the replies for the sidecar to post back in the same chat."""
    if not await registry.knows(incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    try:
        sender = normalize_handle(body.sender)
    except ValueError:
        sender = body.sender.strip()
    return await handle_crew_report(
        db, provider, registry, classifier, embed, incident_id, body.text, sender, body.channel
    )


# --------------------------------------------------------------- the link preview


async def _card_context(db, provider: SnapshotProvider, incident_id: str, token: str):
    """(incident, route, title, subtitle) for a valid link, else a 404. Never reveals why it failed."""
    if not share.check_token(incident_id, token):
        raise HTTPException(status_code=404, detail="Not found")
    try:
        incidents = await _select(db, "incidents", id=incident_id)
    except Exception as error:
        if getattr(error, "code", None) == "22P02":
            raise HTTPException(status_code=404, detail="Not found") from error
        raise
    if not incidents:
        raise HTTPException(status_code=404, detail="Not found")
    incident = incidents[0]
    route = await _latest_route(db, incident_id)
    name = None
    if incident.get("building_id"):
        try:
            name = (await provider.record(incident["building_id"])).get("name")
        except LookupError:
            name = None
    parsed = incident.get("parsed") or {}
    title = name or parsed.get("address") or "Route to the patient"
    parts = []
    if parsed.get("suite"):
        parts.append(f"Suite {parsed['suite']}")
    last = (route or {}).get("steps") or []
    if last and isinstance(last[-1], dict) and last[-1].get("floor") is not None:
        parts.append(f"floor {last[-1]['floor']}")
    return incident, route, title, ", ".join(parts) or "Route ready"


@router.get("/medic/{incident_id}", response_class=HTMLResponse)
async def medic_page(
    incident_id: str,
    db: Annotated[Client, Depends(get_db)],
    provider: Annotated[SnapshotProvider, Depends(get_provider)],
    t: Annotated[str, Query()] = "",
    v: Annotated[str, Query()] = "",
) -> HTMLResponse:
    """Server-rendered head tags so link previews (which do not run JavaScript) get a card.

    People who tap the link are sent on to the web app's medic view."""
    _, route, title, subtitle = await _card_context(db, provider, incident_id, t)
    description = (route or {}).get("briefing") or "Your route is ready."
    here = share.medic_url(incident_id, v)
    image = share.card_url(incident_id, v)
    target = f"{get_settings().public_web_url.rstrip('/')}/arrival?incident={incident_id}"
    e = html.escape
    page = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>{e(title)} · {e(subtitle)}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta property="og:type" content="website">
<meta property="og:site_name" content="Pairatech">
<meta property="og:title" content="{e(title)} · {e(subtitle)}">
<meta property="og:description" content="{e(description)}">
<meta property="og:image" content="{e(image)}">
<meta property="og:image:width" content="1200">
<meta property="og:image:height" content="630">
<meta property="og:url" content="{e(here)}">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{e(title)} · {e(subtitle)}">
<meta name="twitter:description" content="{e(description)}">
<meta name="twitter:image" content="{e(image)}">
</head><body>
<p><a href="{e(target)}">Open the route for {e(title)}</a></p>
<script>location.replace({target!r});</script>
</body></html>"""
    return HTMLResponse(page, headers={"Cache-Control": "no-store"})


@router.get("/medic/{incident_id}/card.png")
async def medic_card(
    incident_id: str,
    db: Annotated[Client, Depends(get_db)],
    provider: Annotated[SnapshotProvider, Depends(get_provider)],
    t: Annotated[str, Query()] = "",
) -> Response:
    """The route drawn on the floor plan; the building's aerial picture if that cannot be drawn."""
    incident, route, title, subtitle = await _card_context(db, provider, incident_id, t)
    building_id = incident.get("building_id")
    png = None
    if route and building_id:
        try:
            graph = BuildingGraph.model_validate(await provider.graph(building_id))
            steps = [RouteStep.model_validate(s) for s in route["steps"]]
            png = render_route_card(graph, steps, title=title, subtitle=subtitle)
        except Exception:
            logger.exception("Could not draw the route card for incident %s", incident_id)
    if png is None:
        png = static_card(building_id, provider.directory, title=title, subtitle=subtitle)
    return Response(png, media_type="image/png", headers={"Cache-Control": "public, max-age=60"})
