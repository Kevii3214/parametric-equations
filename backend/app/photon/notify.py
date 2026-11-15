"""Text the crew when their route is saved or changes. Never raises: the web app works without Photon."""

import asyncio
import logging

from app.agent.trace import PlanTrace
from app.config import get_settings
from app.photon.client import get_sidecar
from app.photon.share import card_url, medic_url

logger = logging.getLogger(__name__)

SEND_TIMEOUT_S = 12


MAX_DIRECTIONS = 10  # a text message, not a manual: longer routes point to the link for the rest


def directions_text(steps: list[dict], total_seconds: float) -> str:
    """The router's own step texts, numbered. Never written by the model."""
    texts = [s["text"] for s in steps if s.get("text")]
    if not texts:
        return ""
    minutes, seconds = divmod(round(total_seconds), 60)
    when = f"{minutes} min {seconds} s" if minutes else f"{seconds} s"
    lines = [f"Directions (about {when}):"]
    lines += [f"{i}. {text}" for i, text in enumerate(texts[:MAX_DIRECTIONS], 1)]
    if len(texts) > MAX_DIRECTIONS:
        lines.append(f"({len(texts) - MAX_DIRECTIONS} more steps: open the link)")
    return "\n".join(lines)


async def crew_who_joined(db, incident_id: str) -> list[dict]:
    """Crew members who have texted the line, so that Photon lets us message them."""
    rows = await asyncio.to_thread(
        lambda: db.table("crew_threads").select("*").eq("incident_id", incident_id).execute()
    )
    return [r for r in rows.data if r.get("photon_space_id") and r.get("photon_user_id")]


async def notify_route(
    db, incident_id: str, briefing: str | None, only_handle: str | None = None
) -> None:
    """Send the briefing and the card link to the incident's crew (or to one member)."""
    if not get_settings().photon_enabled:
        return
    try:
        trace = await PlanTrace.resume(db, incident_id)
        members = await crew_who_joined(db, incident_id)
        if only_handle:
            members = [m for m in members if m["handle"] == only_handle]
        if not members:
            await trace.add(
                "crew", "No crew member has joined the chat yet, so the briefing was not texted", {}
            )
            return
        sidecar = get_sidecar()
        routes = await asyncio.to_thread(
            lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
        )
        latest = max(routes.data, key=lambda r: r["version"], default=None)
        version = latest["version"] if latest else None
        directions = (
            directions_text(latest.get("steps") or [], latest.get("total_seconds") or 0)
            if latest
            else ""
        )
        message = "\n\n".join(part for part in (briefing, directions) if part) or None
        url = medic_url(incident_id, version)
        image_url = card_url(incident_id, version)
        for member in members:
            try:
                await asyncio.wait_for(
                    sidecar.send(
                        incident_id=incident_id,
                        thread_id=member["photon_space_id"],
                        sender_id=member["photon_user_id"],
                        text=message,
                        url=url,
                        image_url=image_url,
                    ),
                    SEND_TIMEOUT_S,
                )
                await trace.add(
                    "crew", f"texted crew: {briefing}", {"to": member["handle"], "link": url}
                )
            except Exception as error:
                logger.exception("Could not text crew member %s", member["handle"])
                await trace.add(
                    "crew",
                    f"Could not text the crew ({type(error).__name__})",
                    {"to": member["handle"]},
                )
    except Exception:
        logger.exception("Crew notification failed for incident %s", incident_id)
