import asyncio
import logging
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from supabase import Client

from app.api.telemetry import EngineRegistry, get_registry, process_sample
from app.db import get_db
from app.device.translate import DeviceBatch, DeviceState, commands

logger = logging.getLogger(__name__)
router = APIRouter()


class _Device:
    def __init__(self, incident_id: str):
        self.incident_id = incident_id
        self.state = DeviceState()
        self.lock = asyncio.Lock()  # batches from one device are handled one at a time, in order


class DeviceRegistry:
    """Which incident each wearable belongs to, and its running totals.

    Links are saved in the `devices` table, so a server restart (Render sleeps) does not lose them;
    the running totals restart at zero, which the position engine treats like a wearable reboot.
    """

    def __init__(self) -> None:
        self._devices: dict[str, _Device] = {}

    async def link(self, device_id: str, incident_id: str, db) -> None:
        existing = await asyncio.to_thread(
            lambda: db.table("devices").select("*").eq("device_id", device_id).execute()
        )
        if existing.data:
            await asyncio.to_thread(
                lambda: (
                    db.table("devices")
                    .update({"incident_id": incident_id})
                    .eq("device_id", device_id)
                    .execute()
                )
            )
        else:
            await asyncio.to_thread(
                lambda: (
                    db.table("devices")
                    .insert({"device_id": device_id, "incident_id": incident_id})
                    .execute()
                )
            )
        self._devices[device_id] = _Device(incident_id)

    async def get(self, device_id: str, db) -> _Device | None:
        if device_id not in self._devices:
            rows = await asyncio.to_thread(
                lambda: db.table("devices").select("*").eq("device_id", device_id).execute()
            )
            if not rows.data:
                return None
            self._devices[device_id] = _Device(rows.data[0]["incident_id"])
        return self._devices[device_id]


@lru_cache
def get_devices() -> DeviceRegistry:
    return DeviceRegistry()


class LinkIn(BaseModel):
    incident_id: str


@router.put("/api/device/{device_id}/link")
async def link_device(
    device_id: str,
    body: LinkIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
) -> dict:
    if not await registry.knows(body.incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    await devices.link(device_id, body.incident_id, db)
    return {"ok": True, "incident_id": body.incident_id}


@router.post("/api/device/{device_id}/events")
async def device_events(
    device_id: str,
    batch: DeviceBatch,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
) -> dict:
    device = await devices.get(device_id, db)
    if device is None:
        raise HTTPException(status_code=404, detail="This device is not linked to an incident")
    async with device.lock:
        sample = device.state.apply(batch)
        for alert in batch.alerts():
            row = {
                "device_id": device_id,
                "incident_id": device.incident_id,
                "kind": alert.kind,
                "data": alert.data(),
            }
            try:
                await asyncio.to_thread(
                    lambda row=row: db.table("device_events").insert(row).execute()
                )
            except Exception:
                logger.exception("Could not save a %s alert", alert.kind)
        update = await process_sample(db, registry, device.incident_id, sample)
    return {
        "commands": commands(update),
        "incident_id": device.incident_id,
        "status": "no_route" if update is None else "tracking",
    }
