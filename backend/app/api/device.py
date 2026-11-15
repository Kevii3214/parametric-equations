import asyncio
import logging
import time
from collections import OrderedDict, deque
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from supabase import Client

from app.api.telemetry import EngineRegistry, get_registry, process_sample
from app.config import get_settings
from app.db import get_db
from app.device.signs import SignReader, match_sign
from app.device.translate import (
    MOVEMENT_TYPES,
    NOT_STORED,
    DeviceState,
    alert_changes,
    commands,
    event_key,
)

logger = logging.getLogger(__name__)
router = APIRouter()

SEEN_LIMIT = 5000  # event keys remembered per device, to recognise a re-send
TOUCH_EVERY_S = 10  # how often `last_seen_at` is written
SCAN_WITHIN_M = 10  # the camera starts reading door signs this close to the destination
AUTO_BIND_EVERY_S = 5  # how often the default wearable looks for a newer incident
SENSOR_FIELDS = ("imu", "baro", "air", "lcd", "led", "cam")
DONE_STATUSES = ("arrived", "closed", "cancelled")


class _Device:
    def __init__(self, incident_id: str | None, auto: bool = False):
        self.incident_id = incident_id
        self.auto = auto  # bound by itself (DEFAULT_DEVICE_ID), so a newer incident takes it over
        self.state = DeviceState()
        self.lock = asyncio.Lock()  # batches from one device are handled one at a time, in order
        self.queue: deque[str] = deque()  # commands waiting for the device's next request
        self.seen: OrderedDict[tuple, None] = OrderedDict()
        self.touched_at = 0.0
        self.scanning = False  # SCAN ON has been sent and SCAN OFF has not
        self.scan_done = False  # the crew arrived: no more scanning for this route
        self.auto_checked_at = 0.0

    def remember(self, key: tuple) -> bool:
        """True the first time this event is seen, False for a re-send."""
        if key in self.seen:
            return False
        self.seen[key] = None
        if len(self.seen) > SEEN_LIMIT:
            self.seen.popitem(last=False)
        return True

    def queue_once(self, command: str) -> None:
        if command not in self.queue:
            self.queue.append(command)

    def drain(self) -> list[str]:
        out = list(self.queue)
        self.queue.clear()
        return out


class DeviceRegistry:
    """Which incident each wearable belongs to, its running totals and the commands waiting for it.

    Links are saved in the `devices` table, so a server restart (Render sleeps) does not lose them;
    the running totals and the command queue restart empty, which the position engine treats like a
    wearable reboot.
    """

    def __init__(self) -> None:
        self._devices: dict[str, _Device] = {}

    async def link(self, device_id: str, incident_id: str, db, auto: bool = False) -> _Device:
        """Bind a wearable to an incident and tell it to zero its counters (RESET) at the route start."""
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
        device = self._devices.get(device_id) or _Device(incident_id)
        device.incident_id, device.auto = incident_id, auto
        device.state = DeviceState()
        device.scanning = device.scan_done = False
        device.queue_once("RESET")
        self._devices[device_id] = device
        return device

    async def get(self, device_id: str, db) -> _Device | None:
        """The device if it is bound to an incident (None if unknown or unbound)."""
        device = await self._load(device_id, db)
        return device if device.incident_id else None

    async def _load(self, device_id: str, db, default_id: str = "") -> _Device:
        if device_id in self._devices:
            return self._devices[device_id]
        rows = await asyncio.to_thread(
            lambda: db.table("devices").select("*").eq("device_id", device_id).execute()
        )
        incident_id = rows.data[0].get("incident_id") if rows.data else None
        device = _Device(incident_id, auto=device_id == default_id)
        # events saved before a restart, so a re-send of one of them is still recognised
        saved = await asyncio.to_thread(
            lambda: db.table("device_events").select("*").eq("device_id", device_id).execute()
        )
        for row in saved.data:
            ts = (row.get("data") or {}).get("ts")
            if ts is not None:
                device.remember(event_key(device_id, {"t": row.get("kind"), "ts": ts}))
        self._devices[device_id] = device
        return device

    async def resolve(self, device_id: str, db, default_id: str = "") -> _Device:
        """The device, following the newest active incident if it is the default wearable."""
        device = await self._load(device_id, db, default_id)
        now = time.monotonic()
        if (
            device_id == default_id
            and (device.auto or device.incident_id is None)
            and now - device.auto_checked_at >= AUTO_BIND_EVERY_S
        ):
            device.auto_checked_at = now
            newest = await _newest_active_incident(db)
            if newest and newest != device.incident_id:
                device = await self.link(device_id, newest, db, auto=True)
                device.auto_checked_at = now
        return device


async def _newest_active_incident(db) -> str | None:
    rows = await asyncio.to_thread(lambda: db.table("incidents").select("*").execute())
    active = [r for r in rows.data if r.get("status") not in DONE_STATUSES]
    newest = max(active, key=lambda r: r.get("created_at") or "", default=None)
    return newest["id"] if newest else None


@lru_cache
def get_devices() -> DeviceRegistry:
    return DeviceRegistry()


class LinkIn(BaseModel):
    incident_id: str


class BindIn(BaseModel):
    device_id: str


async def _bind(
    device_id: str, incident_id: str, db, registry: EngineRegistry, devices: DeviceRegistry
) -> dict:
    if not await registry.knows(incident_id, db):
        raise HTTPException(status_code=404, detail="Unknown incident")
    await devices.link(device_id, incident_id, db)
    return {"ok": True, "incident_id": incident_id, "device_id": device_id}


@router.put("/api/device/{device_id}/link")
async def link_device(
    device_id: str,
    body: LinkIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
) -> dict:
    return await _bind(device_id, body.incident_id, db, registry, devices)


@router.post("/incidents/{incident_id}/device")
async def bind_device(
    incident_id: str,
    body: BindIn,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
) -> dict:
    return await _bind(body.device_id, incident_id, db, registry, devices)


async def _read_events(request: Request) -> list[dict]:
    """The events in the body; anything that is not a list of objects is dropped, never an error."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001 - a bad body is an empty batch, never an error
        return []
    events = body.get("events") if isinstance(body, dict) else None
    if not isinstance(events, list):
        return []
    return [e for e in events if isinstance(e, dict) and isinstance(e.get("t"), str)]


async def _store(db, device_id: str, incident_id: str | None, events: list[dict]) -> None:
    for e in events:
        if e["t"] in NOT_STORED:
            continue
        row = {
            "device_id": device_id,
            "incident_id": incident_id,
            "kind": e["t"],
            "data": {k: v for k, v in e.items() if k != "t"},
        }
        try:
            await asyncio.to_thread(lambda row=row: db.table("device_events").insert(row).execute())
        except Exception:
            logger.exception("Could not save a %s event", e["t"])


async def _alerts(db, device_id: str, incident_id: str, events: list[dict]) -> None:
    """Open or clear the incident's fall and air alerts the web app shows as a banner."""
    for kind, active, detail in alert_changes(events):
        try:
            open_rows = await asyncio.to_thread(
                lambda kind=kind: (
                    db.table("alerts")
                    .select("*")
                    .eq("incident_id", incident_id)
                    .eq("kind", kind)
                    .eq("active", True)
                    .execute()
                )
            )
            if active and not open_rows.data:
                row = {
                    "incident_id": incident_id,
                    "device_id": device_id,
                    "kind": kind,
                    "active": True,
                    "detail": detail,
                }
                await asyncio.to_thread(lambda row=row: db.table("alerts").insert(row).execute())
            elif not active and open_rows.data:
                cleared = {"active": False, "cleared_at": datetime.now(UTC).isoformat()}
                await asyncio.to_thread(
                    lambda cleared=cleared, kind=kind: (
                        db.table("alerts")
                        .update(cleared)
                        .eq("incident_id", incident_id)
                        .eq("kind", kind)
                        .eq("active", True)
                        .execute()
                    )
                )
        except Exception:
            logger.exception("Could not save a %s alert", kind)


async def _touch(db, device_id: str, device: _Device, events: list[dict]) -> None:
    """Remember when the device was last heard from and what its `hello` said (best effort)."""
    hello = next((e for e in events if e["t"] == "hello"), None)
    now = time.monotonic()
    if hello is None and now - device.touched_at < TOUCH_EVERY_S:
        return
    device.touched_at = now
    values: dict = {"last_seen_at": datetime.now(UTC).isoformat()}
    if hello:
        values["fw"] = str(hello.get("fw", ""))
        values["sensors"] = {k: hello[k] for k in SENSOR_FIELDS if k in hello}
    try:
        await asyncio.to_thread(
            lambda: db.table("devices").update(values).eq("device_id", device_id).execute()
        )
    except Exception:  # noqa: BLE001 - best effort
        logger.warning("Could not update last_seen for %s (is migration 0005 applied?)", device_id)


@router.post("/api/device/{device_id}/events")
async def device_events(
    device_id: str,
    request: Request,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
) -> dict:
    """Take a batch of wearable events, return the commands waiting for it. Never an error status:
    the Pi would re-send a rejected batch for ever, so a problem is logged and the answer stays 200."""
    started = time.monotonic()
    settings = get_settings()
    events = await _read_events(request)
    if settings.device_key and request.headers.get("X-Device-Key") != settings.device_key:
        logger.warning("Device %s sent no valid X-Device-Key", device_id)
    out: list[str] = []
    incident_id, status = None, "unbound"
    try:
        device = await devices.resolve(device_id, db, settings.default_device_id)
        async with device.lock:
            fresh = [e for e in events if device.remember(event_key(device_id, e))]
            await _store(db, device_id, device.incident_id, fresh)
            await _touch(db, device_id, device, fresh)
            incident_id = device.incident_id
            if incident_id:
                await _alerts(db, device_id, incident_id, fresh)
                status = "no_route"
                sample = device.state.apply(
                    [e for e in fresh if e["t"] in MOVEMENT_TYPES + ("hello", "ack")]
                )
                if sample is not None:
                    update = await process_sample(db, registry, incident_id, sample)
                    out += commands(update)
                    status = "no_route" if update is None else "tracking"
                    await _scan_near_the_end(device, registry, db, update)
                    if "SCAN OFF" in out:
                        device.scanning, device.scan_done = False, True
            out = device.drain() + out
    except Exception:
        logger.exception("Device %s: could not handle a batch", device_id)
    logger.info(
        "device=%s events=%d commands=%d status=%s ms=%d",
        device_id,
        len(events),
        len(out),
        status,
        (time.monotonic() - started) * 1000,
    )
    return {"commands": out, "incident_id": incident_id, "status": status}


async def _scan_near_the_end(device: _Device, registry: EngineRegistry, db, update) -> None:
    """Turn the camera on (SCAN ON) once the destination is close, so it can read the door signs."""
    if (
        device.scanning
        or device.scan_done
        or update is None
        or update.position is None
        or update.position.off_route
    ):
        return
    tracked = await registry.get(device.incident_id, db)
    if tracked is None:
        return
    steps, i = tracked.engine.steps, update.position.step_index
    if i >= len(steps):
        return
    remaining = steps[i].meters - update.position.progress_m + sum(s.meters for s in steps[i + 1 :])
    if remaining <= SCAN_WITHIN_M:
        device.scanning = True
        device.queue_once("SCAN ON")


@lru_cache
def get_sign_reader() -> SignReader:
    return SignReader()


def _picture_and_fields(content_type: str, body: bytes) -> tuple[bytes | None, dict[str, str]]:
    """The JPEG and the text fields (ts, n, reason) of the Pi's multipart upload."""
    message = BytesParser(policy=email_policy).parsebytes(
        b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
    )
    image, fields = None, {}
    for part in message.iter_parts() if message.is_multipart() else []:
        name = part.get_param("name", header="content-disposition")
        payload = part.get_payload(decode=True) or b""
        if name == "image":
            image = payload
        elif name:
            fields[name] = payload.decode("utf-8", "replace")
    return image, fields


_background: set[asyncio.Task] = (
    set()
)  # tasks are kept here so they are not collected before they finish


async def _fix_from_sign(
    device_id, device, registry, db, reader, image: bytes, fields: dict[str, str]
) -> None:
    """Read the sign in the picture; if it names a point on the route, move the position there."""
    texts = await reader(image)  # the picture goes out of scope here and is never kept
    logger.info("device=%s photo sign text=%s", device_id, texts)
    if not texts or not device.incident_id:
        return
    tracked = await registry.get(device.incident_id, db)
    building_id = registry.building_of(device.incident_id)
    if tracked is None or not building_id:
        return
    graph = await registry.provider.graph(building_id)
    on_route = {s.from_node for s in tracked.engine.steps} | {
        s.to_node for s in tracked.engine.steps
    }
    node = match_sign(texts, [n for n in graph["nodes"] if n["id"] in on_route])
    await _store(
        db,
        device_id,
        device.incident_id,
        [{"t": "sign", "ts": int(float(fields.get("ts", 0) or 0)), "text": texts, "node": node}],
    )
    if node is None:
        return
    tag = f"SIGN:{node}"
    tracked.engine.tag_nodes[tag] = node
    async with device.lock:
        sample = device.state.snapshot(int(time.time() * 1000), tag)
        update = await process_sample(db, registry, device.incident_id, sample)
        for command in commands(update):
            device.queue_once(command)


@router.post("/api/device/{device_id}/photo")
async def device_photo(
    device_id: str,
    request: Request,
    db: Annotated[Client, Depends(get_db)],
    registry: Annotated[EngineRegistry, Depends(get_registry)],
    devices: Annotated[DeviceRegistry, Depends(get_devices)],
    reader: Annotated[SignReader, Depends(get_sign_reader)],
) -> dict:
    """Take a camera picture and answer at once; the sign is read in the background (a failed upload is not
    retried by the Pi). The picture is never stored."""
    out: list[str] = []
    try:
        device = await devices.resolve(device_id, db, get_settings().default_device_id)
        image, fields = _picture_and_fields(
            request.headers.get("content-type", ""), await request.body()
        )
        if image and device.incident_id:
            task = asyncio.create_task(
                _fix_from_sign(device_id, device, registry, db, reader, image, fields)
            )
            _background.add(task)
            task.add_done_callback(_background.discard)
        out = device.drain()
    except Exception:
        logger.exception("Device %s: could not handle a photo", device_id)
    return {"commands": out}
