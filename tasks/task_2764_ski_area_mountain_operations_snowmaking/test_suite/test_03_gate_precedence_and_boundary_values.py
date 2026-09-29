"""Which gate speaks first, and where the numeric edges of the mountain fall.

A single mountain-operations request routinely breaks more than one rule at
once: a snowmaking plan can name a trail that patrol has just pulled offline
*and* ask for more water than the season's withdrawal right still holds, and an
overnight cat pass can be both out of sequence on its route and double-booked
onto a machine that is already out. The order in which the gates are tested is
part of the contract, so these tests build requests that violate two rules
together and pin the code the mountain is required to report — each paired with
a control that reaches the later rule on its own.

The same file pins the exact edges of two measured quantities: the wet-bulb
temperature at which the guns are still allowed to run, and the two-day
lookback that decides which snow stake readings still count toward a trail's
settled base.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import factories as payloads
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    SNOWMAKING_HEADERS,
)

# The windows the recipes below commit, on the logical clock's opening day.
SESSION_WINDOW_START = "2026-08-01T05:00:00Z"
SESSION_WINDOW_END = "2026-08-01T12:00:00Z"
GROOM_NIGHT_START = "2026-08-01T00:00:00Z"
GROOM_NIGHT_END = "2026-08-01T04:00:00Z"


# ─── Terrain state against the seasonal water right ───

def test_snowmaking_session_on_a_held_trail_reports_terrain_state_not_the_water_right(
    api, mountain
):
    """A session create that names a patrol-held trail and also busts the water right reports the terrain state.

    Because this is the last check in the ladder, a request that is malformed, mistimed or over-capacity in any other way never reports a water-right problem.

    Design: Difficulty/priority_pair_validation_conflict/session_create_terrain_state_beats_water_right_exceeded
    """
    state = mountain.open_mountain(
        season_overrides={"water_right_seasonal_af": 1.000},
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400},
    )
    # A 55 mph reading is above the lift's hold threshold, which pushes the
    # trail it serves onto a patrol hold.
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=55.0, wet_bulb_f=22.0)
    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD", (
        "Setup expects the wind reading to have pushed the trail onto a patrol "
        f"hold, got {held_area['opening_state']}"
    )

    # 1200 gpm across a seven-hour window reserves more water than the whole
    # seasonal right of 1.000 acre-feet, so the water rule is violated too.
    planned_reservation = check.expected_water_af(1200, 420)
    assert planned_reservation == 1.547, (
        f"Setup expects a 1.547 acre-foot reservation, computed {planned_reservation}"
    )

    response = api.create_session(
        payloads.session_payload(
            state["area_id"],
            state["pump_house_id"],
            held_area["version"],
            window_start=SESSION_WINDOW_START,
            window_end=SESSION_WINDOW_END,
            gun_count=30,
            gpm=1200,
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(response, errors.ERR_TERRAIN_STATE_INVALID, 409)
    assert response.status_code == 409, (
        "The terrain state gate carries HTTP 409; reporting the water right "
        f"would have answered 422, got {response.status_code}"
    )

    season_row = mountain.season(state["season_id"])
    check.assert_water_af(season_row["water_reserved_af"], 0.000)
    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    check.assert_water_af(rollup["water_right_remaining_af"], 1.000)

    pump_house = mountain.pump_house(state["pump_house_id"])
    check.assert_integer(pump_house["peak_committed_gpm"], 0)
    check.assert_integer(pump_house["active_session_count"], 0)

    after_area = mountain.area(state["area_id"])
    assert after_area["opening_state"] == "PATROL_HOLD"
    check.assert_version_unchanged(held_area, after_area)


def test_snowmaking_session_beyond_the_seasonal_water_right_alone_reports_the_water_right(
    api, mountain
):
    """On an open trail with the flow ceilings clear, the same oversized reservation reaches the water right.

    Exceeding it is refused with `ERR_WATER_RIGHT_EXCEEDED`.

    Design: Difficulty/priority_pair_validation_conflict/session_create_terrain_state_beats_water_right_exceeded
    """
    state = mountain.open_mountain(
        season_overrides={"water_right_seasonal_af": 1.000},
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400},
    )
    open_area = mountain.area(state["area_id"])
    assert open_area["opening_state"] == "OPEN", (
        "Setup expects the trail open so the terrain state gate cannot fire, got "
        f"{open_area['opening_state']}"
    )

    response = api.create_session(
        payloads.session_payload(
            state["area_id"],
            state["pump_house_id"],
            open_area["version"],
            window_start=SESSION_WINDOW_START,
            window_end=SESSION_WINDOW_END,
            gun_count=30,
            gpm=1200,
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(response, errors.ERR_WATER_RIGHT_EXCEEDED, 422)

    season_row = mountain.season(state["season_id"])
    check.assert_water_af(season_row["water_reserved_af"], 0.000)
    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    check.assert_water_af(rollup["water_right_remaining_af"], 1.000)

    pump_house = mountain.pump_house(state["pump_house_id"])
    check.assert_integer(pump_house["peak_committed_gpm"], 0)


# ─── Cat-route sequencing against snowcat exclusivity ───

def test_out_of_order_dispatch_that_also_double_books_the_snowcat_reports_the_sequence_violation(
    api, mountain
):
    """A dispatch that skips its route order while its cat is already out reports the sequencing problem.

    On grooming dispatch, cat-route sequencing is checked before snowcat exclusivity, so a task that violates both reports `ERR_GROOM_SEQUENCE_VIOLATION`.

    Design: Difficulty/priority_pair_validation_conflict/grooming_dispatch_sequence_violation_beats_snowcat_conflict
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    area = mountain.create_terrain_area(season["id"], lift["id"], name="Sunbowl")

    # First pass of route R1, left unstarted: it is what route order demands
    # before the second pass may roll.
    task_a = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start=GROOM_NIGHT_START,
        window_end=GROOM_NIGHT_END,
    )
    # The same snowcat is out on another route for the whole night, which also
    # moves the trail into preparation.
    task_b = mountain.plan_groom(
        area["id"],
        cat_route_code="R2",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start=GROOM_NIGHT_START,
        window_end=GROOM_NIGHT_END,
    )
    mountain.dispatch_groom(task_b["id"])
    # Second pass of route R1, wholly inside the window CAT-1 is already
    # committed to: out of order and double-booked at once.
    task_c = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=2,
        snowcat_unit_code="CAT-1",
        window_start="2026-08-01T01:00:00Z",
        window_end="2026-08-01T03:00:00Z",
    )

    response = api.dispatch_grooming_task(task_c["id"], GROOMING_HEADERS)
    validate_error(response, errors.ERR_GROOM_SEQUENCE_VIOLATION, 409)

    held_task = mountain.grooming_task(task_c["id"])
    assert held_task["state"] == "PLANNED"
    assert held_task["dispatched_at"] is None, (
        "A rejected dispatch must not stamp dispatched_at, got "
        f"{held_task['dispatched_at']}"
    )
    assert mountain.grooming_task(task_b["id"])["state"] == "DISPATCHED"
    assert mountain.grooming_task(task_a["id"])["state"] == "PLANNED"
    assert mountain.area(area["id"])["opening_state"] == "PREP"


def test_in_order_dispatch_that_double_books_the_snowcat_alone_reports_the_snowcat_conflict(
    api, mountain
):
    """With route order satisfied, the same overlapping snowcat commitment reaches the exclusivity rule.

    Sequencing is checked before machine exclusivity, so a task that is both out of order and double-books its cat reports `ERR_GROOM_SEQUENCE_VIOLATION` rather than `ERR_SNOWCAT_CONFLICT`.

    Design: Difficulty/priority_pair_validation_conflict/grooming_dispatch_sequence_violation_beats_snowcat_conflict
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    area = mountain.create_terrain_area(season["id"], lift["id"], name="Sunbowl")

    task_a = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start=GROOM_NIGHT_START,
        window_end=GROOM_NIGHT_END,
    )
    mountain.dispatch_groom(task_a["id"])
    # Lowest pass on its own route, so nothing is out of order; only the cat is
    # already committed across this window.
    task_c = mountain.plan_groom(
        area["id"],
        cat_route_code="R2",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start="2026-08-01T01:00:00Z",
        window_end="2026-08-01T03:00:00Z",
    )

    response = api.dispatch_grooming_task(task_c["id"], GROOMING_HEADERS)
    validate_error(response, errors.ERR_SNOWCAT_CONFLICT, 409)

    held_task = mountain.grooming_task(task_c["id"])
    assert held_task["state"] == "PLANNED"
    assert held_task["dispatched_at"] is None
    assert mountain.grooming_task(task_a["id"])["state"] == "DISPATCHED"


# ─── The wet-bulb edge for starting the guns ───

def test_snowmaking_starts_at_a_wet_bulb_of_exactly_27_0_on_the_marginal_yield_factor(
    api, mountain
):
    """A wet bulb sitting exactly on the warm limit still makes snow, at the lowest yield factor.

    Every band test is strictly greater-than, which means each boundary value — 27.0, 24.0 and 20.0 — falls into the colder, more productive side: a reading of exactly 27.0 starts successfully at a factor of 0.60, and 27.1 does not start at all.

    Design: Difficulty/boundary_precision_check/wet_bulb_at_exactly_27_0_starts_session_and_27_1_rejects
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wind_speed_mph=10.0,
        wet_bulb_f=27.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400},
    )
    session_a = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T05:00:00Z",
        window_end="2026-08-01T08:00:00Z",
        gun_count=15,
        gpm=600,
    )
    mountain.set_clock("2026-08-01T05:00:00Z")

    response = api.set_session_status(
        session_a["id"],
        payloads.session_status_payload("RUNNING"),
        SNOWMAKING_HEADERS,
    )
    started = validate_success(response)

    assert started["state"] == "RUNNING"
    check.assert_one_decimal(started["wet_bulb_f"], 27.0)
    check.assert_number_equals(started["snow_yield_factor"], 0.6)
    assert check.expected_snow_yield_factor(27.0) == 0.60, (
        "The coldest failing band is the 0.60 factor at exactly 27.0 degrees"
    )
    check.assert_instant_equals(started["started_at"], "2026-08-01T05:00:00Z")
    check.assert_instant_equals(started["last_running_since"], "2026-08-01T05:00:00Z")

    pump_house = mountain.pump_house(state["pump_house_id"])
    check.assert_integer(pump_house["active_session_count"], 1)


def test_snowmaking_is_refused_at_a_wet_bulb_of_27_1_one_tenth_above_the_warm_limit(
    api, mountain
):
    """One tenth of a degree warmer than the limit and the guns are not allowed to start at all.

    A wet bulb above 27.0 degrees Fahrenheit is refused outright with `ERR_WET_BULB_TOO_WARM` and the session stays `SCHEDULED`.

    Design: Difficulty/boundary_precision_check/wet_bulb_at_exactly_27_0_starts_session_and_27_1_rejects
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wind_speed_mph=10.0,
        wet_bulb_f=27.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400},
    )
    # Two touching windows on the same trail and pump house, so the pair differ
    # in nothing but the wet bulb standing when each one is asked to start.
    session_a = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T05:00:00Z",
        window_end="2026-08-01T08:00:00Z",
        gun_count=15,
        gpm=600,
    )
    session_b = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T11:00:00Z",
        gun_count=15,
        gpm=600,
    )
    mountain.set_clock("2026-08-01T05:00:00Z")
    mountain.drive_session(session_a["id"], "RUNNING")
    # The night warms by a single tenth of a degree.
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=10.0, wet_bulb_f=27.1)

    response = api.set_session_status(
        session_b["id"],
        payloads.session_status_payload("RUNNING"),
        SNOWMAKING_HEADERS,
    )
    validate_error(response, errors.ERR_WET_BULB_TOO_WARM, 422)

    held_session = mountain.session(session_b["id"])
    assert held_session["state"] == "SCHEDULED"
    assert held_session["wet_bulb_f"] is None
    assert held_session["snow_yield_factor"] is None
    assert held_session["started_at"] is None

    day_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_one_decimal(day_plan["wet_bulb_f"], 27.1)

    pump_house = mountain.pump_house(state["pump_house_id"])
    check.assert_integer(pump_house["active_session_count"], 1)


# ─── The two-day edge of the snow-stake lookback ───

def test_opening_is_refused_on_base_depth_when_the_only_stake_reading_has_aged_out(
    api, mountain
):
    """A trail whose stakes have gone unread for three days fails on base depth, ahead of the later gates.

    The eight readiness gates of the opening decision run in exactly the order 25 through 32, so an area that fails base depth *and* has an unopened lift reports `ERR_BASE_DEPTH_INSUFFICIENT`, never `ERR_SERVING_LIFT_NOT_OPEN`.

    Design: Difficulty/boundary_precision_check/empty_reading_set_yields_zero_base_depth_on_opening_decision
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        open_the_area=False,
    )
    ready_row = mountain.area(state["area_id"])
    assert ready_row["opening_state"] == "READY", (
        f"Setup expects the trail standing in READY, got {ready_row['opening_state']}"
    )
    check.assert_integer(ready_row["min_open_base_depth_in"], 30)

    # Seventy-two hours later the trail's single stake reading, and the night's
    # groom and the lift's inspection with it, are all long out of date.
    mountain.set_clock("2026-08-04T00:00:00Z")

    response = api.decide_opening(
        state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(response, errors.ERR_BASE_DEPTH_INSUFFICIENT, 422)

    after_area = mountain.area(state["area_id"])
    assert after_area["opening_state"] == "READY", (
        "A refused opening decision moves nothing, got "
        f"{after_area['opening_state']}"
    )
    day_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_integer(day_plan["open_terrain_count"], 0)
    season_row = mountain.season(state["season_id"])
    check.assert_integer(season_row["open_area_count"], 0)


def test_base_depth_counts_only_the_stake_reading_inside_the_two_day_lookback(
    api, mountain
):
    """A fresh reading on a second stake settles the base on its own, because the older stake has expired.

    Only readings whose `measured_at` falls inside a two-day lookback — that is, at or after the instant 48 hours before the current logical clock — are considered at all; anything older is discarded even when it is the only reading a stake has ever produced, which means `base_depth_stake_count` shrinks over time if the stakes go unread.

    Design: Difficulty/boundary_precision_check/empty_reading_set_yields_zero_base_depth_on_opening_decision
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        open_the_area=False,
    )
    # Stake S1 was read at 40.0 inches on opening day and never again.
    mountain.set_clock("2026-08-04T00:00:00Z")

    reading = validate_success(
        api.record_snow_depth_reading(
            state["area_id"],
            payloads.snow_depth_reading_payload(
                stake_code="S2",
                depth_in=36.0,
                measured_at="2026-08-04T00:00:00Z",
            ),
            GROOMING_HEADERS,
        ),
        expected_status=201,
    )
    assert reading["stake_code"] == "S2"

    after_area = mountain.area(state["area_id"])
    check.assert_integer(after_area["base_depth_stake_count"], 1)
    # The mean of both stakes would be 38.0; only S2 survives the window.
    check.assert_one_decimal(after_area["base_depth_in"], 36.0)
