import asyncio
import logging
import time
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from app.agent.replan import replan
from app.config import get_settings
from app.db import get_db
from app.graph.schema import RouteStep
from app.models import Telemetry
from app.position.engine import PositionEngine, Update
from app.providers.snapshot import SnapshotProvider

logger = logging.getLogger(__name__)
router = APIRouter()


class _Tracked:
    def __init__(self, engine: PositionEngine, version: int):
        self.engine = engine
        self.version = version
        self.checked_at = time.monotonic()
        self.replanned_version: int | None = (
            None  # route version already re-planned for elevator_out
        )
        self.lock = asyncio.Lock()  # samples for one incident are handled one at a time, in order


class EngineRegistry:
    """One PositionEngine per incident, rebuilt whenever the incident gets a newer route version."""

    def __init__(self, stride_m: float, provider, recheck_s: float = 2.0):
        self.stride_m = stride_m
        self.provider = provider
        self.recheck_s = recheck_s  # how often to look for a newer route
        self._tracked: dict[str, _Tracked] = {}
        self._buildings: dict[str, str | None] = {}  # known incidents -> building_id
        self._lock = asyncio.Lock()

    async def knows(self, incident_id: str, db) -> bool:
        if incident_id in self._buildings:
            return True
        rows = await asyncio.to_thread(
            lambda: db.table("incidents").select("*").eq("id", incident_id).execute()
        )
        if not rows.data:
            return False
        self._buildings[incident_id] = rows.data[0].get("building_id")
        return True

    def building_of(self, incident_id: str) -> str | None:
        return self._buildings.get(incident_id)

    async def get(self, incident_id: str, db) -> _Tracked | None:
        """The engine for this incident's newest route, or None while it has no route yet."""
        async with self._lock:
            tracked = self._tracked.get(incident_id)
            if tracked and time.monotonic() - tracked.checked_at < self.recheck_s:
                return tracked
            route = await self._latest_route(incident_id, db)
            if route is None:
                return tracked
            if tracked and tracked.version == route["version"]:
                tracked.checked_at = time.monotonic()
                return tracked
            engine = PositionEngine(
                [RouteStep.model_validate(s) for s in route["steps"]],
                tag_nodes=await self._tag_nodes(incident_id, db),
                stride_m=self.stride_m,
            )
            self._tracked[incident_id] = tracked = _Tracked(engine, route["version"])
            return tracked

    async def _latest_route(self, incident_id: str, db) -> dict | None:
        rows = await asyncio.to_thread(
            lambda: db.table("routes").select("*").eq("incident_id", incident_id).execute()
        )
        return max(rows.data, key=lambda r: r["version"], default=None)

    async def _tag_nodes(self, incident_id: str, db) -> dict[str, str]:
        """RFID tag UID -> node id, from the building's routing graph."""
        building_id = self._buildings.get(incident_id)
        if not building_id:
            return {}
        try:
            graph = await self.provider.graph(building_id)
        except LookupError:
            return {}
        return {n["tag_id"]: n["id"] for n in graph["nodes"] if n.get("tag_id")}


@lru_cache
def get_registry() -> EngineRegistry:
    return EngineRegistry(stride_m=get_settings().stride_m, provider=SnapshotProvider())


async def _write(db, table: str, row: dict) -> None:
    try:
        await asyncio.to_thread(lambda: db.table(table).insert(row).execute())
    except Exception:
        logger.exception("Could not write a %s row", table)


async def _save(db, incident_id: str, version: int, update: Update) -> None:
    for cue in update.cues:
        row = {
            "incident_id": incident_id,
            "route_version": version,
            "cue": cue.cue,
            "dist_m": cue.dist_m,
            "text": cue.text,
        }
        await _write(db, "cues", row)
    if update.position:
        p = update.position
        row = {
            "incident_id": incident_id,
            "route_version": version,
            "step_index": p.step_index,
            "progress_m": p.progress_m,
            "floor": p.floor,
            "off_route": p.off_route,
        }
        await _write(db, "positions", row)
    if "arrived" in update.effects:
        try:
            await asyncio.to_thread(
                lambda: (
                    db.table("incidents")
                    .update({"status": "arrived"})
                    .eq("id", incident_id)
                    .execute()
                )
            )
        except Exception:
            logger.exception("Could not mark incident %s arrived", incident_id)


@router.post("/incidents/{incident_id}/telemetry")
async def telemetry(
    incident_id: str,
    sample: Telemetry,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
) -> dict:
    if not await registry.knows(incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    tracked = await registry.get(incident_id, db)
    if tracked is None:  # no route yet: nothing to follow
        return {"ok": True}
    async with tracked.lock:
        update = tracked.engine.update(sample)
        await _save(db, incident_id, tracked.version, update)
        # the button is held for several samples: re-plan once per route version
        building_id = registry.building_of(incident_id)
        if (
            "elevator_out" in update.effects
            and building_id
            and tracked.replanned_version != tracked.version
        ):
            tracked.replanned_version = tracked.version
            await replan(
                db,
                registry.provider,
                incident_id,
                building_id,
                "elevator_out",
                tracked.engine,
                None,
            )
    return {"ok": True}
