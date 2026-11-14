import asyncio
import logging
import re

from langchain_core.tools import tool

from app.graph.router import NoRouteError, find_route
from app.graph.schema import BuildingGraph

logger = logging.getLogger(__name__)

FLOOR_BASIS = "suite number (CoStar's own floor names are unreliable)"


def make_plan_tool():
    @tool
    def make_plan(steps: list[str]) -> str:
        """Write down your plan as a short list of steps. Call this first, before anything else."""
        return "Plan recorded. Carry it out now."

    return make_plan


def make_records_tools(provider, db, incident_id: str) -> list:
    """The CoStar building-data tools the records subagent uses. Problems come back as {"error": ...}
    so the agent can react, instead of raising."""

    @tool
    async def resolve_building(address: str) -> dict:
        """Find the building id for a street address, for example '1415 Louisiana St'."""
        try:
            building_id = await provider.resolve(address)
        except LookupError as error:
            return {"error": str(error)}
        try:  # saved by this code, not by the model, so it cannot be mangled
            await asyncio.to_thread(
                lambda: (
                    db.table("incidents")
                    .update({"building_id": building_id})
                    .eq("id", incident_id)
                    .execute()
                )
            )
        except Exception:
            logger.exception("Could not save building_id on incident %s", incident_id)
        return {"building_id": building_id}

    @tool
    async def get_building_record(building_id: str) -> dict:
        """Get the facts about a building: name, floors, elevators, parking and data-quality warnings."""
        try:
            record = await provider.record(building_id)
        except LookupError as error:
            return {"error": str(error)}
        return {
            "building_id": building_id,
            "name": record.get("name"),
            "address": f"{record.get('address')}, {record.get('city')}, {record.get('state')}",
            "property_type": record.get("property_type"),
            "stories_above_grade": record.get("stories_above_grade"),
            "typical_floor_sqft": record.get("typical_floor_sqft"),
            "elevators": record.get("elevators"),
            "parking": record.get("parking"),
            "scan_count": len(record.get("matterport_model_ids") or []),
            "tenant_count": len(record.get("current_tenants") or []),
            "data_quality_notes": record.get("data_quality_notes"),
        }

    @tool
    async def find_suite(building_id: str, suite: str) -> dict:
        """Find who is in a suite and which floor it is on, from the suite number."""
        try:
            record = await provider.record(building_id)
        except LookupError as error:
            return {"error": str(error)}
        number = re.sub(r"(?i)^\s*(suite|ste|unit|#)\s*", "", suite).strip()
        tenant = next(
            (
                t["company"]
                for t in record.get("current_tenants") or []
                if (t.get("suite") or "").strip() == number
            ),
            None,
        )
        floor = int(number) // 100 if re.fullmatch(r"\d{3,4}", number) else None
        return {"suite": number, "tenant": tenant, "floor_guess": floor, "floor_basis": FLOOR_BASIS}

    return [resolve_building, get_building_record, find_suite]


MAX_BRIEFING = 600


def make_route_tools(provider, db, incident_id: str) -> list:
    """Tools for finding and saving the route. The router picks the path: the model only chooses between
    router results and writes a briefing, and it can never supply route steps itself."""

    async def closed_for_this_incident() -> list[str]:
        rows = await asyncio.to_thread(
            lambda: db.table("closures").select("*").eq("incident_id", incident_id).execute()
        )
        return [r["node_or_edge"] for r in rows.data]

    async def load_graph(building_id: str) -> BuildingGraph:
        return BuildingGraph.model_validate(await provider.graph(building_id))

    async def compute(building_id: str, start_node: str, goal_node: str):
        """(steps, None) on success, (None, {"error": ...}) when the router cannot give a route."""
        try:
            graph = await load_graph(building_id)
            return find_route(graph, start_node, goal_node, await closed_for_this_incident()), None
        except (LookupError, NoRouteError) as error:
            return None, {"error": str(error)}

    @tool
    async def list_entrances(building_id: str) -> dict:
        """List the ways into the building (entrances) that the router can start a route from."""
        try:
            graph = await load_graph(building_id)
        except LookupError as error:
            return {"error": str(error)}
        return {
            "entrances": [
                {"node_id": n.id, "label": n.label, "floor": n.floor}
                for n in graph.nodes
                if n.kind == "entrance"
            ]
        }

    @tool
    async def find_destination_nodes(building_id: str, text: str) -> dict:
        """Find places in the building's indoor map whose label contains the text, such as a suite number
        or 'phone room'. Use it to pick the goal node for the patient."""
        try:
            graph = await load_graph(building_id)
        except LookupError as error:
            return {"error": str(error)}
        wanted = text.strip().lower()
        return {
            "nodes": [
                {"node_id": n.id, "label": n.label, "floor": n.floor, "kind": n.kind}
                for n in graph.nodes
                if n.label and wanted in n.label.lower()
            ]
        }

    @tool
    async def plan_route(building_id: str, start_node: str, goal_node: str) -> dict:
        """Ask the router for the fastest stretcher-safe route between two nodes. Nothing is saved, so you can
        compare several entrances. Places closed for this incident are avoided automatically."""
        steps, error = await compute(building_id, start_node, goal_node)
        if error:
            return error
        return {
            "start_node": start_node,
            "goal_node": goal_node,
            "total_seconds": round(sum(s.seconds for s in steps)),
            "steps": [s.model_dump() for s in steps],
        }

    @tool
    async def choose_route(
        building_id: str, start_node: str, goal_node: str, briefing: str
    ) -> dict:
        """Save the route you picked as the incident's route. The router's steps for these two nodes are
        stored; you only add a short briefing for the crew (two or three plain sentences)."""
        steps, error = await compute(building_id, start_node, goal_node)
        if error:
            return error
        try:
            existing = await asyncio.to_thread(
                lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
            )
            version = max((r["version"] for r in existing.data), default=0) + 1
            row = {
                "incident_id": incident_id,
                "version": version,
                "entrance_node": start_node,
                "steps": [s.model_dump() for s in steps],
                "total_seconds": round(sum(s.seconds for s in steps)),
                "briefing": briefing.strip()[:MAX_BRIEFING],
            }
            await asyncio.to_thread(lambda: db.table("routes").insert(row).execute())
            await asyncio.to_thread(
                lambda: (
                    db.table("incidents")
                    .update({"status": "en_route"})
                    .eq("id", incident_id)
                    .execute()
                )
            )
        except Exception:
            logger.exception("Could not save the route for incident %s", incident_id)
            return {"error": "Could not save the route"}
        return {
            "route_version": version,
            "total_seconds": row["total_seconds"],
            "step_count": len(steps),
        }

    return [list_entrances, find_destination_nodes, plan_route, choose_route]
