"""Turn telemetry samples into the events the real wearable sends: for the fake device and for tests.

The reverse of translate.py. It lets a simulated walk (app/position/simulate.py) be sent through the
device endpoint as the real Pi would send it: headings and floors relative to where it started, a `turn`
when the heading changes by 60 degrees, a `floor` when the pressure shows a floor, `state` every tick.
"""

from collections.abc import Iterable, Iterator

from app.device.translate import PASCALS_PER_FLOOR
from app.position.engine import angle_diff

TURN_THRESHOLD_DEGREES = 60.0
STRIDE_M = 0.7
EPOCH_MS = 1_700_000_000_000  # the Pi's clock is epoch milliseconds


def telemetry_to_batches(samples: Iterable[dict], start_ts: int = EPOCH_MS) -> Iterator[list[dict]]:
    """One list of device events per telemetry sample; the first list starts with `hello`."""
    first_steps: int | None = None
    heading_ref = first_heading = pressure_ref = None
    floor, last_steps = 0, 0
    for s in samples:
        ts = start_ts + s["t"]
        events: list[dict] = []
        if first_steps is None:
            first_steps, first_heading = s["steps"], s["heading"]
            events.append({"t": "hello", "ts": ts, "fw": "mock-device", "imu": 1, "baro": 1})
        steps = s["steps"] - first_steps
        hd = round((s["heading"] - first_heading) % 360, 1)
        if steps > last_steps:
            events.append(
                {"t": "step", "ts": ts, "n": steps, "d": round(steps * STRIDE_M, 1), "hd": hd}
            )
            last_steps = steps

        if heading_ref is None:
            heading_ref = s["heading"]
        delta = angle_diff(s["heading"], heading_ref)
        if abs(delta) >= TURN_THRESHOLD_DEGREES:
            events.append(
                {"t": "turn", "ts": ts, "dir": "R" if delta > 0 else "L", "deg": round(delta)}
            )
            heading_ref = s["heading"]

        if pressure_ref is None:
            pressure_ref = s["pressure"]
        change = s["pressure"] - pressure_ref
        if abs(change) >= PASCALS_PER_FLOOR * 0.75:  # a ride is slow: wait for most of a floor
            floor += 1 if change < 0 else -1
            events.append({"t": "floor", "ts": ts, "fl": floor, "alt": round(floor * 3.5, 1)})
            pressure_ref = s["pressure"]

        if s["btn"]:
            events.append(
                {
                    "t": "btn",
                    "ts": ts,
                    "id": s["btn"],
                    "ev": "elevator_out" if s["btn"] == 2 else "confirm",
                }
            )
        events.append(
            {
                "t": "state",
                "ts": ts,
                "steps": steps,
                "d": round(steps * STRIDE_M, 1),
                "hd": hd,
                "fl": floor,
            }
        )
        yield events
