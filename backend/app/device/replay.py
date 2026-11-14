"""Turn telemetry samples back into wearable events: for the fake device and for tests.

The reverse of translate.py. It lets a simulated walk (app/position/simulate.py) be sent through the
device endpoint exactly as the real Pi would send it.
"""

from collections.abc import Iterable, Iterator

from app.device.translate import PASCALS_PER_FLOOR, DeviceBatch, DeviceEvent
from app.position.engine import angle_diff

TURN_THRESHOLD_DEGREES = 60.0


def telemetry_to_batches(samples: Iterable[dict]) -> Iterator[DeviceBatch]:
    last_steps: int | None = None
    heading_ref: float | None = None
    pressure_ref: float | None = None
    for s in samples:
        events: list[DeviceEvent] = []
        if last_steps is not None and s["steps"] > last_steps:
            events.append(DeviceEvent(kind="steps", n=s["steps"] - last_steps))
        last_steps = s["steps"]

        if heading_ref is None:
            heading_ref = s["heading"]
        delta = angle_diff(s["heading"], heading_ref)
        if abs(delta) >= TURN_THRESHOLD_DEGREES:
            events.append(
                DeviceEvent(kind="turn", dir="R" if delta > 0 else "L", deg=round(abs(delta), 1))
            )
            heading_ref = s["heading"]

        if pressure_ref is None:
            pressure_ref = s["pressure"]
        change = s["pressure"] - pressure_ref
        if abs(change) >= PASCALS_PER_FLOOR * 0.75:  # a ride is slow: wait for most of a floor
            events.append(DeviceEvent(kind="floor", dir="up" if change < 0 else "down"))
            pressure_ref = s["pressure"]

        if s["btn"]:
            events.append(DeviceEvent(kind="button", n=s["btn"]))
        if s["tag"]:
            events.append(DeviceEvent(kind="tag", id=s["tag"]))
        yield DeviceBatch(t=s["t"], events=events)
