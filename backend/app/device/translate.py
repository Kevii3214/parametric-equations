"""The Raspberry Pi wearable's language, turned into the telemetry the position engine already understands.

The real protocol is in Hardware/BACKEND_BRIEF.md: the Pi posts `{"events": [{"t": "<type>", "ts": <epoch ms>, ...}]}`
and gets `{"commands": ["CUE L", ...]}` back. Everything that depends on those names lives in this file, so a
renamed field or command changes only here. Pure: no I/O.

Events are read loosely (plain dicts, never validated into errors): the Pi re-sends what the server did not
acknowledge, so one odd event must never turn into an error response.
"""

from app.models import Telemetry
from app.position.engine import Update

PASCALS_PER_FLOOR = (
    45.0  # the engine reads a floor change from pressure; the Pi reports whole floors
)
START_PRESSURE = 100000.0
TURN_DEGREES = (
    90.0  # a turn is counted as exactly this: the Pi's `deg` reads 20-30% low, `dir` is reliable
)
UTURN_DEGREES = 180.0
UTURN_FROM_DEG = 120.0  # a measured turn this big is a U-turn
TEXT_WIDTH = 16  # the Pi's display is 16 characters wide

CUE_COMMANDS = {
    "LEFT": ["CUE L"],
    "RIGHT": ["CUE R"],
    "STRAIGHT": ["CUE S"],
    "UTURN": ["CUE U"],
    "ARRIVE": ["ARRIVED", "SCAN OFF"],
    "OFF_ROUTE": ["WRONG"],
    "FLOOR_UP": [],  # the Pi has no floor command yet: the TXT line below is all it gets
    "FLOOR_DOWN": [],
}

# Events that move the position engine; the rest (hello, air, fall, photo, ack, ...) are only stored.
MOVEMENT_TYPES = ("state", "step", "turn", "floor", "btn")
NOT_STORED = ("state", "step")  # absolute readings sent twice a second: not worth a database row


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def event_key(device_id: str, event: dict) -> tuple[str, int, str]:
    """What identifies one event, so a re-send is recognised: the device, its timestamp and its type."""
    return device_id, int(_number(event.get("ts"))), str(event.get("t"))


class DeviceState:
    """Running totals for one wearable, built from its events.

    Heading is the sum of the turns the Pi reports, not its raw gyro angle: the engine needs "turned left",
    and the gyro under-reads corners. Floor is the Pi's relative floor plus what it had before the last
    boot or RESET, so a zeroed counter never looks like a trip down the stairs.
    """

    def __init__(self) -> None:
        self.steps = 0
        self.heading = 0.0
        self.floor = 0  # the Pi's own relative floor since its last boot or RESET
        self.floor_base = 0  # floors climbed before that

    @property
    def total_floor(self) -> int:
        return self.floor_base + self.floor

    def snapshot(self, ts: int, tag: str) -> Telemetry:
        """The current position as a sample that also carries a position fix (a sign read by the camera)."""
        return Telemetry(
            t=ts,
            steps=self.steps,
            heading=self.heading,
            pressure=START_PRESSURE - PASCALS_PER_FLOOR * self.total_floor,
            btn=0,
            tag=tag,
        )

    def apply(self, events: list[dict]) -> Telemetry | None:
        """One telemetry sample for these events, or None if none of them is about movement."""
        moved, btn, last_ts = False, 0, 0
        for e in sorted(events, key=lambda e: _number(e.get("ts"))):
            kind = e.get("t")
            last_ts = max(last_ts, int(_number(e.get("ts"))))
            if kind == "hello" or (kind == "ack" and str(e.get("cmd", "")).upper() == "RESET"):
                self.floor_base += self.floor  # the Pi just zeroed its counters
                self.floor = 0
                self.steps = 0
            elif kind == "step":
                self.steps, moved = int(_number(e.get("n"), self.steps)), True
            elif kind == "state":
                self.steps = int(_number(e.get("steps"), self.steps))
                self.floor = int(_number(e.get("fl"), self.floor))
                moved = True
            elif kind == "floor":
                self.floor, moved = int(_number(e.get("fl"), self.floor)), True
            elif kind == "turn":
                size = abs(_number(e.get("deg"), TURN_DEGREES))
                turn = UTURN_DEGREES if size >= UTURN_FROM_DEG else TURN_DEGREES
                self.heading = (self.heading + (turn if e.get("dir") == "R" else -turn)) % 360
                moved = True
            elif kind == "btn":
                # elevator out (2) beats confirm (1)
                btn, moved = max(btn, 2 if e.get("ev") == "elevator_out" else 1), True
        if not moved:
            return None
        return Telemetry(
            t=last_ts,
            steps=self.steps,
            heading=self.heading,
            pressure=START_PRESSURE - PASCALS_PER_FLOOR * self.total_floor,
            btn=btn,
            tag=None,
        )


def commands(update: Update | None) -> list[str]:
    """The commands to send back to the wearable for what the engine just decided."""
    if update is None:
        return []
    out: list[str] = []
    for cue in update.cues:
        out += CUE_COMMANDS.get(cue.cue, [])
        out.append(f"TXT {cue.text[:TEXT_WIDTH]}")
    return out


def alert_changes(events: list[dict]) -> list[tuple[str, bool, dict]]:
    """Safety alerts to open or clear, as (kind, active, detail), in time order.

    A `fall` opens a fall alert, `fall_cancel` (button 1 within 15 s) clears it; `air` with warn 1 opens an
    air alert and warn 0 clears it.
    """
    changes: list[tuple[str, bool, dict]] = []
    for e in sorted(events, key=lambda e: _number(e.get("ts"))):
        kind = e.get("t")
        if kind == "fall":
            changes.append(("fall", True, {}))
        elif kind == "fall_cancel":
            changes.append(("fall", False, {}))
        elif kind == "air":
            detail = {"v": e["v"]} if "v" in e else {}
            changes.append(("air", bool(_number(e.get("warn"))), detail))
    return changes
