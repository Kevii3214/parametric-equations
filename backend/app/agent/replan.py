"""Re-plan a route after "elevator out" or an obstacle.

This is deliberately not left to the language model: it closes the blocked part of the building, asks the
router (never the LLM) for a new path from where the crew is, saves it as the next route version and
writes a `replan` step to the trace.
"""

import asyncio
import logging

from app.agent.trace import PlanTrace
from app.briefing import HARD_LIMIT_WORDS, clip_words, spoken_briefing
from app.graph.router import NoRouteError, find_route
from app.graph.schema import BuildingGraph, RouteStep

logger = logging.getLogger(__name__)

REASONS = {"elevator_out": "Elevator out", "obstacle": "Obstacle reported"}


async def _notify(db, incident_id: str, briefing: str) -> None:
    """Text the crew the new briefing (a no-op unless PHOTON_ENABLED). Never raises."""
    from app.photon.notify import notify_route  # imported here to keep this module free of cycles

    await notify_route(db, incident_id, briefing)


def _edge_kind(graph: BuildingGraph, a: str, b: str) -> str | None:
    return next((e.kind for e in graph.edges if e.from_node == a and e.to_node == b), None)


def pick_closure(graph: BuildingGraph, steps: list[RouteStep], index: int, kind: str) -> str | None:
    """The edge to close: the next elevator ride ahead (elevator_out) or the walk being made (obstacle)."""
    if kind == "obstacle":
        step = steps[index]
        return f"{step.from_node}->{step.to_node}"
    for step in steps[index:]:
        if _edge_kind(graph, step.from_node, step.to_node) == "elevator":
            return f"{step.from_node}->{step.to_node}"
    return None


async def replan(
    db, provider, incident_id: str, building_id: str, kind: str, engine, detail_text: str | None
) -> dict:
    """Returns {"replanned": bool, "version": int | None}. Never raises: problems go in the trace."""
    trace = await PlanTrace.resume(db, incident_id)
    reason = REASONS[kind] + (f" ({detail_text})" if detail_text else "")
    try:
        rows = await asyncio.to_thread(
            lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
        )
        route = max(rows.data, key=lambda r: r["version"])
        steps = [RouteStep.model_validate(s) for s in route["steps"]]
        graph = BuildingGraph.model_validate(await provider.graph(building_id))
        index = min(engine.step_index, len(steps) - 1) if engine else 0
        start = steps[index].from_node
        goal = steps[-1].to_node

        closure = pick_closure(graph, steps, index, kind)
        if closure is None:
            await trace.add(
                "replan",
                f"{reason}: the route has no elevator ride ahead, so it was left as it is",
                {"kind": kind, "route_version": route["version"]},
            )
            return {"replanned": False, "version": None}
        await asyncio.to_thread(
            lambda: (
                db.table("closures")
                .insert({"incident_id": incident_id, "node_or_edge": closure, "reason": reason})
                .execute()
            )
        )
        closed = await asyncio.to_thread(
            lambda: db.table("closures").select("*").eq("incident_id", incident_id).execute()
        )
        try:
            new_steps = find_route(graph, start, goal, [c["node_or_edge"] for c in closed.data])
        except NoRouteError:
            await trace.add(
                "replan",
                f"{reason}: closed {closure}, but no route is left from {start} to {goal}",
                {"kind": kind, "closed": closure, "from_node": start, "goal_node": goal},
            )
            return {"replanned": False, "version": None}

        version = route["version"] + 1
        seconds = round(sum(s.seconds for s in new_steps))
        row = {
            "incident_id": incident_id,
            "version": version,
            "entrance_node": start,
            "steps": [s.model_dump() for s in new_steps],
            "total_seconds": seconds,
            "briefing": clip_words(
                f"Re-routed, {REASONS[kind].lower()}. {spoken_briefing(graph, new_steps)}",
                HARD_LIMIT_WORDS,
            ),
        }
        await asyncio.to_thread(lambda: db.table("routes").insert(row).execute())
        await _notify(db, incident_id, row["briefing"])
        await trace.add(
            "replan",
            f"{reason}: closed {closure}, new route v{version} from {start} "
            f"({seconds} s, was {route.get('total_seconds')} s)",
            {
                "kind": kind,
                "closed": closure,
                "from_node": start,
                "route_version": version,
                "total_seconds": seconds,
            },
        )
        return {"replanned": True, "version": version}
    except Exception as error:
        logger.exception("Re-plan failed for incident %s", incident_id)
        await trace.add("replan", f"{reason}: re-plan failed ({type(error).__name__})", {})
        return {"replanned": False, "version": None}


async def replan_to_place(
    db, provider, incident_id: str, building_id: str, goal_node: str, label: str, engine
) -> dict:
    """The patient is somewhere else: route from where the crew is to the new goal. The router picks the path.

    Returns {"replanned": bool, "version": int | None}. Never raises: problems go in the trace.
    """
    trace = await PlanTrace.resume(db, incident_id)
    reason = f"Destination changed to {label}"
    try:
        rows = await asyncio.to_thread(
            lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
        )
        route = max(rows.data, key=lambda r: r["version"])
        steps = [RouteStep.model_validate(s) for s in route["steps"]]
        graph = BuildingGraph.model_validate(await provider.graph(building_id))
        index = min(engine.step_index, len(steps) - 1) if engine else 0
        start = steps[index].from_node
        closed = await asyncio.to_thread(
            lambda: db.table("closures").select("*").eq("incident_id", incident_id).execute()
        )
        try:
            new_steps = find_route(
                graph, start, goal_node, [c["node_or_edge"] for c in closed.data]
            )
        except NoRouteError:
            await trace.add(
                "replan",
                f"{reason}: no route from {start} to {goal_node}",
                {"from_node": start, "goal_node": goal_node},
            )
            return {"replanned": False, "version": None}
        version = route["version"] + 1
        seconds = round(sum(s.seconds for s in new_steps))
        row = {
            "incident_id": incident_id,
            "version": version,
            "entrance_node": start,
            "steps": [s.model_dump() for s in new_steps],
            "total_seconds": seconds,
            "briefing": clip_words(
                f"New destination, {label}. {spoken_briefing(graph, new_steps)}", HARD_LIMIT_WORDS
            ),
        }
        await asyncio.to_thread(lambda: db.table("routes").insert(row).execute())
        await _notify(db, incident_id, row["briefing"])
        await trace.add(
            "replan",
            f"{reason}: new route v{version} from {start} ({seconds} s, was {route.get('total_seconds')} s)",
            {"goal_node": goal_node, "route_version": version, "total_seconds": seconds},
        )
        return {"replanned": True, "version": version}
    except Exception as error:
        logger.exception("Destination re-plan failed for incident %s", incident_id)
        await trace.add("replan", f"{reason}: re-plan failed ({type(error).__name__})", {})
        return {"replanned": False, "version": None}
