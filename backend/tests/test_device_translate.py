import pytest
from pydantic import ValidationError

from app.device.replay import telemetry_to_batches
from app.device.translate import (
    CUE_COMMANDS,
    PASCALS_PER_FLOOR,
    DeviceBatch,
    DeviceState,
    commands,
)
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.models import Telemetry
from app.position.engine import Cue, Update
from app.position.simulate import simulate
from tests.test_telemetry_api import DEMO


def batch(*events, t=0):
    return DeviceBatch.model_validate({"t": t, "events": list(events)})


def test_an_empty_batch_is_a_sample_with_nothing_new():
    sample = DeviceState().apply(batch(t=500))
    assert sample == Telemetry(t=500, steps=0, heading=0, pressure=100000, btn=0, tag=None)


def test_steps_accumulate_across_batches():
    state = DeviceState()
    state.apply(batch({"kind": "steps", "n": 3}))
    assert state.apply(batch({"kind": "steps", "n": 4}, {"kind": "steps", "n": 1})).steps == 8


def test_turns_change_the_heading_right_is_clockwise_and_it_wraps():
    state = DeviceState()
    assert state.apply(batch({"kind": "turn", "dir": "R"})).heading == 90
    both_left = batch({"kind": "turn", "dir": "L"}, {"kind": "turn", "dir": "L"})
    assert state.apply(both_left).heading == 270
    assert state.apply(batch({"kind": "turn", "dir": "R", "deg": 45})).heading == 315


def test_floor_events_move_the_pressure_by_one_floor():
    state = DeviceState()
    up = state.apply(batch({"kind": "floor", "dir": "up"}))
    assert up.pressure == 100000 - PASCALS_PER_FLOOR
    down = state.apply(batch({"kind": "floor", "dir": "down"}, {"kind": "floor", "dir": "down"}))
    assert down.pressure == 100000 + PASCALS_PER_FLOOR


def test_buttons_and_tags_apply_to_that_sample_only_and_elevator_out_wins():
    state = DeviceState()
    sample = state.apply(
        batch({"kind": "button", "n": 1}, {"kind": "button", "n": 2}, {"kind": "tag", "id": "T1"})
    )
    assert (sample.btn, sample.tag) == (2, "T1")
    later = state.apply(batch())
    assert (later.btn, later.tag) == (0, None)


def test_falls_and_air_warnings_do_not_touch_the_position():
    state = DeviceState()
    alerts = batch({"kind": "fall"}, {"kind": "air", "level": "warn", "ppm": 900})
    sample = state.apply(alerts)
    assert (sample.steps, sample.heading, sample.pressure) == (0, 0, 100000)
    assert [e.kind for e in alerts.alerts()] == ["fall", "air"]


@pytest.mark.parametrize(
    "event",
    [
        {"kind": "steps"},  # needs n
        {"kind": "steps", "n": -1},
        {"kind": "turn", "dir": "X"},
        {"kind": "floor"},
        {"kind": "button", "n": 3},
        {"kind": "tag"},
        {"kind": "dance"},
    ],
)
def test_bad_events_are_rejected(event):
    with pytest.raises(ValidationError):
        batch(event)


def test_every_cue_has_a_command():
    assert CUE_COMMANDS == {
        "LEFT": "CUE L",
        "RIGHT": "CUE R",
        "STRAIGHT": "CUE S",
        "UTURN": "CUE U",
        "FLOOR_UP": "CUE UP",
        "FLOOR_DOWN": "CUE DN",
        "ARRIVE": "CUE A",
        "OFF_ROUTE": "CUE X",
    }
    update = Update(cues=[Cue("LEFT", 5, "LEFT in 5 m"), Cue("OFF_ROUTE", 0, "x")])
    assert commands(update) == ["CUE L", "CUE X"]
    assert commands(None) == []


def test_replaying_the_demo_route_as_events_uses_every_kind_of_movement_event():
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    steps = find_route(graph, "st_main", "phone_door")
    batches = list(telemetry_to_batches(simulate(steps)))
    kinds = {e.kind for b in batches for e in b.events}
    assert {"steps", "turn", "floor"} <= kinds
