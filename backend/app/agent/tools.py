import asyncio
import logging
import re

from langchain_core.tools import tool

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
