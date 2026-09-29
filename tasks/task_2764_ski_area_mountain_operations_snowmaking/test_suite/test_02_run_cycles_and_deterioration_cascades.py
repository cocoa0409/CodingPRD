"""Snowmaking run cycles, the two lift dimensions, and the deterioration chains.

Two families of mountain behaviour live in this file. The first is the life of a
row that returns to a state it has already occupied: a snowmaking session driven
round the RUNNING and PAUSED cycle several times before it is metered, and a lift
whose service posture and mechanical posture move by different amounts under one
inspection. The second is deterioration travelling several objects away from the
request that caused it: a wind observation that reaches the season water ledger
through a lift, a trail, a cat route and a set of guns, and an incident dispatch
that reaches the operating day's posture through a patroller and a trail.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import ERR_SESSION_STATE_INVALID
from test_helpers.assertions import (
    assert_energy_kwh,
    assert_instant_equals,
    assert_integer,
    assert_one_decimal,
    assert_usd,
    assert_version_unchanged,
    assert_versions_advanced,
    assert_water_af,
    assert_water_ledger_identity,
    expected_capacity,
    expected_response_minutes,
    expected_snow_swe_af,
    expected_water_af,
    find_row,
    shift_instant,
    whole_minutes_between,
)
from test_helpers.constants import (
    INITIAL_CLOCK,
    LIFT_INSPECTION_VALID_HOURS,
    SNOW_YIELD_GOOD,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
)

# ─── The mountain every recipe in this file starts from ───────────────

SEASON_SETUP = {
    "season_label": "2026-27",
    "base_depth_policy": "MEAN_OF_STAKES",
    "water_right_seasonal_af": 250.000,
    "plant_max_gpm": 6000,
    "snowmaking_kwh_per_af": 620.0,
    "min_patrollers_per_open_area": 2,
    "groom_freshness_hours": 18,
}

LIFT_SETUP = {
    "lift_code": "L1",
    "name": "Summit Express",
    "lift_type": "DETACHABLE",
    "wind_hold_threshold_mph": 40.0,
    "hourly_capacity_pph": 1800,
    "required_operator_count": 2,
}

AREA_SETUP = {
    "trail_code": "T1",
    "name": "Sunbowl",
    "terrain_class": "BLUE",
    "acres": 18.0,
    "min_open_base_depth_in": 30,
    "avalanche_terrain": False,
}

DAY_PLAN_SETUP = {"operating_date": "2026-08-01", "parking_stalls_total": 500}

PUMP_HOUSE_SETUP = {
    "pump_house_code": "PH1",
    "name": "Base Pumphouse",
    "max_gpm": 2400,
    "gun_count": 40,
}

CALM_WIND_MPH = 10.0
GALE_WIND_MPH = 55.0
SETTLED_WET_BULB_F = 22.0

SESSION_WINDOW_START = "2026-08-01T05:00:00Z"
SESSION_WINDOW_END = "2026-08-01T12:00:00Z"
SESSION_GPM = 1200
SESSION_GUN_COUNT = 30

FIRST_START = "2026-08-01T05:00:00Z"
FIRST_PAUSE = "2026-08-01T06:00:00Z"
FIRST_RESUME = "2026-08-01T07:00:00Z"
SECOND_PAUSE = "2026-08-01T08:00:00Z"
SECOND_RESUME = "2026-08-01T09:00:00Z"
COMPLETION_INSTANT = "2026-08-01T13:00:00Z"

# The three run segments the cycle closes, and the whole minutes they carry.
CLOSED_SEGMENTS = (
    (FIRST_START, FIRST_PAUSE),
    (FIRST_RESUME, SECOND_PAUSE),
    (SECOND_RESUME, COMPLETION_INSTANT),
)
EXPECTED_RUN_MINUTES = sum(
    whole_minutes_between(start, end) for start, end in CLOSED_SEGMENTS
)
PLANNED_MINUTES = whole_minutes_between(SESSION_WINDOW_START, SESSION_WINDOW_END)

# Seven minutes and thirty seconds after the injured skier was called in.
RESPONSE_ELAPSED_SECONDS = 450
DISPATCH_INSTANT = "2026-08-01T00:07:30Z"

# The night the plant actually worked: start, pause, resume, pause, resume.
NIGHT_CYCLE = [
    (FIRST_START, "RUNNING"),
    (FIRST_PAUSE, "PAUSED"),
    (FIRST_RESUME, "RUNNING"),
    (SECOND_PAUSE, "PAUSED"),
    (SECOND_RESUME, "RUNNING"),
]

# The cycle stopped one step short of its last resume.
CYCLE_UP_TO_SECOND_PAUSE = NIGHT_CYCLE[:-1]


def open_the_mountain(mountain, with_pump_house=False):
    """The mountain standing open at the initial logical clock: a season with its
    water right and price schedule, one lift open on a passing inspection with a
    full crew, one groomed and patrolled terrain area open, and a published
    operating day carrying calm, cold weather.
    """
    mountain.set_clock(INITIAL_CLOCK)
    return mountain.open_mountain(
        season_overrides=dict(SEASON_SETUP),
        lift_overrides=dict(LIFT_SETUP),
        area_overrides=dict(AREA_SETUP),
        day_plan_overrides=dict(DAY_PLAN_SETUP),
        wind_speed_mph=CALM_WIND_MPH,
        wet_bulb_f=SETTLED_WET_BULB_F,
        passes_completed=20,
        patroller_count=2,
        blaster_certified=True,
        with_pump_house=with_pump_house,
        pump_house_overrides=dict(PUMP_HOUSE_SETUP),
    )


def schedule_the_night_session(mountain, state, **overrides):
    """One snowmaking session on the open area, thirty guns at 1200 gallons a
    minute across the seven-hour window the plant planned for."""
    payload = {
        "window_start": SESSION_WINDOW_START,
        "window_end": SESSION_WINDOW_END,
        "gun_count": SESSION_GUN_COUNT,
        "gpm": SESSION_GPM,
    }
    payload.update(overrides)
    return mountain.schedule_session(
        state["area_id"], state["pump_house_id"], **payload
    )


def plan_the_second_cat_route(mountain, area_id):
    """A second grooming task on the same trail, left planned so that a
    deterioration chain has something to defer."""
    return mountain.plan_groom(
        area_id,
        cat_route_code="R1",
        sequence_index=2,
        snowcat_unit_code="CAT-2",
        window_start="2026-08-01T06:00:00Z",
        window_end="2026-08-01T10:00:00Z",
    )


def grooming_tasks_of(api, area_id):
    """Every grooming task standing against one terrain area."""
    rows, _meta = validate_paginated(
        api.list_grooming_tasks(DIRECTOR_HEADERS, terrain_area_id=area_id)
    )
    return rows


# ─── A session driven round the running and paused cycle ──────────────

def test_snowmaking_session_meters_only_the_minutes_of_its_closed_run_segments(api, mountain):
    """A session cycled twice between running and paused accumulates the minutes of every closed segment, not the span of its window.

    The `RUNNING` and `PAUSED` states may alternate as many times as the night demands, and that is the whole point: the metered figures depend on how many times the cycle was traversed, not merely on where the session finished.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    mountain.set_clock(COMPLETION_INSTANT)

    completed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    assert completed["state"] == "COMPLETED"
    assert EXPECTED_RUN_MINUTES == 360
    assert PLANNED_MINUTES == 420
    assert_integer(completed["accumulated_run_minutes"], 360)


def test_resuming_a_paused_session_restamps_only_the_open_segment_marker(api, mountain):
    """A resume stamps a fresh open-segment marker while the session's original start instant stays where the first run put it.

    Resuming — `PAUSED → RUNNING` — re-checks that the pump house is `ONLINE`, that the active day plan's `wet_bulb_f` is still at or below 27.0, and that the terrain area is still neither held nor season-closed, then stamps `last_running_since` afresh.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    paused = mountain.run_session_cycle(session["id"], CYCLE_UP_TO_SECOND_PAUSE)
    assert paused["state"] == "PAUSED"
    assert paused["last_running_since"] is None
    mountain.set_clock(SECOND_RESUME)

    resumed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        )
    )

    assert resumed["state"] == "RUNNING"
    assert_instant_equals(resumed["last_running_since"], SECOND_RESUME)
    assert_instant_equals(resumed["started_at"], FIRST_START)


def test_completing_a_cycled_session_stamps_its_end_and_closes_the_open_segment_marker(api, mountain):
    """Completion from the running state ends the session at the logical clock and leaves no open segment behind.

    The session then moves to `COMPLETED`, `ended_at` is stamped with the logical clock, and `last_running_since` is cleared.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    running = mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    mountain.set_clock(COMPLETION_INSTANT)

    completed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    assert completed["state"] == "COMPLETED"
    assert_instant_equals(completed["ended_at"], COMPLETION_INSTANT)
    assert completed["last_running_since"] is None
    assert_versions_advanced(running, completed)


def test_metered_water_bills_the_accumulated_minutes_and_stays_below_the_reservation(api, mountain):
    """The water actually drawn is priced off the accumulated minutes, so a session that idled through part of its window meters below what it reserved.

    Metered water follows the same arithmetic as the reservation but on real minutes: the committed `gpm` multiplied by `accumulated_run_minutes`, divided by the 325,851 gallons in an acre-foot, rounded half up to three decimal places, stored as `water_af_actual`.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    assert_water_af(session["water_af_reserved"], 1.547)
    mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    mountain.set_clock(COMPLETION_INSTANT)

    completed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    assert expected_water_af(SESSION_GPM, EXPECTED_RUN_MINUTES) == 1.326
    assert_water_af(completed["water_af_actual"], 1.326)
    assert_water_af(completed["water_af_reserved"], 1.547)


def test_snow_water_equivalent_is_the_metered_water_at_the_committed_yield_factor(api, mountain):
    """The snow made is the metered water scaled by the yield factor the cold wet bulb earned.

    `snow_swe_af` is then the metered water multiplied by `snow_yield_factor`, rounded half up to three decimal places.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    mountain.set_clock(COMPLETION_INSTANT)

    completed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    assert expected_snow_swe_af(1.326, SNOW_YIELD_GOOD) == 1.127
    assert_water_af(completed["snow_swe_af"], 1.127)


def test_completing_the_last_session_empties_the_pump_house_occupancy(api, mountain):
    """When the night's only session finishes, the pump house is left with no occupants and no committed peak.

    The pump house's `active_session_count` is decremented by 1 and its `peak_committed_gpm` is recomputed over the remaining occupants.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    running_plant = mountain.pump_house(state["pump_house_id"])
    assert_integer(running_plant["active_session_count"], 1)
    mountain.set_clock(COMPLETION_INSTANT)

    completed = validate_success(
        api.set_session_status(
            session["id"], f.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    assert completed["state"] == "COMPLETED"
    quiet_plant = mountain.pump_house(state["pump_house_id"])
    assert_integer(quiet_plant["active_session_count"], 0)
    assert_integer(quiet_plant["peak_committed_gpm"], 0)


def test_a_finished_session_cannot_be_sent_back_round_the_cycle(api, mountain):
    """Once metered, the session is finished for good and will not run again however many times it cycled before.

    Any other request — asking for `PAUSED` straight from `SCHEDULED`, or touching a finished session — is refused with `ERR_SESSION_STATE_INVALID`.

    Design: Difficulty/non_linear_state_machine/snowmaking_session_running_paused_cycle_accumulates_minutes
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    session = schedule_the_night_session(mountain, state)
    mountain.run_session_cycle(session["id"], NIGHT_CYCLE)
    mountain.set_clock(COMPLETION_INSTANT)
    finished = mountain.drive_session(session["id"], "COMPLETED")
    assert finished["state"] == "COMPLETED"
    mountain.set_clock("2026-08-01T14:00:00Z")

    validate_error(
        api.set_session_status(
            session["id"], f.session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        ),
        ERR_SESSION_STATE_INVALID,
    )

    unchanged = mountain.session(session["id"])
    assert unchanged["state"] == "COMPLETED"
    assert_integer(unchanged["accumulated_run_minutes"], 360)
    assert_version_unchanged(finished, unchanged)


# ─── One lift, two dimensions moving by different amounts ─────────────

def test_failing_inspection_moves_the_mechanical_dimension_and_voids_the_validity_window(api, mountain):
    """A failed inspection re-marks what the mechanics know about the lift and destroys the currency of the last pass.

    `mechanical_status` moves to `INSPECTION_FAILED` — again accepted from any of the three mechanical states, so `INSPECTION_PASSED → INSPECTION_FAILED` and a re-failure both apply — and `inspection_valid_until` is set to null.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    assert state["lift"]["mechanical_status"] == "INSPECTION_PASSED"
    assert state["lift"]["service_status"] == "OPEN"

    failed = validate_success(
        api.record_lift_inspection(
            state["lift_id"],
            f.inspection_payload("FAIL", notes="cable slip on the return bullwheel"),
            LIFT_OPS_HEADERS,
        )
    )

    assert failed["mechanical_status"] == "INSPECTION_FAILED"
    assert failed["inspection_valid_until"] is None


def test_failing_inspection_forces_the_open_lift_onto_a_mechanical_hold_and_holds_its_terrain(api, mountain):
    """The service dimension is dragged to a mechanical hold and the trail the lift serves is pulled off the open posture with it.

    If `service_status` was `OPEN`, `STANDBY` or `WIND_HOLD`, it is forced to `MECH_HOLD`, and that drives the full deterioration chain: every terrain area served by this lift whose `opening_state` was `OPEN` moves `OPEN → PATROL_HOLD`; each such area moves its `PLANNED` and `DISPATCHED` grooming tasks to `DEFERRED`; each such area moves its `SCHEDULED`, `RUNNING` and `PAUSED` snowmaking sessions to `ABORTED` with `abort_reason` `TERRAIN_HOLD`; and each aborted session's `water_af_reserved` is subtracted from the season's `water_reserved_af`.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    lift_before = mountain.lift(state["lift_id"])
    area_before = mountain.area(state["area_id"])
    assert area_before["opening_state"] == "OPEN"

    failed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("FAIL"), LIFT_OPS_HEADERS
        )
    )

    assert failed["service_status"] == "MECH_HOLD"
    assert_versions_advanced(lift_before, failed)
    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    assert_versions_advanced(area_before, held_area)


def test_failing_inspection_leaves_an_already_finished_grooming_task_alone(api, mountain):
    """The deferral only reaches grooming work still ahead of the snowcats; the pass that has already been driven is untouched.

    If `service_status` was `OPEN`, `STANDBY` or `WIND_HOLD`, it is forced to `MECH_HOLD`, and that drives the full deterioration chain: every terrain area served by this lift whose `opening_state` was `OPEN` moves `OPEN → PATROL_HOLD`; each such area moves its `PLANNED` and `DISPATCHED` grooming tasks to `DEFERRED`; each such area moves its `SCHEDULED`, `RUNNING` and `PAUSED` snowmaking sessions to `ABORTED` with `abort_reason` `TERRAIN_HOLD`; and each aborted session's `water_af_reserved` is subtracted from the season's `water_reserved_af`.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    finished_before = find_row(grooming_tasks_of(api, state["area_id"]), sequence_index=1)
    assert finished_before["state"] == "COMPLETED"

    failed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("FAIL"), LIFT_OPS_HEADERS
        )
    )

    assert failed["service_status"] == "MECH_HOLD"
    finished_after = mountain.grooming_task(finished_before["id"])
    assert finished_after["state"] == "COMPLETED"
    assert_version_unchanged(finished_before, finished_after)


def test_passing_reinspection_restores_the_mechanical_dimension_and_extends_the_validity_window(api, mountain):
    """A pass recorded after a failure puts the mechanical dimension back and dates the new currency window a full day out.

    A passing inspection sets `mechanical_status` to `INSPECTION_PASSED` and sets `inspection_valid_until` to 24 hours after the inspection instant, which is the entire basis of the currency test used elsewhere: an inspection is current while the logical clock is strictly before `inspection_valid_until`.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    mountain.inspect_lift(state["lift_id"], "FAIL")

    passed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("PASS"), LIFT_OPS_HEADERS
        )
    )

    assert passed["mechanical_status"] == "INSPECTION_PASSED"
    assert_instant_equals(
        passed["inspection_valid_until"],
        shift_instant(INITIAL_CLOCK, hours=LIFT_INSPECTION_VALID_HOURS),
    )
    assert_instant_equals(passed["inspection_valid_until"], "2026-08-02T00:00:00Z")


def test_passing_reinspection_lifts_the_service_dimension_only_as_far_as_standby(api, mountain):
    """The mechanical dimension recovers fully in one act while the service dimension climbs just one rung, back to standby rather than back to open.

    A passing inspection additionally releases a mechanical hold: if `service_status` was `MECH_HOLD` it moves `MECH_HOLD → STANDBY`, and every terrain area served by the lift that is sitting on `PATROL_HOLD` is re-gated and returned to `OPEN` only if every opening gate holds at the current clock.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    held = mountain.inspect_lift(state["lift_id"], "FAIL")
    assert held["service_status"] == "MECH_HOLD"

    passed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("PASS"), LIFT_OPS_HEADERS
        )
    )

    assert passed["service_status"] == "STANDBY"
    assert passed["mechanical_status"] == "INSPECTION_PASSED"


def test_terrain_held_by_a_lift_failure_stays_held_after_the_lift_passes_reinspection(api, mountain):
    """The trail does not ride the lift's recovery back open, because its serving lift is no longer running.

    Recovery is always an explicit, individually gated act. Releasing a wind hold, passing a mechanical inspection, or putting a patroller back on duty may make an area eligible to reopen, but an area sitting on a patrol hold is only returned to service when every one of the opening gates is re-satisfied at the current logical clock — and a duty change or an incident closure alone never auto-reopens a held area.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    mountain.inspect_lift(state["lift_id"], "FAIL")
    assert mountain.area(state["area_id"])["opening_state"] == "PATROL_HOLD"

    passed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("PASS"), LIFT_OPS_HEADERS
        )
    )

    assert passed["service_status"] == "STANDBY"
    still_held = mountain.area(state["area_id"])
    assert still_held["opening_state"] == "PATROL_HOLD"


def test_uphill_capacity_stays_at_zero_while_the_lift_sits_off_the_open_posture(api, mountain):
    """A lift on standby after its recovery still carries nobody uphill, so the operating day's capacity figures stay on the floor.

    First, `open_lift_capacity_pph` is the sum of `hourly_capacity_pph` across the season's lifts whose `service_status` is `OPEN`; a lift on a wind or mechanical hold contributes nothing at all.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    assert_integer(state["day_plan"]["open_lift_capacity_pph"], 1800)
    mountain.inspect_lift(state["lift_id"], "FAIL")

    passed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("PASS"), LIFT_OPS_HEADERS
        )
    )

    assert passed["service_status"] == "STANDBY"
    grounded = expected_capacity(0, 0.0)
    plan = mountain.day_plan(state["day_plan_id"])
    assert_integer(plan["open_lift_capacity_pph"], grounded["open_lift_capacity_pph"])
    assert_integer(plan["open_lift_capacity_pph"], 0)
    assert_integer(plan["raw_ccc"], 0)
    assert_integer(plan["guest_capacity"], 0)
    assert_integer(plan["non_season_pool"], 0)


def test_each_inspection_result_is_stamped_onto_the_lift_record(api, mountain):
    """Whichever way the inspection goes, the lift remembers when it was inspected and what the mechanics found.

    Either result stamps `last_inspection_at` with the logical clock and copies the outcome into `last_inspection_result`.

    Design: Difficulty/non_linear_state_machine/lift_parallel_service_and_mechanical_dimensions_evolve_independently
    """
    state = open_the_mountain(mountain)
    failed = mountain.inspect_lift(state["lift_id"], "FAIL")
    assert failed["last_inspection_result"] == "FAIL"
    assert_instant_equals(failed["last_inspection_at"], INITIAL_CLOCK)

    passed = validate_success(
        api.record_lift_inspection(
            state["lift_id"], f.inspection_payload("PASS"), LIFT_OPS_HEADERS
        )
    )

    assert passed["last_inspection_result"] == "PASS"
    assert_instant_equals(passed["last_inspection_at"], INITIAL_CLOCK)


# ─── A wind observation travelling all the way to the water ledger ────

def test_wind_above_the_lift_threshold_puts_the_running_lift_on_a_wind_hold(api, mountain):
    """A gale reported on the operating day stops the only lift whose hold threshold the wind clears.

    First, every lift of the season whose `service_status` is `OPEN` and whose `wind_hold_threshold_mph` is **strictly below** the reported wind moves `OPEN → WIND_HOLD` with `wind_hold_since` stamped, processed in ascending `lift_code` order; a lift whose threshold exactly equals the reported wind stays open.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    schedule_the_night_session(mountain, state)
    lift_before = mountain.lift(state["lift_id"])
    assert lift_before["service_status"] == "OPEN"
    assert_one_decimal(lift_before["wind_hold_threshold_mph"], 40.0)

    plan = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    assert_one_decimal(plan["wind_speed_mph"], 55.0)
    held_lift = mountain.lift(state["lift_id"])
    assert held_lift["service_status"] == "WIND_HOLD"
    assert_instant_equals(held_lift["wind_hold_since"], INITIAL_CLOCK)
    assert_versions_advanced(lift_before, held_lift)


def test_wind_hold_defers_the_planned_grooming_and_aborts_the_snowmaking_on_the_held_trail(api, mountain):
    """From the lift the hold reaches the trail, from the trail the cat route still to be driven and the guns still to be fired.

    Each lift entering the hold cascades its `OPEN` terrain areas onto `PATROL_HOLD` in ascending `trail_code` order; each such area defers its `PLANNED` and `DISPATCHED` grooming tasks in ascending `sequence_index` order and aborts its `SCHEDULED`, `RUNNING` and `PAUSED` sessions in ascending `created_at` order with `abort_reason` `TERRAIN_HOLD`; and each aborted session releases its `water_af_reserved` back out of the season's `water_reserved_af`.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    planned_task = plan_the_second_cat_route(mountain, state["area_id"])
    session = schedule_the_night_session(mountain, state)
    area_before = mountain.area(state["area_id"])
    finished_task = find_row(grooming_tasks_of(api, state["area_id"]), sequence_index=1)
    assert planned_task["state"] == "PLANNED"
    assert session["state"] == "SCHEDULED"

    validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    assert_versions_advanced(area_before, held_area)
    deferred = mountain.grooming_task(planned_task["id"])
    assert deferred["state"] == "DEFERRED"
    assert_versions_advanced(planned_task, deferred)
    assert mountain.grooming_task(finished_task["id"])["state"] == "COMPLETED"
    aborted = mountain.session(session["id"])
    assert aborted["state"] == "ABORTED"
    assert aborted["abort_reason"] == "TERRAIN_HOLD"
    assert_versions_advanced(session, aborted)


def test_wind_hold_returns_the_aborted_reservation_to_the_season_water_ledger(api, mountain):
    """Four objects down the chain, the water the aborted session had set aside comes back to the season and the ledger reads as though the session had never been planned.

    Its `water_af_reserved` is subtracted from the season's `water_reserved_af` as a compensating release while `water_used_af` is left untouched, which returns the season ledger to exactly the value it held before the session was created.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    session = schedule_the_night_session(mountain, state)
    assert_water_af(session["water_af_reserved"], 1.547)
    committed_season = mountain.season(state["season_id"])
    assert_water_af(committed_season["water_reserved_af"], 1.547)

    validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    released_season = mountain.season(state["season_id"])
    assert_water_af(released_season["water_reserved_af"], 0.000)
    assert_water_af(released_season["water_used_af"], 0.000)
    assert_water_ledger_identity(released_season, 250.000)
    assert_versions_advanced(committed_season, released_season)
    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    assert_water_af(rollup["water_right_remaining_af"], 250.000)


def test_an_aborted_snowmaking_session_is_never_priced(api, mountain):
    """A session killed by the hold carries no water, no snow, no power and no cost.

    The session's `ended_at` is stamped, `abort_reason` records `TERRAIN_HOLD`, `SUPERSEDED` or `SEASON_CLOSE`, and every metered figure is forced flat: `water_af_actual` 0.000, `snow_swe_af` 0.000, `energy_kwh` 0.000 and `energy_cost_usd` 0.00 — an aborted session is never priced, however many minutes it ran.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    session = schedule_the_night_session(mountain, state)

    validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    aborted = mountain.session(session["id"])
    assert aborted["abort_reason"] == "TERRAIN_HOLD"
    assert_instant_equals(aborted["ended_at"], INITIAL_CLOCK)
    assert_water_af(aborted["water_af_actual"], 0.000)
    assert_water_af(aborted["snow_swe_af"], 0.000)
    assert_energy_kwh(aborted["energy_kwh"], 0.000)
    assert_usd(aborted["energy_cost_usd"], 0.00)


def test_the_wind_hold_cascade_drops_the_operating_day_out_of_the_full_posture(api, mountain):
    """With its one trail held, the day can no longer claim that everything openable is open.

    The reverse, `PUBLISHED_FULL → PUBLISHED_PARTIAL`, fires as soon as `open_terrain_count` drops below that number, whether through an explicit close or through a patrol-hold cascade.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    schedule_the_night_session(mountain, state)
    assert state["day_plan"]["posture"] == "PUBLISHED_FULL"

    plan = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    assert plan["posture"] == "PUBLISHED_PARTIAL"


def test_the_wind_hold_cascade_empties_the_open_terrain_counters(api, mountain):
    """No trail is left open, so the count of open terrain and the open acreage both fall to nothing.

    Second, `open_terrain_count` is the number of the season's areas whose `opening_state` is `OPEN`, and `terrain_open_acres` is the sum of those areas' `acres`, rounded half up to one decimal place.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    schedule_the_night_session(mountain, state)
    assert_integer(state["day_plan"]["open_terrain_count"], 1)
    assert_one_decimal(state["day_plan"]["terrain_open_acres"], 18.0)

    plan = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    assert_integer(plan["open_terrain_count"], 0)
    assert_one_decimal(plan["terrain_open_acres"], 0.0)


def test_the_wind_hold_cascade_zeroes_the_carrying_capacity_of_the_day(api, mountain):
    """A lift standing still carries nobody uphill, and the whole capacity chain collapses behind it.

    First, `open_lift_capacity_pph` is the sum of `hourly_capacity_pph` across the season's lifts whose `service_status` is `OPEN`; a lift on a wind or mechanical hold contributes nothing at all.

    Design: Difficulty/transitive_cascade/weather_wind_hold_cascade_depth_four_to_season_water_ledger
    """
    state = open_the_mountain(mountain, with_pump_house=True)
    plan_the_second_cat_route(mountain, state["area_id"])
    schedule_the_night_session(mountain, state)
    assert_integer(state["day_plan"]["open_lift_capacity_pph"], 1800)

    plan = validate_success(
        api.post_weather(
            state["day_plan_id"],
            f.weather_payload(GALE_WIND_MPH, SETTLED_WET_BULB_F),
            DIRECTOR_HEADERS,
        )
    )

    becalmed = expected_capacity(0, 0.0)
    assert_integer(plan["open_lift_capacity_pph"], becalmed["open_lift_capacity_pph"])
    assert_integer(plan["open_lift_capacity_pph"], 0)
    assert_integer(plan["raw_ccc"], becalmed["raw_ccc"])
    assert_integer(plan["guest_capacity"], becalmed["guest_capacity"])
    assert_integer(plan["non_season_pool"], becalmed["non_season_pool"])


# ─── An ambulance run travelling to the posture of the operating day ──

def test_dispatching_a_patroller_holds_the_trail_and_defers_its_planned_grooming(api, mountain):
    """Sending one of the trail's two patrollers to an injured skier takes the trail below its staffing floor and stops the grooming still to be driven on it.

    The responder then moves `AVAILABLE → ON_INCIDENT`, which recomputes their assigned area's `assigned_patroller_count`, which may push that area `OPEN → PATROL_HOLD`, which defers that area's `PLANNED` and `DISPATCHED` grooming tasks and aborts its `SCHEDULED`, `RUNNING` and `PAUSED` sessions with their water released, which recomputes the active day plan's `open_terrain_count`, `terrain_open_acres`, `guest_capacity` and `posture`.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    planned_task = plan_the_second_cat_route(mountain, state["area_id"])
    responder_id = state["patroller_ids"][0]
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    assert incident["state"] == "REPORTED"
    area_before = mountain.area(state["area_id"])
    assert area_before["opening_state"] == "OPEN"
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(responder_id),
            DIRECTOR_HEADERS,
        )
    )

    assert dispatched["state"] == "DISPATCHED"
    assert dispatched["responder_patroller_id"] == responder_id
    assert mountain.patroller(responder_id)["status"] == "ON_INCIDENT"
    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    assert_versions_advanced(area_before, held_area)
    deferred = mountain.grooming_task(planned_task["id"])
    assert deferred["state"] == "DEFERRED"


def test_incident_response_minutes_round_half_up_from_seven_and_a_half_elapsed_minutes(api, mountain):
    """Seven and a half minutes between the call and the dispatch is recorded as eight whole minutes.

    On success the incident moves `REPORTED → DISPATCHED`, `dispatched_at` is stamped, `responder_patroller_id` is recorded, and `response_minutes` is computed as the whole seconds elapsed from `reported_at` to `dispatched_at` divided by 60 and rounded half up to a whole number of minutes: seven minutes and thirty seconds becomes 8, while seven minutes and twenty-nine seconds becomes 7, and a dispatch in the same logical instant as the report yields 0.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    plan_the_second_cat_route(mountain, state["area_id"])
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    assert_instant_equals(incident["reported_at"], INITIAL_CLOCK)
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(state["patroller_ids"][0]),
            DIRECTOR_HEADERS,
        )
    )

    assert_instant_equals(dispatched["dispatched_at"], DISPATCH_INSTANT)
    assert expected_response_minutes(RESPONSE_ELAPSED_SECONDS) == 8
    assert_integer(dispatched["response_minutes"], 8)


def test_a_patroller_on_an_incident_drops_out_of_the_trail_staffing_count(api, mountain):
    """The trail keeps both patrollers on its roster but only the one still free counts towards its staffing floor.

    Patrollers who are `OFF_DUTY` and patrollers who are `ON_INCIDENT` both drop out of the count, and that is the mechanism by which an ordinary ambulance run can close a trail.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    plan_the_second_cat_route(mountain, state["area_id"])
    responder_id, standing_by_id = state["patroller_ids"]
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    assert_integer(mountain.area(state["area_id"])["assigned_patroller_count"], 2)
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(responder_id),
            DIRECTOR_HEADERS,
        )
    )

    assert dispatched["state"] == "DISPATCHED"
    assert mountain.patroller(responder_id)["status"] == "ON_INCIDENT"
    assert mountain.patroller(standing_by_id)["status"] == "AVAILABLE"
    assert_integer(mountain.area(state["area_id"])["assigned_patroller_count"], 1)


def test_the_incident_cascade_drops_the_operating_day_out_of_the_full_posture(api, mountain):
    """Three objects from the dispatch, the operating day stops advertising a fully open mountain.

    The reverse, `PUBLISHED_FULL → PUBLISHED_PARTIAL`, fires as soon as `open_terrain_count` drops below that number, whether through an explicit close or through a patrol-hold cascade.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    plan_the_second_cat_route(mountain, state["area_id"])
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    assert state["day_plan"]["posture"] == "PUBLISHED_FULL"
    assert_integer(state["day_plan"]["open_terrain_count"], 1)
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(state["patroller_ids"][0]),
            DIRECTOR_HEADERS,
        )
    )

    assert dispatched["state"] == "DISPATCHED"
    plan = mountain.day_plan(state["day_plan_id"])
    assert plan["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(plan["open_terrain_count"], 0)
    assert_one_decimal(plan["terrain_open_acres"], 0.0)


def test_guest_capacity_rises_to_the_uncrowded_figure_when_the_last_acreage_closes(api, mountain):
    """With the lift still spinning but no acreage open at all, the crowding penalty falls away and the day is left carrying its uncrowded capacity.

    Fourth, a crowding density is derived as `raw_ccc` divided by `terrain_open_acres`, or 0.0 when no acreage is open; this density is computed from `raw_ccc` and is **never** recomputed from the reduced figure.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    plan_the_second_cat_route(mountain, state["area_id"])
    crowded = expected_capacity(1800, 18.0)
    assert_integer(state["day_plan"]["guest_capacity"], crowded["guest_capacity"])
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(state["patroller_ids"][0]),
            DIRECTOR_HEADERS,
        )
    )

    assert dispatched["state"] == "DISPATCHED"
    uncrowded = expected_capacity(1800, 0.0)
    plan = mountain.day_plan(state["day_plan_id"])
    assert_integer(plan["open_lift_capacity_pph"], 1800)
    assert_integer(plan["raw_ccc"], uncrowded["raw_ccc"])
    assert_integer(plan["raw_ccc"], 1080)
    assert_integer(plan["guest_capacity"], uncrowded["guest_capacity"])
    assert_integer(plan["guest_capacity"], 1080)
    assert_integer(plan["non_season_pool"], uncrowded["non_season_pool"])
    assert_integer(plan["non_season_pool"], 756)


def test_the_incident_cascade_recounts_the_seasons_open_areas(api, mountain):
    """The season's own tally of open terrain follows the cascade down to nothing.

    The season configuration also carries `open_area_count`, the number of its terrain areas currently in the open state, and it is recomputed on every opening decision and on every cascade that moves an area in or out of the open state.

    Design: Difficulty/transitive_cascade/incident_dispatch_cascade_depth_three_to_day_plan_posture
    """
    state = open_the_mountain(mountain)
    plan_the_second_cat_route(mountain, state["area_id"])
    incident = mountain.report_incident(state["area_id"], reporter_code="LIFTIE-3")
    assert_integer(mountain.season(state["season_id"])["open_area_count"], 1)
    mountain.set_clock(DISPATCH_INSTANT)

    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            f.incident_dispatch_payload(state["patroller_ids"][0]),
            DIRECTOR_HEADERS,
        )
    )

    assert dispatched["state"] == "DISPATCHED"
    assert_integer(mountain.season(state["season_id"])["open_area_count"], 0)
