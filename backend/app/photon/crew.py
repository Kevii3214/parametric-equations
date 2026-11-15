"""What happens when the crew texts back.

The text is labelled by Gemini (classify.py); every action after that is deterministic: a blocker or a new
destination waits for a YES, then goes through the existing re-plan code, where the router picks the path.
Every inbound and outbound line is written to plan_steps (kind "crew") so the dispatcher sees it.
"""

import asyncio
import logging
import re

from app.agent.replan import replan, replan_to_place
from app.agent.trace import PlanTrace
from app.graph.schema import BuildingGraph
from app.notes import save_note
from app.photon.classify import CrewReport, is_no, is_yes
from app.photon.notify import notify_route

logger = logging.getLogger(__name__)

NOT_ASSIGNED = {"ignored": True, "reason": "not assigned to this incident", "replies": []}


async def _rows(db, table: str, **match) -> list[dict]:
    def run():
        query = db.table(table).select("*")
        for column, value in match.items():
            query = query.eq(column, value)
        return query.execute().data

    return await asyncio.to_thread(run)


async def _set_pending(db, member: dict, pending: dict | None) -> None:
    member["pending"] = pending
    await asyncio.to_thread(
        lambda: (
            db.table("crew_threads")
            .update({"pending": pending})
            .eq("incident_id", member["incident_id"])
            .eq("handle", member["handle"])
            .execute()
        )
    )


# "directions", "send the route again", "where do I go": a plain keyword, so no model call and no waiting
RESEND = re.compile(
    r"^\W*(directions?|route|resend|repeat|again|help|where( do i go)?|which way|"
    r"(send|give)( me)?( the)? (route|directions?)( again)?)\W*$",
    re.IGNORECASE,
)


def is_resend(text: str) -> bool:
    return bool(RESEND.match(text))


FILLER = {"the", "a", "an", "in", "on", "at", "to", "into"}


def find_places(graph: BuildingGraph, text: str) -> list:
    """The map nodes the crew might mean, found by label.

    An exact label wins. Otherwise every label containing the words; if none does, trailing words are dropped one
    at a time, but never below two words ("conference room on 18" becomes "conference room"; "the roof" stays
    "roof" and matches nothing). Plain string matching, no model."""
    words = text.strip().lower().split()
    while words and words[0] in FILLER:
        words.pop(0)
    if not words:
        return []
    labelled = [n for n in graph.nodes if n.label and n.kind != "entrance"]
    exact = [n for n in labelled if n.label.lower() == " ".join(words)]
    if len(exact) == 1:
        return exact
    for count in range(len(words), min(len(words), 2) - 1, -1):
        phrase = " ".join(words[:count])
        found = [n for n in labelled if phrase in n.label.lower()]
        if found:
            return found
    return []


async def handle_crew_report(
    db, provider, registry, classify, embed, incident_id: str, text: str, sender: str, channel: str
) -> dict:
    """Returns {"category": ..., "replies": [...]} (or "ignored": True). The caller texts the replies back."""
    incidents = await _rows(db, "incidents", id=incident_id)
    members = [
        m for m in await _rows(db, "crew_threads", incident_id=incident_id) if m["handle"] == sender
    ]
    if not incidents or not members:
        return dict(NOT_ASSIGNED)
    incident, member = incidents[0], members[0]
    if incident.get("status") == "arrived":
        return {"ignored": True, "reason": "incident is not active", "replies": []}

    trace = await PlanTrace.resume(db, incident_id)
    await trace.add("crew", f"crew texted: {text}", {"from": sender, "channel": channel})

    async def say(*replies: str) -> list[str]:
        for reply in replies:
            await trace.add("crew", f"texted crew: {reply}", {"to": sender, "channel": channel})
        return list(replies)

    if is_resend(text):  # send the route (picture, briefing, directions, link) to this person again
        rows = await _rows(db, "routes", incident_id=incident_id)
        latest = max(rows, key=lambda r: r["version"], default=None)
        if latest is None:
            return {
                "category": "resend",
                "replies": await say("There is no route yet. I will text it as soon as there is."),
            }
        await notify_route(db, incident_id, latest.get("briefing"), only_handle=sender)
        return {"category": "resend", "replies": []}

    pending = member.get("pending")
    if pending and is_yes(text):
        await _set_pending(db, member, None)
        return {
            "category": "confirmed",
            "replies": await say(await _confirm(db, provider, registry, incident, pending, text)),
        }
    if pending and is_no(text):
        await _set_pending(db, member, None)
        return {"category": "cancelled", "replies": await say("OK, the route stays as it is.")}

    report: CrewReport | None = await classify(text)
    if report is None:
        logger.warning("Could not classify a crew text for incident %s", incident_id)
        return {"category": "unclassified", "replies": []}
    building_id = incident.get("building_id")

    if report.category == "chatter":
        return {"category": "chatter", "replies": []}

    if report.category == "crew_tip":
        if not building_id:
            return {"category": "crew_tip", "replies": await say("Thanks, noted.")}
        try:
            await save_note(db, embed, building_id, text.strip())
        except Exception:
            logger.exception("Could not save a crew tip for incident %s", incident_id)
            return {
                "category": "crew_tip",
                "replies": await say("Thanks, but I could not save that tip."),
            }
        return {"category": "crew_tip", "replies": await say("Thanks, saved for the next crew.")}

    if report.category == "blocker":
        kind = "elevator_out" if report.elevator or "elevator" in text.lower() else "obstacle"
        what = report.summary or text.strip()
        await _set_pending(db, member, {"type": "replan", "kind": kind, "text": text.strip()})
        return {
            "category": "blocker",
            "replies": await say(f"Re-routing around {what}. Reply YES to confirm."),
        }

    # destination_change: find the place on the building's map in code, never by the model
    place = report.place or ""
    found: list = []
    if building_id:
        try:
            found = find_places(
                BuildingGraph.model_validate(await provider.graph(building_id)), place
            )
        except LookupError:
            found = []
    if len(found) != 1:
        if len(found) > 1:
            options = "; ".join(n.label for n in found[:4])
            reply = f"Which one: {options}? Text the exact name and the route stays as it is until then."
        else:
            reply = f'I couldn\'t find "{place or "that place"}" on the building map, so the route stays as it is.'
        return {"category": "destination_change", "replies": await say(reply)}
    node = found[0]
    await _set_pending(
        db, member, {"type": "destination", "goal_node": node.id, "label": node.label}
    )
    return {
        "category": "destination_change",
        "replies": await say(f"Change the destination to {node.label}? Reply YES to confirm."),
    }


async def _confirm(db, provider, registry, incident: dict, pending: dict, text: str) -> str:
    """Run the confirmed change through the re-plan code. The new briefing and link are texted by that code."""
    incident_id, building_id = incident["id"], incident.get("building_id")
    tracked = await registry.get(incident_id, db)
    if tracked is None or not building_id:
        return "There is no route yet to change."
    async with tracked.lock:
        if pending["type"] == "destination":
            result = await replan_to_place(
                db,
                provider,
                incident_id,
                building_id,
                pending["goal_node"],
                pending["label"],
                tracked.engine,
            )
        else:
            result = await replan(
                db,
                provider,
                incident_id,
                building_id,
                pending["kind"],
                tracked.engine,
                pending.get("text"),
            )
    if result["replanned"]:
        return "Re-routing now."
    return "I could not find another way, so the route stays as it is."
