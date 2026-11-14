"""The Raspberry Pi wearable's language, turned into the telemetry the position engine already understands.

The Pi sends events ("3 steps", "turned left", "went up a floor") and wants short commands back ("CUE L").
Everything that depends on those names lives in this file, so a renamed field or command changes only here.
Pure: no I/O.
"""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models import Telemetry
from app.position.engine import Update

PASCALS_PER_FLOOR = 45.0  # climbing a floor lowers the pressure by about this much
DEFAULT_TURN_DEGREES = 90.0
START_PRESSURE = 100000.0

CUE_COMMANDS = {
    "LEFT": "CUE L",
    "RIGHT": "CUE R",
    "STRAIGHT": "CUE S",
    "UTURN": "CUE U",
    "FLOOR_UP": "CUE UP",
    "FLOOR_DOWN": "CUE DN",
    "ARRIVE": "CUE A",
    "OFF_ROUTE": "CUE X",
}

MOVEMENT_KINDS = ("steps", "turn", "floor", "button", "tag")
ALERT_KINDS = ("fall", "air")


class DeviceEvent(BaseModel):
    """One thing the wearable noticed. Which fields are needed depends on `kind`."""

    kind: Literal["steps", "turn", "floor", "button", "tag", "fall", "air"]
    n: int | None = Field(
        default=None, description="steps: how many. button: 1 confirm, 2 elevator out"
    )
    dir: str | None = Field(default=None, description="turn: L or R. floor: up or down")
    deg: float | None = Field(default=None, gt=0, le=360, description="turn: size, default 90")
    id: str | None = Field(default=None, description="tag: the RFID UID")
    level: str | None = Field(default=None, description="air: ok, warn or danger")
    ppm: float | None = Field(default=None, description="air: the reading")

    @model_validator(mode="after")
    def has_what_its_kind_needs(self) -> "DeviceEvent":
        if self.kind == "steps" and (self.n is None or self.n < 0):
            raise ValueError("steps needs n >= 0")
        if self.kind == "turn" and self.dir not in ("L", "R"):
            raise ValueError("turn needs dir L or R")
        if self.kind == "floor" and self.dir not in ("up", "down"):
            raise ValueError("floor needs dir up or down")
        if self.kind == "button" and self.n not in (1, 2):
            raise ValueError("button needs n 1 or 2")
        if self.kind == "tag" and not self.id:
            raise ValueError("tag needs id")
        return self

    def data(self) -> dict:
        """What is stored for an alert: every field except the kind."""
        return self.model_dump(exclude={"kind"}, exclude_none=True)


class DeviceBatch(BaseModel):
    """Body of POST /api/device/{id}/events: whatever happened since the last post (may be empty)."""

    t: int = Field(ge=0, description="Milliseconds since the wearable booted")
    events: list[DeviceEvent] = Field(default_factory=list)

    def alerts(self) -> list[DeviceEvent]:
        return [e for e in self.events if e.kind in ALERT_KINDS]


class DeviceState:
    """Running totals for one wearable. The Pi starts at heading 0 and floor 0 when it boots;
    the engine only looks at changes, so nothing needs lining up with the building."""

    def __init__(self) -> None:
        self.steps = 0
        self.heading = 0.0
        self.pressure = START_PRESSURE

    def apply(self, batch: DeviceBatch) -> Telemetry:
        btn, tag = 0, None
        for e in batch.events:
            if e.kind == "steps":
                self.steps += e.n or 0
            elif e.kind == "turn":
                turn = e.deg or DEFAULT_TURN_DEGREES
                self.heading = (self.heading + (turn if e.dir == "R" else -turn)) % 360
            elif e.kind == "floor":
                self.pressure += PASCALS_PER_FLOOR * (-1 if e.dir == "up" else 1)
            elif e.kind == "button":
                btn = max(btn, e.n or 0)  # elevator out (2) beats confirm (1)
            elif e.kind == "tag":
                tag = e.id
        return Telemetry(
            t=batch.t,
            steps=self.steps,
            heading=self.heading,
            pressure=self.pressure,
            btn=btn,
            tag=tag,
        )


def commands(update: Update | None) -> list[str]:
    """The commands to send back to the wearable for what the engine just decided."""
    if update is None:
        return []
    return [CUE_COMMANDS[c.cue] for c in update.cues]
