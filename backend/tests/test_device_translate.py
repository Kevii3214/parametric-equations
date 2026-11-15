from app.device.replay import telemetry_to_batches
from app.device.translate import (
    PASCALS_PER_FLOOR,
    START_PRESSURE,
    DeviceState,
    alert_changes,
    commands,
    event_key,
)
from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.position.engine import Cue, PositionEngine, Update
from app.position.simulate import simulate
from tests.test_telemetry_api import DEMO


def test_events_that_are_not_about_movement_make_no_sample():
    events = [{"t": "air", "ts": 1, "v": 900, "warn": 1}, {"t": "fall", "ts": 2}, {"t": "dance"}]
    assert DeviceState().apply(events) is None


def test_state_and_step_events_set_the_step_count():
    state = DeviceState()
    sample = state.apply([{"t": "state", "ts": 500, "steps": 4, "fl": 0, "hd": 10}])
    assert (sample.t, sample.steps, sample.btn) == (500, 4, 0)
    assert state.apply([{"t": "step", "ts": 700, "n": 7}]).steps == 7


def test_events_are_read_in_time_order_whatever_order_they_arrive_in():
    events = [{"t": "step", "ts": 900, "n": 9}, {"t": "step", "ts": 100, "n": 1}]
    assert DeviceState().apply(events).steps == 9


def test_a_turn_counts_as_ninety_degrees_by_direction_even_when_the_pi_reads_low():
    state = DeviceState()
    assert state.apply([{"t": "turn", "ts": 1, "dir": "R", "deg": 64}]).heading == 90
    assert state.apply([{"t": "turn", "ts": 2, "dir": "L", "deg": -66}]).heading == 0
    assert state.apply([{"t": "turn", "ts": 3, "dir": "L", "deg": -140}]).heading == 180


def test_a_floor_becomes_a_pressure_change_the_engine_can_read():
    state = DeviceState()
    top = state.apply([{"t": "state", "ts": 1, "steps": 0, "fl": 0}])
    up = state.apply([{"t": "floor", "ts": 2, "fl": 1, "alt": 3.5}])
    assert top.pressure == START_PRESSURE
    assert up.pressure == START_PRESSURE - PASCALS_PER_FLOOR


def test_a_reset_does_not_look_like_a_trip_down_the_stairs():
    state = DeviceState()
    state.apply([{"t": "state", "ts": 1, "steps": 20, "fl": 2}])
    after = state.apply(
        [{"t": "ack", "ts": 2, "cmd": "RESET"}, {"t": "state", "ts": 3, "steps": 0, "fl": 0}]
    )
    assert after.pressure == START_PRESSURE - 2 * PASCALS_PER_FLOOR  # still two floors up
    assert after.steps == 0


def test_elevator_out_beats_confirm_in_one_batch():
    both = [
        {"t": "btn", "ts": 1, "id": 1, "ev": "confirm"},
        {"t": "btn", "ts": 2, "id": 2, "ev": "elevator_out"},
    ]
    assert DeviceState().apply(both).btn == 2
    assert DeviceState().apply(both[:1]).btn == 1


def test_an_event_is_identified_by_device_time_and_type():
    assert event_key("w", {"t": "step", "ts": 5}) == event_key("w", {"t": "step", "ts": 5.0})
    assert event_key("w", {"t": "step", "ts": 5}) != event_key("w", {"t": "turn", "ts": 5})


def test_no_update_means_no_commands():
    assert commands(None) == []


def test_cues_become_the_wearables_commands_each_with_a_short_text():
    update = Update(
        cues=[
            Cue("LEFT", 6.0, "Turn left at the door in 6 m please"),
            Cue("ARRIVE", 0.0, "Here"),
            Cue("OFF_ROUTE", 0.0, "Wrong way"),
            Cue("FLOOR_UP", 0.0, "Floor up"),
        ]
    )
    assert commands(update) == [
        "CUE L",
        "TXT Turn left at the",
        "ARRIVED",
        "SCAN OFF",
        "TXT Here",
        "WRONG",
        "TXT Wrong way",
        "FLOOR U",
        "TXT Floor up",
    ]


def test_the_simulated_walk_speaks_the_real_protocol_and_the_engine_follows_it():
    graph = BuildingGraph.model_validate_json(DEMO.read_text(encoding="utf-8"))
    route = find_route(graph, "st_main", "phone_door")
    batches = list(telemetry_to_batches(simulate(route)))
    assert batches[0][0]["t"] == "hello"
    assert {e["t"] for b in batches for e in b} >= {"hello", "state", "step", "turn", "floor"}
    assert all(isinstance(e["ts"], int) for b in batches for e in b)

    state, engine, cues = DeviceState(), PositionEngine(route, tag_nodes={}, stride_m=0.7), []
    for batch in batches:
        sample = state.apply(batch)
        if sample:
            cues += [c.cue for c in engine.update(sample).cues]
    assert engine.arrived
    assert cues[-1] == "ARRIVE" and "FLOOR_UP" in cues and ({"LEFT", "RIGHT"} & set(cues))


def test_alert_changes_in_time_order():
    events = [
        {"t": "fall_cancel", "ts": 3},
        {"t": "fall", "ts": 1},
        {"t": "air", "ts": 2, "v": 3000, "warn": 1},
        {"t": "air", "ts": 4, "warn": 0},
        {"t": "step", "ts": 5, "n": 1},
    ]
    assert alert_changes(events) == [
        ("fall", True, {}),
        ("air", True, {"v": 3000}),
        ("fall", False, {}),
        ("air", False, {}),
    ]
