from pathlib import Path

import pytest

from app.graph.router import find_route
from app.graph.schema import BuildingGraph
from app.models import Telemetry
from app.position.engine import PositionEngine

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
START = 1000  # the wearable's step counter does not start at zero
BASE_PRESSURE = 100000.0

# Route n1 -> n10 on the hand-made fixture graph (stride 1.0 m, so steps = metres):
#   0 STRAIGHT 6 m | 1 LEFT 6 m | 2 STRAIGHT 9 m | 3 FLOOR_UP (lift) | 4 RIGHT 11 m | 5 LEFT 18 m | 6 ARRIVE 8 m
# Headings: east 90 on steps 0-1, north 0 after the left turn, east 90 after the right turn, north 0 again.


@pytest.fixture(scope="module")
def graph():
    return BuildingGraph.model_validate_json(
        (FIXTURES / "building_graph.json").read_text(encoding="utf-8")
    )


@pytest.fixture
def route(graph):
    return find_route(graph, "n1", "n10")


@pytest.fixture
def engine(route):
    tags = {"TAG-ENTRANCE-01": "n1", "TAG-SUITE-1420": "n10", "TAG-N2": "n2", "TAG-N12": "n12"}
    return PositionEngine(route, tag_nodes=tags, stride_m=1.0)


def sample(t, steps, heading=90.0, pressure=BASE_PRESSURE, btn=0, tag=None):
    return Telemetry(t=t, steps=steps, heading=heading, pressure=pressure, btn=btn, tag=tag)


class Walker:
    """Feeds a route to an engine one sample at a time and collects everything it writes."""

    def __init__(self, engine):
        self.engine = engine
        self.t, self.steps, self.heading, self.pressure = 0, START, 90.0, BASE_PRESSURE
        self.cues, self.positions, self.effects = [], [], []

    def feed(self, walk_m=0, heading=None, pressure=None, btn=0, tag=None):
        self.t += 200
        self.steps += walk_m
        self.heading = self.heading if heading is None else heading
        self.pressure = self.pressure if pressure is None else pressure
        update = self.engine.update(
            sample(self.t, self.steps, self.heading, self.pressure, btn, tag)
        )
        self.cues += update.cues
        self.effects += update.effects
        if update.position:
            self.positions.append(update.position)
        return update

    def walk(self, metres, heading=None):
        for _ in range(int(metres)):
            self.feed(1, heading)


@pytest.fixture
def walker(engine):
    w = Walker(engine)
    w.feed()  # the first sample sets the starting point
    return w


# ------------------------------------------------------------------ starting


def test_first_sample_is_the_start_whatever_the_step_counter_says(walker):
    assert walker.engine.step_index == 0 and walker.engine.progress_m == 0
    assert walker.engine.floor == 1 and not walker.engine.off_route


def test_walking_advances_progress_using_the_stride(route):
    engine = PositionEngine(route, tag_nodes={}, stride_m=0.7)
    w = Walker(engine)
    w.feed()
    w.feed(10)  # 10 steps of 0.7 m
    assert engine.progress_m == pytest.approx(1.0)  # 7.0 m walked, 6 m of step 0 already used
    assert engine.step_index == 1


def test_step_counter_going_backwards_restarts_the_count(walker):
    walker.walk(3)
    walker.steps = 5  # the wearable rebooted
    walker.feed()
    assert walker.engine.progress_m == 0 and walker.engine.step_index == 0


# --------------------------------------------------------------------- cues


def test_no_cue_for_a_straight_walk_with_nothing_special_ahead(walker):
    walker.walk(5)
    assert walker.cues == []


def test_turn_cue_is_written_once_within_six_metres_of_the_turn(walker):
    walker.walk(6)  # step 0 done; step 1 (LEFT) is 6 m long, so its cue is due straight away
    assert [(c.cue, c.dist_m) for c in walker.cues] == [("LEFT", 6)]
    assert walker.cues[0].text == "LEFT in 6 m"
    walker.walk(4, heading=90)
    assert len(walker.cues) == 1  # never repeated for the same step


def test_the_cue_for_a_lift_is_given_while_approaching_it(walker):
    walker.walk(12)  # to the corner
    walker.feed(0, heading=0)  # turn left
    walker.walk(4)  # within 6 m of the end of step 2 (9 m)
    assert [c.cue for c in walker.cues] == ["LEFT", "FLOOR_UP"]
    assert walker.cues[-1].dist_m <= 6


# -------------------------------------------------------------------- turns


def test_a_left_turn_is_confirmed_by_a_heading_change_of_about_ninety_degrees(walker):
    walker.walk(12)
    walker.feed(0, heading=0)  # turned left
    walker.walk(2)
    assert walker.engine.step_index == 2 and not walker.engine.off_route
    assert walker.engine.progress_m == pytest.approx(2)


def test_small_heading_drift_does_not_cause_off_route(walker):
    walker.walk(6, heading=110)
    walker.walk(6, heading=70)
    assert not walker.engine.off_route


def test_turning_the_wrong_way_is_off_route(walker):
    walker.walk(12)
    walker.feed(0, heading=180)  # turned right when LEFT was expected
    assert walker.engine.off_route
    assert walker.cues[-1].cue == "OFF_ROUTE"


def test_walking_more_than_five_metres_past_the_turn_is_off_route(walker):
    walker.walk(12)
    walker.walk(5)  # exactly 5 m past: not yet
    assert not walker.engine.off_route
    walker.walk(1)
    assert walker.engine.off_route


def test_off_route_cue_is_written_only_once(walker):
    walker.walk(12)
    walker.walk(10)
    assert [c.cue for c in walker.cues].count("OFF_ROUTE") == 1


# ------------------------------------------------------------------- floors


def reach_the_lift(w):
    w.walk(12)
    w.feed(0, heading=0)
    w.walk(9)


def test_walking_around_at_the_lift_does_not_move_the_route_on(walker):
    reach_the_lift(walker)
    walker.walk(8)
    assert walker.engine.step_index == 3  # still waiting for the lift


@pytest.mark.parametrize("change", [45.0, 120.0, -50.0])
def test_a_pressure_change_of_35_pascals_or_more_confirms_the_floor_change(walker, change):
    reach_the_lift(walker)
    walker.feed(0, pressure=BASE_PRESSURE - change)
    assert walker.engine.floor == 14 and walker.engine.step_index == 4


def test_a_small_pressure_change_does_not_count(walker):
    reach_the_lift(walker)
    walker.feed(0, pressure=BASE_PRESSURE - 20)
    assert walker.engine.floor == 1 and walker.engine.step_index == 3


def test_the_confirm_button_at_the_lift_also_confirms_the_floor_change(walker):
    reach_the_lift(walker)
    walker.feed(0, btn=1)
    assert walker.engine.floor == 14 and walker.engine.step_index == 4


def test_the_confirm_button_does_nothing_away_from_the_lift(walker):
    walker.walk(2)
    walker.feed(0, btn=1)
    assert walker.engine.floor == 1 and walker.engine.step_index == 0


def test_slow_weather_drift_is_not_mistaken_for_a_floor_change(walker):
    for i in range(30):
        walker.feed(0, pressure=BASE_PRESSURE - i * 2)  # 58 Pa over six seconds of standing still
    assert walker.engine.floor == 1


# ----------------------------------------------------------------- RFID tags


def test_a_tag_snaps_the_position_to_its_node_and_clears_off_route(walker):
    walker.walk(12)
    walker.walk(8)
    assert walker.engine.off_route
    walker.feed(0, heading=0, tag="TAG-N2")  # n2 is where step 1 ends
    assert not walker.engine.off_route
    assert walker.engine.step_index == 2 and walker.engine.progress_m == 0


def test_a_tag_resets_the_heading_baseline(walker):
    walker.walk(3)
    walker.feed(0, heading=200, tag="TAG-ENTRANCE-01")  # the gyro drifted; re-zero here
    walker.walk(6, heading=200)
    assert not walker.engine.off_route and walker.engine.step_index == 1


def test_an_unknown_tag_is_ignored(walker):
    walker.walk(2)
    walker.feed(0, tag="TAG-SOMETHING-ELSE")
    assert walker.engine.step_index == 0 and walker.engine.progress_m == 2


def test_a_tag_on_a_node_that_is_not_on_the_route_means_off_route(route):
    engine = PositionEngine(route, tag_nodes={"TAG-X": "n4"}, stride_m=1.0)
    w = Walker(engine)
    w.feed()
    w.feed(0, tag="TAG-X")
    assert engine.off_route and w.cues[-1].cue == "OFF_ROUTE"


def test_the_suite_tag_means_arrived(walker):
    walker.feed(0, tag="TAG-SUITE-1420")
    assert walker.engine.arrived and "arrived" in walker.effects


# ------------------------------------------------------- buttons and arrival


def test_button_two_raises_elevator_out(walker):
    walker.feed(0, btn=2)
    assert "elevator_out" in walker.effects


def test_walking_the_whole_route_gives_each_cue_once_in_order_and_arrives(walker):
    walker.walk(12)
    walker.feed(0, heading=0)
    walker.walk(9)
    walker.feed(0, pressure=BASE_PRESSURE - 800)  # the lift ride
    walker.walk(11, heading=0)
    walker.feed(0, heading=90)  # turn right
    walker.walk(18, heading=90)
    walker.feed(0, heading=0)  # turn left
    walker.walk(8, heading=0)
    assert [c.cue for c in walker.cues] == ["LEFT", "FLOOR_UP", "RIGHT", "LEFT", "ARRIVE"]
    assert all(c.dist_m <= 6 for c in walker.cues)
    assert walker.engine.arrived and walker.engine.floor == 14 and not walker.engine.off_route
    assert "arrived" in walker.effects


# ---------------------------------------------------------- position output


def test_positions_are_written_at_most_once_a_second(walker):
    walker.walk(40)  # 40 samples, 200 ms apart: 8 seconds
    assert 7 <= len(walker.positions) <= 9


def test_a_position_row_describes_where_the_crew_is(walker):
    walker.walk(8)
    walker.t += 1000
    update = walker.engine.update(sample(walker.t, walker.steps))
    position = update.position
    assert (position.step_index, position.floor, position.off_route) == (1, 1, False)
    assert position.progress_m == pytest.approx(2)  # 8 m walked, 6 m of step 0 used


def test_scanning_a_tag_at_the_spot_you_are_already_at_does_not_repeat_the_cue(walker):
    walker.walk(6)  # the end of step 0 = the node n12; step 1's LEFT cue is written on arrival
    assert [c.cue for c in walker.cues] == ["LEFT"]
    walker.feed(0, tag="TAG-N12")
    walker.walk(2)
    assert [c.cue for c in walker.cues] == ["LEFT"]
    assert walker.engine.step_index == 1


def test_scanning_a_tag_further_back_lets_the_cues_fire_again(walker):
    walker.walk(12)  # at the corner: the LEFT cue has been given
    walker.feed(
        0, tag="TAG-N12"
    )  # a tag at the start of that step: the crew is back at the start of it
    assert [c.cue for c in walker.cues].count(
        "LEFT"
    ) == 1  # no new cue while still at the same step
    walker.feed(0, tag="TAG-ENTRANCE-01")  # right back to the start of the route
    walker.walk(6)
    assert [c.cue for c in walker.cues].count("LEFT") == 2  # the cue is due again


def walk_all_but_the_last_metres(w, last_leg):
    w.walk(12)
    w.feed(0, heading=0)
    w.walk(9)
    w.feed(0, pressure=BASE_PRESSURE - 800)
    w.walk(11, heading=0)
    w.feed(0, heading=90)
    w.walk(18, heading=90)
    w.feed(0, heading=0)
    w.walk(last_leg, heading=0)


def test_arrival_is_declared_within_a_metre_of_the_end_because_strides_vary(walker):
    walk_all_but_the_last_metres(walker, 7)  # the last step is 8 m: 1 m short is close enough
    assert walker.engine.arrived and "arrived" in walker.effects


def test_more_than_a_metre_short_is_not_yet_arrived(walker):
    walk_all_but_the_last_metres(walker, 6)
    assert not walker.engine.arrived


def test_skip_floor_at_the_lift_moves_on_like_the_confirm_button(walker):
    reach_the_lift(walker)
    update = walker.engine.skip_floor()
    assert walker.engine.floor == 14 and walker.engine.step_index == 4
    assert update.position is not None


def test_skip_floor_does_nothing_away_from_the_lift_or_before_any_sample(walker, route):
    walker.walk(2)
    walker.engine.skip_floor()
    assert walker.engine.floor == 1 and walker.engine.step_index == 0
    fresh = PositionEngine(route, tag_nodes={}, stride_m=0.7)
    fresh.skip_floor()  # no wearable sample yet: must not crash
    assert fresh.step_index == 0


# ------------------------------------------------------------ recovering from off route


def test_undoing_a_wrong_turn_brings_the_crew_back_on_route(walker):
    walker.walk(12)
    walker.feed(0, heading=180)  # turned right when LEFT was expected
    assert walker.engine.off_route
    walker.feed(0, heading=100)  # turned back, within 30 degrees of the original heading
    assert not walker.engine.off_route and "recovered" in walker.effects
    assert walker.positions[-1].off_route is False


def test_making_the_missed_turn_late_brings_the_crew_back_on_route(walker):
    walker.walk(12)
    walker.walk(6)  # six metres past the corner: off route
    assert walker.engine.off_route
    walker.feed(0, heading=0)  # the LEFT turn, made late
    assert not walker.engine.off_route and walker.engine.step_index == 2


def test_walking_on_the_wrong_way_stays_off_route(walker):
    walker.walk(12)
    walker.feed(0, heading=180)
    walker.walk(10, heading=180)
    assert walker.engine.off_route


def test_after_recovering_the_route_carries_on_and_reaches_the_lift(walker):
    walker.walk(12)
    walker.feed(0, heading=180)
    walker.feed(0, heading=90)
    walker.walk(1)
    walker.feed(0, heading=0)  # the real left turn
    walker.walk(9)
    assert walker.engine.step_index >= 2 and not walker.engine.off_route


def test_the_confirm_button_while_off_route_rejoins_from_the_start_of_the_step(walker):
    walker.walk(12)
    walker.walk(10)
    assert walker.engine.off_route
    walker.feed(0, btn=1)
    assert not walker.engine.off_route and "rejoined" in walker.effects
    assert walker.engine.progress_m == 0.0


def test_rejoin_does_nothing_when_on_route(walker):
    walker.walk(2)
    walker.engine.rejoin()
    assert walker.engine.step_index == 0 and not walker.engine.off_route
