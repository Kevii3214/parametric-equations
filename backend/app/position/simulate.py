"""A pretend wearable: walks a route and yields telemetry samples, for testing and for demos.

Used by tools/mock_wearable.py to move the dot on the web app without the real hardware.
"""

import math
from collections.abc import Iterator

from app.graph.schema import RouteStep

TURN_DEGREES = {"LEFT": -90.0, "RIGHT": 90.0, "UTURN": 180.0}
STANDING_TICKS = 5  # waiting for the lift
RIDE_TICKS = 10  # the lift ride, as the pressure changes
FINAL_TICKS = 3


def simulate(
    steps: list[RouteStep],
    *,
    stride_m: float = 0.7,
    speed_mps: float = 1.3,
    start_steps: int = 1000,
    start_heading: float = 90.0,
    base_pressure: float = 100000.0,
    pascals_per_floor: float = 45.0,
    tags_at: dict[str, str] | None = None,
    tick_ms: int = 200,
) -> Iterator[dict]:
    """Yield one telemetry dict per tick as a paramedic walks the whole route.

    tags_at maps a node id to the RFID tag UID to scan when reaching it (the start node included).
    """
    tags_at = tags_at or {}
    t = 0
    counter = float(start_steps)  # fractional steps; the wearable reports whole ones
    heading = start_heading
    pressure = base_pressure
    pending_tag = tags_at.get(steps[0].from_node)
    floor = steps[0].floor

    def sample(btn: int = 0) -> dict:
        nonlocal t, pending_tag
        t += tick_ms
        tag, pending_tag = pending_tag, None
        return {
            "t": t,
            "steps": math.ceil(counter - 1e-9),
            "heading": heading % 360,
            "pressure": round(pressure, 1),
            "btn": btn,
            "tag": tag,
        }

    yield sample()  # standing at the start
    for i, step in enumerate(steps):
        if step.floor != floor:  # lift or stairs: stand, then ride
            for _ in range(STANDING_TICKS):
                yield sample()
            drop = (step.floor - floor) * pascals_per_floor  # climbing lowers the pressure
            for _ in range(RIDE_TICKS):
                pressure -= drop / RIDE_TICKS
                yield sample()
            floor = step.floor
        else:
            ticks = max(1, math.ceil(step.meters / (speed_mps * tick_ms / 1000)))
            for _ in range(ticks):
                counter += step.meters / stride_m / ticks
                yield sample()
        pending_tag = tags_at.get(step.to_node)
        if i < len(steps) - 1 and step.cue in TURN_DEGREES:
            heading += TURN_DEGREES[step.cue]  # the turn, made at the corner
            yield sample()
    for _ in range(FINAL_TICKS):
        yield sample()
