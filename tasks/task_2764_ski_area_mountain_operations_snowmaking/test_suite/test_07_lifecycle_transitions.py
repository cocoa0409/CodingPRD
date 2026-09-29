"""How the mountain's objects enter, move between and leave their states.

Every operational object on this mountain carries a life story: a lift is
registered uninspected and has to earn its way to a spinning posture, a cat
pass is planned before it rolls and closed out afterwards, a snowmaking session
is scheduled, run, paused and metered, an avalanche mission is planned,
executed and signed off by a second pair of eyes, and a terrain area climbs a
readiness ladder before the director may ever call it open. These tests pin
that vocabulary at three points.

First, where the story begins: each family of rows has its own declared
starting state, and a patroller's depends on the duty flag it was rostered
with. Second, the moves that are legal and what they stamp — a passing
mechanical inspection that touches the mechanical dimension of a lift and
deliberately leaves the guest-facing one alone, a wind hold released only once
the anemometer has fallen a full five miles per hour below the figure that
armed it, a hazard rating that turns a signed-off mitigation into an extended
hold. Third, the moves that are not legal: reporting the same cat pass finished
twice, metering the same session twice, opening a trail that is still being
prepared, releasing an operator who is already off the roster.

Because deterioration on this mountain travels downhill on its own while
recovery never does, most of these transitions drag other rows with them, and
the tests below re-read every row the move was entitled to touch — the served
terrain, the deferred grooming, the released water, the day's carrying
capacity — as well as the rows it must have left alone.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import api_errors as errors
from test_helpers import assertions as check
from test_helpers import factories as payloads
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GROOMING_USER_ID,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
    make_patroller_headers,
)

# The logical clock reads this instant before any call is made, and these
# recipes only move it where the rule under test needs elapsed time.
OPENING_INSTANT = "2026-08-01T00:00:00Z"
INSPECTION_EXPIRY = "2026-08-02T00:00:00Z"

# The lift these recipes register holds its terrain at forty miles per hour, so
# the release band sits at exactly thirty-five.
WIND_HOLD_THRESHOLD_MPH = 40.0

# The overnight cat window and the snowmaking window the recipes commit.
GROOM_NIGHT_START = "2026-08-01T00:00:00Z"
GROOM_NIGHT_END = "2026-08-01T04:00:00Z"
SESSION_WINDOW_START = "2026-08-01T05:00:00Z"
SESSION_WINDOW_END = "2026-08-01T12:00:00Z"


# ─── Where every story begins ───

def test_every_newly_created_row_lands_in_the_state_the_mountain_declares_for_it(
    api, mountain
):
    """Six families of rows are created rather than transitioned into, and a patroller's start depends on the duty flag.

    A patroller created with `on_duty` true therefore lands directly in `AVAILABLE`, and one created off duty lands in `OFF_DUTY`.

    Design: Corner/state_machines/every_entity_is_created_in_its_declared_initial_state
    """
    season = mountain.create_season()
    lift = mountain.create_lift(
        season["id"], wind_hold_threshold_mph=WIND_HOLD_THRESHOLD_MPH
    )
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"], name="Sunbowl")
    pump_house = mountain.create_pump_house(season["id"])

    fresh_area = mountain.area(area["id"])
    assert fresh_area["opening_state"] == "CLOSED", (
        "Setup expects an untouched trail, got "
        f"{fresh_area['opening_state']}"
    )

    session = validate_success(
        api.create_session(
            payloads.session_payload(
                area["id"],
                pump_house["id"],
                fresh_area["version"],
                window_start=SESSION_WINDOW_START,
                window_end=SESSION_WINDOW_END,
                gun_count=30,
                gpm=1200,
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert session["state"] == "SCHEDULED"
    check.assert_integer(session["accumulated_run_minutes"], 0)
    check.assert_water_af(session["water_af_actual"], 0.000)
    assert session["started_at"] is None

    task = validate_success(
        api.create_grooming_task(
            payloads.grooming_task_payload(
                area["id"],
                window_start=GROOM_NIGHT_START,
                window_end=GROOM_NIGHT_END,
            ),
            GROOMING_HEADERS,
        ),
        201,
    )
    assert task["state"] == "PLANNED"
    check.assert_integer(task["passes_completed"], 0)
    check.assert_one_decimal(task["coverage_pct"], 0.0)
    assert task["dispatched_at"] is None

    mission = validate_success(
        api.create_mission(
            payloads.mission_payload(
                area["id"],
                route_code="AV-1",
                method="SKI_CUT",
                hazard_rating_pre="MODERATE",
                planned_charges=0,
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert mission["state"] == "PLANNED"
    check.assert_integer(mission["charges_used"], 0)
    check.assert_integer(mission["road_closure_minutes"], 0)

    incident = validate_success(
        api.create_incident(
            payloads.incident_payload(
                area["id"], reporter_code="LIFTOP-3", severity="MINOR"
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert incident["state"] == "REPORTED"
    assert incident["responder_patroller_id"] is None
    check.assert_integer(incident["response_minutes"], 0)
    check.assert_instant_equals(incident["reported_at"], OPENING_INSTANT)

    day_plan = validate_success(
        api.create_day_plan(payloads.day_plan_payload(season["id"]), DIRECTOR_HEADERS),
        201,
    )
    assert day_plan["posture"] == "DRAFT"
    assert day_plan["published_at"] is None
    check.assert_integer(day_plan["guest_capacity"], 0)
    check.assert_integer(day_plan["raw_ccc"], 0)

    off_duty = validate_success(
        api.create_patroller(
            payloads.patroller_payload(
                season["id"], patroller_code="P1", full_name="Off Duty", on_duty=False
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert off_duty["status"] == "OFF_DUTY"

    on_duty = validate_success(
        api.create_patroller(
            payloads.patroller_payload(
                season["id"], patroller_code="P2", full_name="On Duty", on_duty=True
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert on_duty["status"] == "AVAILABLE"

    # Scheduling the guns is work starting on the trail, which is the one side
    # effect these creates are allowed to have.
    prepared_area = mountain.area(area["id"])
    assert prepared_area["opening_state"] == "PREP"
    check.assert_versioned_row(prepared_area, 2)


# ─── The two dimensions of a lift move on their own ───

def test_a_passing_inspection_stamps_the_mechanics_and_leaves_the_lift_closed_to_guests(
    api, mountain, season
):
    """A passing inspection moves only the mechanical dimension and dates the currency window a day out.

    A passing inspection sets `mechanical_status` to `INSPECTION_PASSED` and sets `inspection_valid_until` to 24 hours after the inspection instant, which is the entire basis of the currency test used elsewhere: an inspection is current while the logical clock is strictly before `inspection_valid_until`.

    Design: Corner/state_machines/inspection_pass_stamps_the_mechanical_dimension_without_moving_the_service_dimension
    """
    lift = mountain.create_lift(
        season["id"], wind_hold_threshold_mph=WIND_HOLD_THRESHOLD_MPH
    )
    assert lift["mechanical_status"] == "INSPECTION_DUE", (
        f"Setup expects an uninspected lift, got {lift['mechanical_status']}"
    )

    inspected = validate_success(
        api.record_lift_inspection(
            lift["id"],
            payloads.inspection_payload("PASS", notes="daily pre-op"),
            LIFT_OPS_HEADERS,
        )
    )
    assert inspected["mechanical_status"] == "INSPECTION_PASSED"
    assert inspected["last_inspection_result"] == "PASS"
    check.assert_instant_equals(inspected["last_inspection_at"], OPENING_INSTANT)
    check.assert_instant_equals(inspected["inspection_valid_until"], INSPECTION_EXPIRY)
    assert inspected["service_status"] == "CLOSED", (
        "The mechanics passing the lift tells the guests nothing; the service "
        f"dimension must still read CLOSED, got {inspected['service_status']}"
    )

    mountain.staff_lift(lift["id"])
    staffed = mountain.lift(lift["id"])
    check.assert_integer(staffed["staffed_operator_count"], 2)

    on_standby = validate_success(
        api.set_lift_service_status(
            lift["id"], payloads.service_status_payload("STANDBY"), LIFT_OPS_HEADERS
        )
    )
    assert on_standby["service_status"] == "STANDBY"
    assert on_standby["mechanical_status"] == "INSPECTION_PASSED", (
        "Moving the service posture must not disturb what the mechanics know, "
        f"got {on_standby['mechanical_status']}"
    )
    check.assert_instant_equals(on_standby["inspection_valid_until"], INSPECTION_EXPIRY)


# ─── The opening decision only speaks to a finished trail ───

def test_opening_a_trail_still_in_preparation_is_refused_on_its_terrain_state(
    api, mountain
):
    """A trail that has only reached preparation is not an admissible subject for an open decision.

    A `decision` of `OPEN` is admissible only from `opening_state` `READY` or `PATROL_HOLD`, and `CLOSE` only from `OPEN` or `PATROL_HOLD`; anything else is refused with `ERR_TERRAIN_STATE_INVALID`.

    Design: Corner/state_machines/opening_decision_open_on_a_prep_area_returns_terrain_state_invalid
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        area_overrides={"name": "Sunbowl"},
    )
    # A second trail on the same lift, walked no further than a cat pass being
    # sent out: no coverage reported, so it never reaches the ready rung.
    second_area = mountain.create_terrain_area(
        state["season_id"],
        state["lift_id"],
        trail_code="T2",
        name="Northwoods",
        terrain_class="BLACK",
        acres=12.0,
        min_open_base_depth_in=30,
    )
    unfinished_pass = mountain.plan_groom(
        second_area["id"],
        cat_route_code="R2",
        sequence_index=1,
        snowcat_unit_code="CAT-2",
        window_start=GROOM_NIGHT_START,
        window_end=GROOM_NIGHT_END,
    )
    mountain.dispatch_groom(unfinished_pass["id"])

    prepared = mountain.area(second_area["id"])
    assert prepared["opening_state"] == "PREP", (
        f"Setup expects the second trail in preparation, got {prepared['opening_state']}"
    )

    response = api.decide_opening(
        second_area["id"],
        payloads.opening_decision_payload("OPEN", note="too early"),
        DIRECTOR_HEADERS,
    )
    validate_error(response, errors.ERR_TERRAIN_STATE_INVALID, 409)

    after = mountain.area(second_area["id"])
    assert after["opening_state"] == "PREP", (
        f"The refused decision must change nothing, got {after['opening_state']}"
    )
    check.assert_version_unchanged(prepared, after)

    # The first trail is still the only thing open on the hill.
    season_row = mountain.season(state["season_id"])
    check.assert_integer(season_row["open_area_count"], 1)
    assert mountain.area(state["area_id"])["opening_state"] == "OPEN"


# ─── A finished cat pass is finished ───

def test_reporting_a_second_set_of_passes_on_a_finished_cat_task_is_refused(api, mountain):
    """Once a cat pass is signed off, a second completion report is refused and the recorded work stands.

    Attempting to dispatch a task that is not `PLANNED` or `DEFERRED`, or to complete a task that is not `DISPATCHED`, is refused with `ERR_WORKFLOW_STATE_INVALID`.

    Design: Corner/state_machines/completing_an_already_completed_grooming_task_returns_workflow_state_invalid
    """
    season = mountain.create_season()
    lift = mountain.create_lift(
        season["id"], wind_hold_threshold_mph=WIND_HOLD_THRESHOLD_MPH
    )
    area = mountain.create_terrain_area(season["id"], lift["id"], name="Sunbowl")
    task = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start=GROOM_NIGHT_START,
        window_end=GROOM_NIGHT_END,
    )
    mountain.dispatch_groom(task["id"])
    mountain.complete_groom(task["id"], passes_completed=20)

    finished = mountain.grooming_task(task["id"])
    assert finished["state"] == "COMPLETED", (
        f"Setup expects the pass signed off, got {finished['state']}"
    )
    # Twenty passes across eighteen acres settle at 83.3 per cent coverage.
    assert check.expected_coverage_pct(20, 18.0) == 83.3, (
        "Setup expects twenty passes to report 83.3 per cent coverage"
    )
    check.assert_one_decimal(finished["coverage_pct"], 83.3)
    groomed_area = mountain.area(area["id"])

    response = api.complete_grooming_task(
        task["id"], payloads.grooming_completion_payload(60), GROOMING_HEADERS
    )
    validate_error(response, errors.ERR_WORKFLOW_STATE_INVALID, 409)

    after_task = mountain.grooming_task(task["id"])
    assert after_task["state"] == "COMPLETED"
    check.assert_integer(after_task["passes_completed"], 20)
    check.assert_one_decimal(after_task["coverage_pct"], 83.3)
    check.assert_version_unchanged(finished, after_task)

    # The replayed sixty passes must not be allowed to move the trail either.
    after_area = mountain.area(area["id"])
    check.assert_one_decimal(after_area["groom_coverage_pct"], 83.3)
    assert after_area["groom_ready"] is True
    check.assert_instant_equals(after_area["last_groomed_at"], OPENING_INSTANT)
    check.assert_version_unchanged(groomed_area, after_area)


# ─── A metered snowmaking session settles once ───

def test_asking_a_finished_snowmaking_session_to_finish_again_is_refused(api, mountain):
    """A completed session is closed to further status requests and its meter readings are final.

    Any other request — asking for `PAUSED` straight from `SCHEDULED`, or touching a finished session — is refused with `ERR_SESSION_STATE_INVALID`.

    Design: Corner/state_machines/completing_an_already_completed_session_returns_session_state_invalid
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400},
    )
    session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start=SESSION_WINDOW_START,
        window_end=SESSION_WINDOW_END,
        gun_count=30,
        gpm=1200,
    )
    # The guns run from the opening instant until six o'clock: six metered hours.
    mountain.drive_session(session["id"], "RUNNING")
    mountain.set_clock("2026-08-01T06:00:00Z")
    mountain.drive_session(session["id"], "COMPLETED")

    finished = mountain.session(session["id"])
    assert finished["state"] == "COMPLETED", (
        f"Setup expects the session settled, got {finished['state']}"
    )
    metered_water = check.expected_water_af(1200, 360)
    assert metered_water == 1.326, (
        f"Setup expects 1.326 acre-feet drawn, computed {metered_water}"
    )

    response = api.set_session_status(
        session["id"], payloads.session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
    )
    validate_error(response, errors.ERR_SESSION_STATE_INVALID, 409)

    after = mountain.session(session["id"])
    assert after["state"] == "COMPLETED"
    check.assert_integer(after["accumulated_run_minutes"], 360)
    check.assert_water_af(after["water_af_actual"], 1.326)
    check.assert_number_equals(after["snow_yield_factor"], 0.85)
    check.assert_water_af(after["snow_swe_af"], 1.127)
    check.assert_energy_kwh(after["energy_kwh"], 822.120)
    check.assert_usd(after["energy_cost_usd"], 106.20)
    assert after["demand_surcharge_applied"] is False
    check.assert_version_unchanged(finished, after)

    # Nothing was drawn or spent twice on the season's ledger.
    season_row = mountain.season(state["season_id"])
    check.assert_water_af(season_row["water_used_af"], 1.326)
    check.assert_water_af(season_row["water_reserved_af"], 0.000)
    check.assert_water_af(season_row["snow_produced_swe_af"], 1.127)

    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], DIRECTOR_HEADERS)
    )
    check.assert_water_af(rollup["water_used_af"], 1.326)
    check.assert_water_af(rollup["water_reserved_af"], 0.000)
    check.assert_water_af(rollup["water_right_remaining_af"], 248.674)
    check.assert_water_af(rollup["snow_produced_swe_af"], 1.127)
    check.assert_usd(rollup["energy_cost_total_usd"], 106.20)
    check.assert_integer(rollup["completed_session_count"], 1)
    check.assert_water_ledger_identity(season_row, 248.674)


# ─── A sign-off that finds the slope more dangerous than it was ───

def test_signing_off_a_mission_at_high_hazard_extends_the_hold_and_pulls_the_trail_back(
    api, mountain
):
    """A sign-off carrying a high rating extends the hold, voids the clearance and pushes the open trail onto a patrol hold.

    A `hazard_rating_post` of `CONSIDERABLE`, `HIGH` or `EXTREME` moves the mission `EXECUTED → HOLD_EXTENDED` instead, still stamping `cleared_at` and recording the rating, but setting the area's `mitigation_clearance_expires_at` to null and pushing the area `OPEN → PATROL_HOLD` if it happened to be open.

    Design: Corner/state_machines/clearing_a_mission_with_high_hazard_extends_the_hold_and_drops_the_open_area
    """
    state = mountain.ready_area(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        area_overrides={"avalanche_terrain": True},
        blaster_certified=True,
    )
    executing_patroller, clearing_patroller = state["patroller_ids"][:2]

    # A ski cut signed off at LOW is what gives the avalanche trail a clearance
    # good until eight o'clock, and lets the opening decision through.
    first_mission = mountain.plan_mission(
        state["area_id"],
        route_code="AV-1",
        method="SKI_CUT",
        hazard_rating_pre="CONSIDERABLE",
        planned_charges=0,
    )
    mountain.execute_mission(first_mission["id"], executing_patroller, charges_used=0)
    mountain.clear_mission(first_mission["id"], clearing_patroller, "LOW")

    # A second, explosive mission on the same trail, shot but not yet signed off.
    # Mitigation is never thrown over open terrain, so it is shot while the trail
    # is still off the hill and only signed off once the trail is standing open.
    second_mission = mountain.plan_mission(
        state["area_id"],
        route_code="AV-2",
        method="EXPLOSIVE",
        hazard_rating_pre="HIGH",
        planned_charges=2,
    )
    mountain.execute_mission(second_mission["id"], executing_patroller, charges_used=2)

    day_plan = mountain.create_day_plan(state["season_id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], wind_speed_mph=10.0, wet_bulb_f=22.0)
    mountain.set_lift_status(state["lift_id"], "OPEN")
    mountain.decide_opening(state["area_id"], "OPEN")
    state["day_plan_id"] = day_plan["id"]

    open_area = mountain.area(state["area_id"])
    assert open_area["opening_state"] == "OPEN", (
        f"Setup expects the trail standing open, got {open_area['opening_state']}"
    )
    check.assert_instant_equals(
        open_area["mitigation_clearance_expires_at"], "2026-08-01T08:00:00Z"
    )
    full_plan = mountain.day_plan(state["day_plan_id"])
    assert full_plan["posture"] == "PUBLISHED_FULL", (
        f"Setup expects a full posture, got {full_plan['posture']}"
    )
    season_before = mountain.season(state["season_id"])

    cleared = validate_success(
        api.clear_mission(
            second_mission["id"],
            payloads.mission_clear_payload("HIGH"),
            make_patroller_headers(clearing_patroller),
        )
    )
    assert cleared["state"] == "HOLD_EXTENDED", (
        f"A HIGH rating extends the hold rather than clearing, got {cleared['state']}"
    )
    assert cleared["hazard_rating_post"] == "HIGH"
    check.assert_instant_equals(cleared["cleared_at"], OPENING_INSTANT)
    assert cleared["cleared_by_patroller_id"] == clearing_patroller
    check.assert_integer(cleared["charges_used"], 2)
    check.assert_integer(cleared["road_closure_minutes"], 40)
    assert check.expected_road_closure_minutes(2) == 40, (
        "Two charges close the mitigation road for forty minutes"
    )

    held_area = mountain.area(state["area_id"])
    assert held_area["mitigation_clearance_expires_at"] is None, (
        "An extended hold voids the trail's clearance, got "
        f"{held_area['mitigation_clearance_expires_at']}"
    )
    assert held_area["opening_state"] == "PATROL_HOLD"
    check.assert_versions_advanced(open_area, held_area)

    partial_plan = mountain.day_plan(state["day_plan_id"])
    assert partial_plan["posture"] == "PUBLISHED_PARTIAL"
    check.assert_integer(partial_plan["open_terrain_count"], 0)
    check.assert_one_decimal(partial_plan["terrain_open_acres"], 0.0)
    check.assert_integer(partial_plan["open_lift_capacity_pph"], 1800)
    check.assert_integer(partial_plan["raw_ccc"], 1080)
    check.assert_integer(partial_plan["guest_capacity"], 1080)
    check.assert_versions_advanced(full_plan, partial_plan)

    season_after = mountain.season(state["season_id"])
    check.assert_integer(season_after["open_area_count"], 0)
    check.assert_versions_advanced(season_before, season_after)

    # The earlier sign-off is untouched by the later one.
    assert mountain.mission(first_mission["id"])["state"] == "CLEARED"


# ─── Who may sign a mission off, and in what order that is judged ───

def test_the_shooter_is_refused_before_an_undercertified_patroller_is_judged(api, mountain):
    """A sign-off is tested for a conflict of interest before the signer's certification is considered.

    The clearing `Patroller` must not be the patroller who executed it — a matching `X-User-ID` is refused with `ERR_SOD_VIOLATION` — must be on duty, and must carry a `cert_level` of `EMT` or `PARAMEDIC`, with `BASIC` and `OEC` refused as `ERR_PATROLLER_CERT_INSUFFICIENT`.

    Design: Corner/state_machines/mission_clear_enforces_segregation_of_duties_before_the_cert_requirement
    """
    season = mountain.create_season()
    lift = mountain.create_lift(
        season["id"], wind_hold_threshold_mph=WIND_HOLD_THRESHOLD_MPH
    )
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"], lift["id"], name="Sunbowl", avalanche_terrain=True
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    shooter, signer = (
        row["id"]
        for row in mountain.staff_patrol(
            season["id"], area["id"], count=2, blaster_certified=True
        )
    )
    # A third patroller on duty on the same trail, certified only to BASIC.
    undercertified = mountain.create_patroller(
        season["id"],
        patroller_code="P3",
        cert_level="BASIC",
        on_duty=True,
        blaster_certified=False,
        assigned_terrain_area_id=area["id"],
    )

    mission = mountain.plan_mission(
        area["id"],
        route_code="AV-1",
        method="SKI_CUT",
        hazard_rating_pre="CONSIDERABLE",
        planned_charges=0,
    )
    mountain.execute_mission(mission["id"], shooter, charges_used=0)
    executed = mountain.mission(mission["id"])
    assert executed["state"] == "EXECUTED", (
        f"Setup expects the ski cut shot but unsigned, got {executed['state']}"
    )

    # The patroller who cut the slope may not sign off on his own work.
    validate_error(
        api.clear_mission(
            mission["id"],
            payloads.mission_clear_payload("LOW"),
            make_patroller_headers(shooter),
        ),
        errors.ERR_SOD_VIOLATION,
        409,
    )
    still_executed = mountain.mission(mission["id"])
    assert still_executed["state"] == "EXECUTED"
    check.assert_version_unchanged(executed, still_executed)

    # A different patroller clears the conflict test but not the certification.
    validate_error(
        api.clear_mission(
            mission["id"],
            payloads.mission_clear_payload("LOW"),
            make_patroller_headers(undercertified["id"]),
        ),
        errors.ERR_PATROLLER_CERT_INSUFFICIENT,
        422,
    )
    assert mountain.mission(mission["id"])["state"] == "EXECUTED"

    # A second patroller carrying PARAMEDIC satisfies both rules.
    cleared = validate_success(
        api.clear_mission(
            mission["id"],
            payloads.mission_clear_payload("LOW"),
            make_patroller_headers(signer),
        )
    )
    assert cleared["state"] == "CLEARED"
    assert cleared["cleared_by_patroller_id"] == signer
    check.assert_instant_equals(
        mountain.area(area["id"])["mitigation_clearance_expires_at"],
        "2026-08-01T08:00:00Z",
    )


# ─── The last close of the season ───

def test_the_final_day_close_takes_the_season_the_terrain_the_work_and_the_guests_down(
    api, mountain
):
    """A final close ends the season and every unfinished piece of work under it, releasing the reserved water.

    A `season_final` of true additionally tears the season down for good: the `SeasonConfig` moves to `CLOSED`, every terrain area to `SEASON_CLOSED`, every grooming task not already in a terminal state to `CANCELLED`, every snowmaking session not already terminal to `ABORTED` with `abort_reason` `SEASON_CLOSE` and its reserved water released back to the season, and every mission still `PLANNED` or `EXECUTED` to `ABORTED`.

    Design: Corner/state_machines/close_day_with_season_final_cascades_areas_tasks_sessions_and_reservations
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400, "gun_count": 40},
    )
    # Water committed to a session the guns never started.
    session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start=SESSION_WINDOW_START,
        window_end=SESSION_WINDOW_END,
        gun_count=30,
        gpm=1200,
    )
    reserved = check.expected_water_af(1200, 420)
    assert reserved == 1.547, (
        f"Setup expects a 1.547 acre-foot reservation, computed {reserved}"
    )
    # A late-evening cat pass that was never dispatched.
    late_pass = mountain.plan_groom(
        state["area_id"],
        cat_route_code="R2",
        sequence_index=1,
        snowcat_unit_code="CAT-2",
        window_start="2026-08-01T20:00:00Z",
        window_end="2026-08-01T23:00:00Z",
    )
    # A season-pass party holding two stalls for the day.
    reservation = mountain.create_reservation(
        state["day_plan_id"],
        party_code="PC-1",
        pass_type="SEASON",
        party_size=10,
        vehicle_count=2,
    )
    assert reservation["state"] == "CONFIRMED", (
        f"Setup expects the party admitted, got {reservation['state']}"
    )
    # The overnight groom that made the trail ready is already finished, and a
    # final close must leave a terminal row exactly as it found it.
    tasks, _ = validate_paginated(
        api.list_grooming_tasks(GROOMING_HEADERS, terrain_area_id=state["area_id"])
    )
    boot_pass = check.find_row(tasks, cat_route_code="R1")
    assert boot_pass["state"] == "COMPLETED"

    season_before = mountain.season(state["season_id"])
    check.assert_water_af(season_before["water_reserved_af"], 1.547)

    closed_plan = validate_success(
        api.close_day(
            state["day_plan_id"], DIRECTOR_HEADERS, payloads.close_day_payload(True)
        )
    )
    assert closed_plan["posture"] == "DAY_CLOSED"
    check.assert_integer(closed_plan["admitted_guest_count"], 0)
    check.assert_integer(closed_plan["parking_stalls_used"], 0)
    check.assert_integer(closed_plan["open_terrain_count"], 0)

    closed_area = mountain.area(state["area_id"])
    assert closed_area["opening_state"] == "SEASON_CLOSED"
    check.assert_versions_advanced(state["area"], closed_area)

    aborted_session = mountain.session(session["id"])
    assert aborted_session["state"] == "ABORTED"
    assert aborted_session["abort_reason"] == "SEASON_CLOSE"
    check.assert_water_af(aborted_session["water_af_actual"], 0.000)
    check.assert_usd(aborted_session["energy_cost_usd"], 0.00)

    assert mountain.grooming_task(late_pass["id"])["state"] == "CANCELLED"
    finished_pass = mountain.grooming_task(boot_pass["id"])
    assert finished_pass["state"] == "COMPLETED", (
        "A pass already signed off is terminal and must not be cancelled, got "
        f"{finished_pass['state']}"
    )
    check.assert_integer(finished_pass["passes_completed"], 20)
    check.assert_version_unchanged(boot_pass, finished_pass)

    released = mountain.reservation(reservation["id"])
    assert released["state"] == "RELEASED"
    check.assert_integer(released["allocated_stalls"], 0)

    season_after = mountain.season(state["season_id"])
    assert season_after["season_state"] == "CLOSED"
    check.assert_water_af(season_after["water_reserved_af"], 0.000)
    check.assert_water_af(season_after["water_used_af"], 0.000)
    check.assert_integer(season_after["open_area_count"], 0)
    check.assert_water_ledger_identity(season_after)

    # The lift the trail hung from is shut with it.
    assert mountain.lift(state["lift_id"])["service_status"] == "CLOSED"


# ─── Dismantling a terrain park ───

def test_submitting_an_empty_feature_set_tears_the_park_down_and_pulls_it_off_the_hill(
    api, mountain
):
    """An empty feature build closes the park, voids its inspection and pushes the open park trail onto a patrol hold.

    Submitting an **empty** `features` array from `PARK_INSPECTED` is how a park is torn down: `park_state` moves `PARK_INSPECTED → PARK_CLOSED`, `park_feature_count` returns to 0, `park_risk_score` returns to 0.0, `park_inspected_by_user_id` is nulled, and if the area was `OPEN` with `terrain_class` `PARK` it is pushed onto `PATROL_HOLD`.

    Design: Corner/state_machines/tearing_down_the_park_drops_the_open_park_area_to_patrol_hold
    """
    state = mountain.ready_area(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        area_overrides={
            "trail_code": "TP",
            "name": "Main Park",
            "terrain_class": "PARK",
            "acres": 18.0,
            "min_open_base_depth_in": 30,
        },
    )
    # A park trail only reaches READY once its features are in and signed off, so
    # the build and the inspection precede the publication of the operating day.
    features = payloads.park_build_payload()["features"]
    mountain.build_park(state["area_id"])
    mountain.inspect_park(state["area_id"], state["patroller_ids"][0])

    day_plan = mountain.create_day_plan(state["season_id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], wind_speed_mph=10.0, wet_bulb_f=22.0)
    mountain.set_lift_status(state["lift_id"], "OPEN")
    mountain.decide_opening(state["area_id"], "OPEN")
    state["day_plan_id"] = day_plan["id"]

    standing_park = mountain.area(state["area_id"])
    assert standing_park["park_state"] == "PARK_INSPECTED", (
        f"Setup expects a signed-off park, got {standing_park['park_state']}"
    )
    assert check.expected_park_risk_score(features) == 50.6, (
        "Setup expects the six-feature build to score 50.6"
    )
    check.assert_one_decimal(standing_park["park_risk_score"], 50.6)
    check.assert_integer(standing_park["park_feature_count"], 6)
    assert standing_park["opening_state"] == "OPEN"
    full_plan = mountain.day_plan(state["day_plan_id"])
    assert full_plan["posture"] == "PUBLISHED_FULL", (
        f"Setup expects a full posture, got {full_plan['posture']}"
    )

    torn_down = validate_success(
        api.build_park(state["area_id"], payloads.park_build_payload([]), GROOMING_HEADERS)
    )
    assert torn_down["park_state"] == "PARK_CLOSED"
    check.assert_integer(torn_down["park_feature_count"], 0)
    check.assert_one_decimal(torn_down["park_risk_score"], 0.0)
    assert torn_down["park_inspected_by_user_id"] is None, (
        "Tearing the park down voids the sign-off, got "
        f"{torn_down['park_inspected_by_user_id']}"
    )
    assert torn_down["park_built_by_user_id"] == GROOMING_USER_ID
    assert torn_down["opening_state"] == "PATROL_HOLD", (
        "A park trail standing open when its features come out is pushed onto a "
        f"patrol hold in the same response, got {torn_down['opening_state']}"
    )
    check.assert_versions_advanced(standing_park, torn_down)

    partial_plan = mountain.day_plan(state["day_plan_id"])
    assert partial_plan["posture"] == "PUBLISHED_PARTIAL"
    check.assert_integer(partial_plan["open_terrain_count"], 0)
    check.assert_one_decimal(partial_plan["terrain_open_acres"], 0.0)
    check.assert_integer(partial_plan["guest_capacity"], 1080)
    check.assert_versions_advanced(full_plan, partial_plan)

    check.assert_integer(mountain.season(state["season_id"])["open_area_count"], 0)


# ─── The five-mile-per-hour band under a wind hold ───

def test_a_wind_hold_release_is_refused_while_the_anemometer_sits_inside_the_band(
    api, mountain
):
    """A lift held for wind will not restart until the wind falls a full five miles per hour below the figure that held it.

    A release attempted while the wind sits inside that band — above the release figure but at or below the hold threshold — is refused with `ERR_WIND_ABOVE_RELEASE_THRESHOLD`.

    Design: Corner/state_machines/wind_hold_release_inside_the_hysteresis_band_is_rejected_then_recovers_at_the_boundary
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
    )
    # Fifty-five miles per hour is above the lift's forty, so the lift is held
    # and the trail it serves comes off the hill with it.
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=55.0, wet_bulb_f=22.0)
    held_lift = mountain.lift(state["lift_id"])
    assert held_lift["service_status"] == "WIND_HOLD", (
        f"Setup expects the lift held for wind, got {held_lift['service_status']}"
    )
    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    held_plan = mountain.day_plan(state["day_plan_id"])
    assert held_plan["posture"] == "PUBLISHED_PARTIAL"
    check.assert_integer(held_plan["guest_capacity"], 0)

    # Asking for the lift back while the gale still blows.
    validate_error(
        api.set_lift_service_status(
            state["lift_id"], payloads.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        ),
        errors.ERR_WIND_ABOVE_RELEASE_THRESHOLD,
        422,
    )
    assert mountain.lift(state["lift_id"])["service_status"] == "WIND_HOLD"

    # The wind eases to thirty-six: below the figure that armed the hold, but
    # still inside the five-mile-per-hour band that governs the release.
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=36.0, wet_bulb_f=22.0)
    easing_lift = mountain.lift(state["lift_id"])
    assert easing_lift["service_status"] == "WIND_HOLD", (
        "A falling anemometer does not restart the lift by itself, got "
        f"{easing_lift['service_status']}"
    )
    easing_plan = mountain.day_plan(state["day_plan_id"])
    assert easing_plan["posture"] == "PUBLISHED_PARTIAL"
    assert mountain.area(state["area_id"])["opening_state"] == "PATROL_HOLD"

    validate_error(
        api.set_lift_service_status(
            state["lift_id"], payloads.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        ),
        errors.ERR_WIND_ABOVE_RELEASE_THRESHOLD,
        422,
    )
    still_held = mountain.lift(state["lift_id"])
    assert still_held["service_status"] == "WIND_HOLD"
    check.assert_instant_equals(still_held["wind_hold_since"], OPENING_INSTANT)
    check.assert_version_unchanged(easing_lift, still_held)
    assert mountain.area(state["area_id"])["opening_state"] == "PATROL_HOLD"


def test_a_wind_hold_release_succeeds_at_the_band_boundary_and_recovers_the_trail(
    api, mountain
):
    """At exactly the release figure the lift restarts, and the trail it serves is re-gated and returned to the hill.

    A successful release sets `service_status` to `OPEN`, sets `wind_hold_since` back to null, and conditionally recovers terrain: every area served by this lift sitting on `PATROL_HOLD` is re-gated against the current clock, those satisfying every opening gate return to `OPEN`, and those that do not simply stay on `PATROL_HOLD`.

    Design: Corner/state_machines/wind_hold_release_inside_the_hysteresis_band_is_rejected_then_recovers_at_the_boundary
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
    )
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=55.0, wet_bulb_f=22.0)
    assert mountain.lift(state["lift_id"])["service_status"] == "WIND_HOLD", (
        "Setup expects the lift held for wind"
    )
    # Thirty-five is exactly forty less the five-mile-per-hour band, so the
    # release is admissible on the boundary itself.
    mountain.post_weather(state["day_plan_id"], wind_speed_mph=35.0, wet_bulb_f=22.0)
    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    held_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_integer(held_plan["guest_capacity"], 0)

    released = validate_success(
        api.set_lift_service_status(
            state["lift_id"], payloads.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert released["service_status"] == "OPEN"
    assert released["wind_hold_since"] is None, (
        f"A successful release clears the hold stamp, got {released['wind_hold_since']}"
    )
    assert released["mechanical_status"] == "INSPECTION_PASSED"

    recovered_area = mountain.area(state["area_id"])
    assert recovered_area["opening_state"] == "OPEN", (
        "The trail still satisfies every opening gate, so the release returns it "
        f"to the hill, got {recovered_area['opening_state']}"
    )
    check.assert_versions_advanced(held_area, recovered_area)

    expected = check.expected_capacity(1800, 18.0)
    assert expected["raw_ccc"] == 1080 and expected["guest_capacity"] == 918, (
        f"The open hill computes to {expected}"
    )
    full_plan = mountain.day_plan(state["day_plan_id"])
    assert full_plan["posture"] == "PUBLISHED_FULL"
    check.assert_integer(full_plan["open_lift_capacity_pph"], 1800)
    check.assert_integer(full_plan["raw_ccc"], 1080)
    check.assert_integer(full_plan["guest_capacity"], 918)
    check.assert_integer(full_plan["non_season_pool"], 642)
    check.assert_one_decimal(full_plan["terrain_open_acres"], 18.0)
    check.assert_versions_advanced(held_plan, full_plan)

    check.assert_integer(mountain.season(state["season_id"])["open_area_count"], 1)


# ─── Letting an operator off shift takes the lift and its terrain with it ───

def test_releasing_an_operator_below_the_required_crew_drops_the_lift_and_its_trail(
    api, mountain
):
    """Releasing one of two operators leaves the lift short-crewed, so it falls to standby and its trail comes off the hill.

    If the recomputed count drops below `required_operator_count` while the lift is `OPEN`, the lift falls `OPEN → STANDBY`, and every terrain area it serves whose `opening_state` is `OPEN` cascades onto `PATROL_HOLD` with the usual downstream grooming and snowmaking consequences.

    Design: Corner/state_machines/releasing_an_operator_below_the_required_count_drops_the_lift_and_the_area
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
    )
    crewed_lift = mountain.lift(state["lift_id"])
    assert crewed_lift["service_status"] == "OPEN", (
        f"Setup expects the lift spinning, got {crewed_lift['service_status']}"
    )
    check.assert_integer(crewed_lift["staffed_operator_count"], 2)
    open_area = mountain.area(state["area_id"])
    assert open_area["opening_state"] == "OPEN"
    full_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_integer(full_plan["guest_capacity"], 918)

    assignments, _ = validate_paginated(
        api.list_lift_staff_assignments(state["lift_id"], LIFT_OPS_HEADERS)
    )
    top_operator = check.find_row(assignments, operator_code="OP-1")
    assert top_operator["state"] == "ASSIGNED", (
        f"Setup expects OP-1 on shift, got {top_operator['state']}"
    )

    released = validate_success(
        api.release_lift_staff_assignment(top_operator["id"], LIFT_OPS_HEADERS)
    )
    assert released["state"] == "RELEASED"
    check.assert_instant_equals(released["released_at"], OPENING_INSTANT)

    short_lift = mountain.lift(state["lift_id"])
    check.assert_integer(short_lift["staffed_operator_count"], 1)
    assert short_lift["service_status"] == "STANDBY", (
        "One operator short of the required crew stops the lift carrying guests, "
        f"got {short_lift['service_status']}"
    )
    assert short_lift["mechanical_status"] == "INSPECTION_PASSED", (
        "A staffing shortfall says nothing about the mechanics, got "
        f"{short_lift['mechanical_status']}"
    )
    check.assert_versions_advanced(crewed_lift, short_lift)

    held_area = mountain.area(state["area_id"])
    assert held_area["opening_state"] == "PATROL_HOLD"
    check.assert_versions_advanced(open_area, held_area)

    empty_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_integer(empty_plan["open_lift_capacity_pph"], 0)
    check.assert_integer(empty_plan["raw_ccc"], 0)
    check.assert_integer(empty_plan["guest_capacity"], 0)
    check.assert_integer(empty_plan["non_season_pool"], 0)
    check.assert_integer(empty_plan["open_terrain_count"], 0)
    check.assert_versions_advanced(full_plan, empty_plan)

    # The shift is already over: letting the same operator off twice is refused.
    validate_error(
        api.release_lift_staff_assignment(top_operator["id"], LIFT_OPS_HEADERS),
        errors.ERR_WORKFLOW_STATE_INVALID,
        409,
    )
    check.assert_integer(mountain.lift(state["lift_id"])["staffed_operator_count"], 1)


# ─── A patroller comes free, and the trail stays shut ───

def test_closing_an_incident_frees_the_patroller_without_reopening_the_trail(api, mountain):
    """Closing an incident returns the responder to available, and the trail their absence closed stays on a patrol hold until the director acts.

    Recovery is again explicit: an area already on `PATROL_HOLD` is not reopened merely because its patroller came free.

    Design: Corner/state_machines/closing_an_incident_returns_the_patroller_without_reopening_the_area
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": WIND_HOLD_THRESHOLD_MPH},
        wind_speed_mph=10.0,
        wet_bulb_f=22.0,
    )
    responder = state["patroller_ids"][0]
    incident = mountain.report_incident(
        state["area_id"],
        reporter_code="LIFTOP-3",
        severity="MINOR",
        location_note="knee injury skier left",
    )
    assert incident["state"] == "REPORTED"

    # Committing one of the trail's two patrollers to the patient is what takes
    # the trail off the hill in the first place.
    dispatched = validate_success(
        api.dispatch_incident(
            incident["id"],
            payloads.incident_dispatch_payload(responder),
            DIRECTOR_HEADERS,
        )
    )
    assert dispatched["state"] == "DISPATCHED"
    assert dispatched["responder_patroller_id"] == responder
    check.assert_integer(dispatched["response_minutes"], 0)

    held_area = mountain.area(state["area_id"])
    check.assert_integer(held_area["assigned_patroller_count"], 1)
    assert held_area["opening_state"] == "PATROL_HOLD", (
        f"Setup expects the trail held for staffing, got {held_area['opening_state']}"
    )
    # The lift is still spinning, so the uphill capacity and raw_ccc are untouched;
    # with no acreage open the crowding density is 0.0 and the density factor 1.00,
    # so guest_capacity tracks raw_ccc rather than collapsing to zero.
    held_plan = mountain.day_plan(state["day_plan_id"])
    check.assert_integer(held_plan["open_terrain_count"], 0)
    check.assert_one_decimal(held_plan["terrain_open_acres"], 0.0)
    check.assert_integer(held_plan["open_lift_capacity_pph"], 1800)
    check.assert_integer(held_plan["raw_ccc"], 1080)
    check.assert_integer(held_plan["guest_capacity"], 1080)

    closed = validate_success(
        api.close_incident(
            incident["id"],
            payloads.incident_close_payload("RELEASED_ON_HILL"),
            make_patroller_headers(responder),
        )
    )
    assert closed["state"] == "CLOSED"
    assert closed["disposition"] == "RELEASED_ON_HILL"
    assert closed["transport_mode"] is None, (
        "A patient released on the hill was never transported, got "
        f"{closed['transport_mode']}"
    )
    check.assert_instant_equals(closed["closed_at"], OPENING_INSTANT)

    freed_patroller = mountain.patroller(responder)
    assert freed_patroller["status"] == "AVAILABLE"
    assert freed_patroller["on_duty"] is True

    recovered_count_area = mountain.area(state["area_id"])
    check.assert_integer(recovered_count_area["assigned_patroller_count"], 2)
    assert recovered_count_area["opening_state"] == "PATROL_HOLD", (
        "The staffing gate holds again, but the trail is not reopened by the "
        f"patroller coming free, got {recovered_count_area['opening_state']}"
    )

    # Only the director's explicit decision puts the trail back on the hill.
    reopened = validate_success(
        api.decide_opening(
            state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN"

    full_plan = mountain.day_plan(state["day_plan_id"])
    assert full_plan["posture"] == "PUBLISHED_FULL"
    check.assert_integer(full_plan["guest_capacity"], 918)
    check.assert_integer(full_plan["open_terrain_count"], 1)
