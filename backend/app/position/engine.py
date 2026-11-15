"""Where is the crew on the route, and what should the wearable tell them? A pure state machine.

One PositionEngine follows one route for one incident. Feed it telemetry samples; it returns the cues to
send and a position row. It does no I/O, so every rule here is unit tested.
"""

from dataclasses import dataclass, field

from app.graph.schema import RouteStep
from app.models import Telemetry

CUE_DISTANCE_M = 6.0  # write a turn cue once the turn is this close
ARRIVAL_TOLERANCE_M = 1.0  # strides vary, so the last step counts as done this close to its end
OVERSHOOT_M = 5.0  # walking this far past a turn without turning means off route
TURN_DEGREES = 60.0  # a heading change this big, in the expected direction, confirms a turn
UTURN_DEGREES = 150.0
FLOOR_PASCALS = 35.0  # about one floor of pressure change
POSITION_INTERVAL_MS = 1000  # at most one positions row per second
PRESSURE_SMOOTHING = 0.1

TURN_DIRECTION = {"LEFT": -1, "RIGHT": 1, "UTURN": 0}


@dataclass
class Cue:
    cue: str
    dist_m: float
    text: str


@dataclass
class Position:
    step_index: int
    progress_m: float
    floor: int
    off_route: bool


@dataclass
class Update:
    cues: list[Cue] = field(default_factory=list)
    position: Position | None = None
    effects: list[str] = field(
        default_factory=list
    )  # "arrived", "elevator_out", "snapped:<node>", ...


def angle_diff(now: float, before: float) -> float:
    """Signed heading change in degrees, -180 up to 180 (positive = clockwise = right)."""
    return (now - before + 540) % 360 - 180


class PositionEngine:
    def __init__(self, steps: list[RouteStep], tag_nodes: dict[str, str], stride_m: float):
        self.steps = list(steps)
        self.tag_nodes = tag_nodes
        self.stride_m = stride_m
        self.step_index = 0
        self.progress_m = 0.0  # metres along the current step
        self.floor = self.steps[0].floor
        self.off_route = False
        self.arrived = False
        self._origin: float | None = None  # step counter value at the start of the current step
        self._last_steps = 0
        self._cued: set[int] = set()
        self._heading_ref: float | None = None  # heading when the current turn cue was written
        self._pressure_ref: float | None = None
        self._last_position_t: int | None = None
        self._last_sample: Telemetry | None = None

    @property
    def current_node(self) -> str:
        """The last route node the crew has reached (where a re-plan starts from)."""
        return self.steps[self.step_index].from_node

    # ------------------------------------------------------------------ public

    def update(self, sample: Telemetry) -> Update:
        self._last_sample = sample
        cues: list[Cue] = []
        effects: list[str] = []
        if (
            self._origin is None or sample.steps < self._last_steps
        ):  # first sample, or the wearable rebooted
            self._origin = sample.steps
        self._last_steps = sample.steps
        if self._pressure_ref is None:
            self._pressure_ref = sample.pressure

        if sample.btn == 2:
            effects.append("elevator_out")
        if sample.tag:
            self._snap_to_tag(sample, cues, effects)
        if not self.arrived and not self.off_route:
            self._advance(sample, cues, effects)
        return Update(cues=cues, position=self._position_row(sample.t), effects=effects)

    def skip_floor(self) -> Update:
        """Demo bypass: count the lift or stairs ride the crew is waiting at as done, as if they pressed confirm.

        Does nothing unless the engine is waiting at a floor change. It reuses the same code as the confirm
        button, fed with the last sample the wearable sent, so heading and step counts stay in step.
        """
        last = self._last_sample or Telemetry(
            t=0, steps=0, heading=0.0, pressure=100000.0, btn=0, tag=None
        )
        return self.update(
            last.model_copy(update={"btn": 1, "tag": None, "t": last.t + POSITION_INTERVAL_MS})
        )

    # ----------------------------------------------------------------- walking

    def _advance(self, s: Telemetry, cues: list[Cue], effects: list[str]) -> None:
        for _ in range(len(self.steps) + 1):  # one sample may cross several short steps
            i = self.step_index
            step = self.steps[i]
            if self._is_floor_change(i):
                self._wait_for_floor_change(s, i, cues, effects)
                if self.step_index == i or self.arrived:
                    return
                continue

            self._pressure_ref += PRESSURE_SMOOTHING * (s.pressure - self._pressure_ref)
            self.progress_m = (s.steps - self._origin) * self.stride_m
            remaining = step.meters - self.progress_m
            if i not in self._cued and remaining <= CUE_DISTANCE_M:
                self._write_cue(i, max(remaining, 0.0), s, cues)
            last = i == len(self.steps) - 1
            if remaining > (ARRIVAL_TOLERANCE_M if last else 0):
                return

            if last:
                self._arrive(s, cues, effects)
                return
            if step.cue in TURN_DIRECTION:
                if not self._turn_taken(s, step.cue, -remaining, cues):
                    return
                self._start_step(i + 1, s.steps - (-remaining) / self.stride_m)
            else:  # a straight step: carry on into the next one
                self._start_step(i + 1, s.steps - (-remaining) / self.stride_m)

    def _turn_taken(self, s: Telemetry, cue: str, overshoot: float, cues: list[Cue]) -> bool:
        """True once the heading shows the turn was made. Flags off route for a wrong turn or a missed one."""
        if self._heading_ref is None:
            self._heading_ref = s.heading
        delta = angle_diff(s.heading, self._heading_ref)
        direction = TURN_DIRECTION[cue]
        if direction == 0:  # U-turn: any way round
            confirmed, wrong = abs(delta) >= UTURN_DEGREES, False
        else:
            confirmed, wrong = delta * direction >= TURN_DEGREES, delta * direction <= -TURN_DEGREES
        if wrong or (not confirmed and overshoot > OVERSHOOT_M):
            self._go_off_route(cues)
            return False
        return confirmed

    def _start_step(self, index: int, origin: float) -> None:
        self.step_index = index
        self._origin = origin
        self._heading_ref = None

    # ------------------------------------------------------------------ floors

    def _is_floor_change(self, i: int) -> bool:
        return i > 0 and self.steps[i].floor != self.steps[i - 1].floor

    def _wait_for_floor_change(
        self, s: Telemetry, i: int, cues: list[Cue], effects: list[str]
    ) -> None:
        """At a lift or stairs: walking does not move the route on, only a floor change does."""
        self.progress_m = 0.0
        if i not in self._cued:
            self._write_cue(i, 0.0, s, cues)
        if abs(s.pressure - self._pressure_ref) >= FLOOR_PASCALS or s.btn == 1:
            self.floor = self.steps[i].floor
            self._pressure_ref = s.pressure
            if i == len(self.steps) - 1:
                self._arrive(s, cues, effects)
            else:
                self._start_step(i + 1, s.steps)

    # -------------------------------------------------------------------- cues

    def _cue_for(self, i: int) -> str | None:
        """What to tell the crew as step i nears its end: its own turn, or the lift that follows it."""
        step = self.steps[i]
        if step.cue != "STRAIGHT":
            return step.cue
        following = i + 1
        if following < len(self.steps) and self._is_floor_change(following):
            self._cued.add(following)  # the lift cue is given now, not again when we get there
            return self.steps[following].cue
        return None

    def _write_cue(self, i: int, dist: float, s: Telemetry, cues: list[Cue]) -> None:
        self._cued.add(i)
        cue = self._cue_for(i)
        if cue is None:
            return
        metres = round(dist)
        cues.append(Cue(cue, metres, f"{cue} in {metres} m"))
        if cue in TURN_DIRECTION:
            self._heading_ref = s.heading

    def _go_off_route(self, cues: list[Cue]) -> None:
        if not self.off_route:
            self.off_route = True
            cues.append(Cue("OFF_ROUTE", 0, "OFF_ROUTE: you have left the route"))

    def _arrive(self, s: Telemetry, cues: list[Cue], effects: list[str]) -> None:
        last = len(self.steps) - 1
        self.step_index = last
        self.progress_m = self.steps[last].meters
        self.floor = self.steps[last].floor
        if last not in self._cued:
            self._write_cue(last, 0.0, s, cues)
        self.arrived = True
        effects.append("arrived")

    # -------------------------------------------------------------- RFID tags

    def _snap_to_tag(self, s: Telemetry, cues: list[Cue], effects: list[str]) -> None:
        node = self.tag_nodes.get(s.tag)
        if node is None:
            return  # not one of ours
        index = self._index_after(node)
        if index is None:  # a real node, but not on this route
            self._go_off_route(cues)
            effects.append(f"off_route_tag:{node}")
            return
        self.off_route = False
        self._origin = s.steps
        self._heading_ref = s.heading  # the gyroscope drifts; count turns from this heading now
        self._pressure_ref = s.pressure
        if index != self.step_index:  # moved to a different step: its cues are due again
            self._cued = {k for k in self._cued if k < index}
        effects.append(f"snapped:{node}")
        if index >= len(self.steps):
            self._arrive(s, cues, effects)
            return
        self.arrived = False
        self.step_index = index
        self.progress_m = 0.0
        self.floor = self.steps[index - 1].floor if index > 0 else self.steps[0].floor

    def _index_after(self, node: str) -> int | None:
        """Index of the step that starts at this node, or None when the node is not on the route."""
        if node == self.steps[0].from_node:
            return 0
        for i, step in enumerate(self.steps):
            if step.to_node == node:
                return i + 1
        return None

    # ---------------------------------------------------------------- positions

    def _position_row(self, t: int) -> Position | None:
        if self._last_position_t is not None and t - self._last_position_t < POSITION_INTERVAL_MS:
            return None
        self._last_position_t = t
        return Position(self.step_index, round(self.progress_m, 2), self.floor, self.off_route)
