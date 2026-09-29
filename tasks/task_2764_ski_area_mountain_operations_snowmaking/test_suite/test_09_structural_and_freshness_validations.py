"""Shapes the mountain refuses to accept, and the freshness clocks that run out on the instant.

Half of a ski area's paperwork is structural: a stake reading may not be dated
into the future, a snowmaking window must run forwards, a season's price
schedule must cover the whole twenty-four hours with no hole and no overlap, a
winch pass must name the tree it is anchored to, and a trail code has to be
unique inside its own season while being free to repeat in the next one. These
tests submit the malformed shape, pin the code the mountain reports, and then
submit the corrected shape against exactly the same setup so the refusal is
shown to be about the shape and nothing else.

The other half is time. An avalanche clearance, a groomer's pass and a lift's
mechanical inspection each stay good for a fixed number of hours and then stop
counting, and the contract draws that line with a strict comparison: the
clearance is current while the logical clock is *before* the expiry instant, so
standing the clock exactly on the instant expires it. These tests park the
clock on the last second the currency holds, then on the instant itself, and
show that only a fresh mission, a fresh cat pass or a fresh inspection reopens
the trail.
"""

from prd_bench_local_runner.testing import (
    get_success_data,
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
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
)

# The instants these recipes park the logical clock on.
SIX_IN_THE_MORNING = "2026-08-01T06:00:00Z"
ONE_SECOND_LATER = "2026-08-01T06:00:01Z"
ONE_SECOND_EARLIER = "2026-08-01T05:59:59Z"


# ─── A stake reading may not be dated ahead of the clock ───

def test_a_stake_reading_dated_one_second_after_the_logical_clock_is_refused(api, mountain):
    """A snow stake reading dated even one second ahead of the mountain's logical clock is refused, while the same instant as the clock is accepted.

    A reading whose `measured_at` falls after the logical clock is refused with `ERR_READING_TIMESTAMP_FUTURE`.

    Design: Corner/validations/a_reading_measured_after_the_logical_clock_is_rejected_at_the_second
    """
    mountain.set_clock(SIX_IN_THE_MORNING)
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"])

    one_second_ahead = api.record_snow_depth_reading(
        area["id"],
        payloads.snow_depth_reading_payload(
            stake_code="S1", depth_in=40.0, measured_at=ONE_SECOND_LATER
        ),
        GROOMING_HEADERS,
    )
    validate_error(one_second_ahead, errors.ERR_READING_TIMESTAMP_FUTURE)

    # A refused reading leaves the trail's settled base exactly as a brand new
    # area starts: nothing measured, no stakes counted.
    untouched = mountain.area(area["id"])
    check.assert_one_decimal(untouched["base_depth_in"], 0.0)
    check.assert_integer(untouched["base_depth_stake_count"], 0)

    # The very same wall-clock second as the logical clock is not "after" it.
    on_the_second = api.record_snow_depth_reading(
        area["id"],
        payloads.snow_depth_reading_payload(
            stake_code="S1", depth_in=40.0, measured_at=SIX_IN_THE_MORNING
        ),
        GROOMING_HEADERS,
    )
    validate_success(on_the_second, 201)

    a_second_in_the_past = api.record_snow_depth_reading(
        area["id"],
        payloads.snow_depth_reading_payload(
            stake_code="S2", depth_in=36.0, measured_at=ONE_SECOND_EARLIER
        ),
        GROOMING_HEADERS,
    )
    validate_success(a_second_in_the_past, 201)

    # Two accepted stakes, so the mean-of-stakes base is (40.0 + 36.0) / 2.
    settled = mountain.area(area["id"])
    check.assert_one_decimal(settled["base_depth_in"], 38.0)
    check.assert_integer(settled["base_depth_stake_count"], 2)

    rows, meta = validate_paginated(
        api.list_snow_depth_readings(area["id"], DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 2, (
        "The future-dated reading must never have been stored, so the trail "
        f"should hold exactly two readings, got {meta['total_count']}"
    )
    assert len(rows) == 2, (
        f"Expected two stored readings on the page, got {len(rows)}"
    )


# ─── A snowmaking window has to run forwards ───

def test_a_snowmaking_window_that_does_not_run_forwards_is_refused_before_any_water_is_reserved(
    api, mountain
):
    """A snowmaking session whose window ends before it starts, or ends exactly when it starts, is refused without touching the water ledger or the trail.

    A window whose start is not strictly before its end is refused with `ERR_WINDOW_INVALID`.

    Design: Corner/validations/a_session_window_that_is_not_strictly_increasing_is_rejected_before_any_capacity_work
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"])
    pump_house = mountain.create_pump_house(season["id"])
    observed_version = mountain.area_version(area["id"])

    reversed_window = api.create_session(
        payloads.session_payload(
            area["id"],
            pump_house["id"],
            observed_version,
            window_start="2026-08-01T12:00:00Z",
            window_end="2026-08-01T05:00:00Z",
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(reversed_window, errors.ERR_WINDOW_INVALID)

    zero_length_window = api.create_session(
        payloads.session_payload(
            area["id"],
            pump_house["id"],
            observed_version,
            window_start="2026-08-01T05:00:00Z",
            window_end="2026-08-01T05:00:00Z",
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(zero_length_window, errors.ERR_WINDOW_INVALID)

    # Neither refusal reserved water, and neither moved the trail off CLOSED or
    # bumped the version the caller is still holding.
    ledger = mountain.season(season["id"])
    check.assert_water_af(ledger["water_reserved_af"], 0.000)
    check.assert_water_af(ledger["water_used_af"], 0.000)
    still_closed = mountain.area(area["id"])
    assert still_closed["opening_state"] == "CLOSED", (
        f"A refused session must leave the trail CLOSED, got {still_closed['opening_state']}"
    )
    check.assert_integer(still_closed["version"], observed_version)

    # The same payload with the window the right way round is accepted, and the
    # seven-hour span at 1200 gpm is what reserves water.
    forwards = api.create_session(
        payloads.session_payload(
            area["id"],
            pump_house["id"],
            observed_version,
            window_start="2026-08-01T05:00:00Z",
            window_end="2026-08-01T12:00:00Z",
        ),
        SNOWMAKING_HEADERS,
    )
    session = validate_success(forwards, 201)
    check.assert_integer(session["planned_minutes"], 420)
    check.assert_water_af(session["water_af_reserved"], 1.547)
    assert session["state"] == "SCHEDULED", (
        f"A newly scheduled session begins in SCHEDULED, got {session['state']}"
    )

    prepped = mountain.area(area["id"])
    assert prepped["opening_state"] == "PREP", (
        f"Scheduling snowmaking moves the trail CLOSED to PREP, got {prepped['opening_state']}"
    )
    committed = mountain.pump_house(pump_house["id"])
    check.assert_integer(committed["peak_committed_gpm"], 1200)


# ─── The price schedule must cover the whole day, once ───

def test_an_energy_price_schedule_that_does_not_tile_the_whole_day_is_rejected(api, mountain):
    """A season's price schedule is refused when it leaves a gap, overlaps itself, starts after hour 0 or stops short of hour 24, and the label stays free for the corrected submission.

    A submitted set with a hole, an overlap, or a missing day-end is rejected with `ERR_ENERGY_WINDOW_COVERAGE_GAP`.

    Taken together and sorted by start hour, the entries must tile the whole day exactly: the first must start at hour 0, the last must end at hour 24, consecutive entries must touch with no gap, and no two may overlap.

    Design: Corner/validations/energy_windows_must_tile_the_whole_day_exactly_once
    """
    def schedule(**edits):
        """The canonical four-entry day, with one entry's hours edited."""
        windows = payloads.energy_windows_full_day()
        for code, (start_hour, end_hour) in edits.items():
            for window in windows:
                if window["code"] == code:
                    window["start_hour_utc"] = start_hour
                    window["end_hour_utc"] = end_hour
        return windows

    # A hole between hour 9 and hour 10, left by the on-peak entry starting late.
    with_a_hole = api.create_season(
        payloads.season_payload(energy_windows=schedule(ON_1=(10, 21))),
        DIRECTOR_HEADERS,
    )
    validate_error(with_a_hole, errors.ERR_ENERGY_WINDOW_COVERAGE_GAP)

    # An overlap: the mid-peak entry reaches back into the off-peak entry.
    with_an_overlap = api.create_season(
        payloads.season_payload(energy_windows=schedule(MID_1=(5, 9))),
        DIRECTOR_HEADERS,
    )
    validate_error(with_an_overlap, errors.ERR_ENERGY_WINDOW_COVERAGE_GAP)

    # The first entry starts at hour 1, so the first hour of the day is uncovered.
    starting_late = api.create_season(
        payloads.season_payload(energy_windows=schedule(OFF_1=(1, 6))),
        DIRECTOR_HEADERS,
    )
    validate_error(starting_late, errors.ERR_ENERGY_WINDOW_COVERAGE_GAP)

    # The last entry stops at hour 23, so the day-end is missing.
    stopping_short = api.create_season(
        payloads.season_payload(energy_windows=schedule(MID_2=(21, 23))),
        DIRECTOR_HEADERS,
    )
    validate_error(stopping_short, errors.ERR_ENERGY_WINDOW_COVERAGE_GAP)

    # Four refusals stored nothing, so the label "2026-27" is still unclaimed and
    # the corrected schedule is accepted under it.
    corrected = api.create_season(
        payloads.season_payload(energy_windows=payloads.energy_windows_full_day()),
        DIRECTOR_HEADERS,
    )
    season = validate_success(corrected, 201)
    assert season["season_label"] == "2026-27", (
        f"Expected the season label to be accepted as submitted, got {season['season_label']}"
    )
    assert season["season_state"] == "PRESEASON", (
        f"A newly created season starts in PRESEASON, got {season['season_state']}"
    )
    check.assert_water_af(season["water_reserved_af"], 0.000)
    check.assert_water_af(season["water_used_af"], 0.000)
    check.assert_integer(season["open_area_count"], 0)


# ─── A winch pass has to name its anchor ───

def test_a_winch_grooming_pass_without_an_anchor_code_is_refused(api, mountain):
    """A grooming task that asks for the winch must name the anchor point it will be tied to, while an ordinary pass needs no anchor at all.

    Winch grooming is requested with `winch_required`, which defaults to false; when it is true a non-empty `winch_anchor_code` naming the anchor point must accompany it, and its absence is refused with `ERR_WINCH_ANCHOR_REQUIRED`.

    Design: Corner/validations/a_winched_grooming_task_must_declare_an_anchor_code
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"])

    anchorless_winch = api.create_grooming_task(
        payloads.grooming_task_payload(
            area["id"], sequence_index=1, winch_required=True
        ),
        GROOMING_HEADERS,
    )
    validate_error(anchorless_winch, errors.ERR_WINCH_ANCHOR_REQUIRED)

    # The refusal freed nothing up, because it stored nothing: sequence index 1
    # on route R1 is still available to the same pass without the winch.
    without_the_winch = api.create_grooming_task(
        payloads.grooming_task_payload(
            area["id"], sequence_index=1, winch_required=False
        ),
        GROOMING_HEADERS,
    )
    ordinary_pass = validate_success(without_the_winch, 201)
    assert ordinary_pass["winch_required"] is False, (
        f"Expected an ordinary pass to carry winch_required false, got {ordinary_pass['winch_required']}"
    )
    assert ordinary_pass["state"] == "PLANNED", (
        f"A new task begins in PLANNED, got {ordinary_pass['state']}"
    )

    with_the_anchor = api.create_grooming_task(
        payloads.grooming_task_payload(
            area["id"],
            sequence_index=2,
            winch_required=True,
            winch_anchor_code="ANC-4",
        ),
        GROOMING_HEADERS,
    )
    winched_pass = validate_success(with_the_anchor, 201)
    assert winched_pass["winch_required"] is True, (
        f"Expected the winched pass to carry winch_required true, got {winched_pass['winch_required']}"
    )
    assert winched_pass["winch_anchor_code"] == "ANC-4", (
        f"Expected the anchor code to be stored as submitted, got {winched_pass['winch_anchor_code']}"
    )

    rows, meta = validate_paginated(
        api.list_grooming_tasks(GROOMING_HEADERS, terrain_area_id=area["id"])
    )
    assert meta["total_count"] == 2, (
        "The anchorless winch request must never have been stored, so the trail "
        f"should hold exactly two planned passes, got {meta['total_count']}"
    )
    assert len(rows) == 2, f"Expected two planned passes on the page, got {len(rows)}"


# ─── Codes are unique inside their season, not across the mountain ───

def test_trail_lift_and_operating_day_codes_repeat_freely_in_a_second_season(api, mountain):
    """A trail code, a lift code and an operating date collide only inside their own season, while the season label is the one code that must be unique across every season ever created.

    A duplicate date within one season is refused with `ERR_DUPLICATE_CODE`.

    A registration names its `season_id`, a `lift_code` unique within that season (for example "L1"), a display `name`, a `lift_type` of `SURFACE`, `FIXED_GRIP`, `DETACHABLE` or `GONDOLA`, a `wind_hold_threshold_mph` greater than zero and carried to one decimal place, and an `hourly_capacity_pph` of at least 1 describing uphill capacity in people per hour while the lift is running.

    Design: Corner/validations/code_uniqueness_is_scoped_per_season_not_globally
    """
    this_winter = mountain.create_season(season_label="2026-27")
    summit_express = mountain.create_lift(this_winter["id"], lift_code="L1")
    mountain.create_terrain_area(this_winter["id"], summit_express["id"], trail_code="T1")
    mountain.create_day_plan(this_winter["id"], operating_date="2026-08-01")

    next_winter = mountain.create_season(season_label="2027-28")

    # Inside one season, each of these codes is already taken.
    same_trail_code = api.create_terrain_area(
        payloads.terrain_area_payload(
            this_winter["id"], summit_express["id"], trail_code="T1", name="Lower Bowl Repeat"
        ),
        DIRECTOR_HEADERS,
    )
    validate_error(same_trail_code, errors.ERR_DUPLICATE_CODE)

    same_operating_date = api.create_day_plan(
        payloads.day_plan_payload(this_winter["id"], operating_date="2026-08-01"),
        DIRECTOR_HEADERS,
    )
    validate_error(same_operating_date, errors.ERR_DUPLICATE_CODE)

    # In the next season every one of those codes is free again.
    next_winters_lift = api.create_lift(
        payloads.lift_payload(next_winter["id"], lift_code="L1"), LIFT_OPS_HEADERS
    )
    reused_lift_code = validate_success(next_winters_lift, 201)
    assert reused_lift_code["lift_code"] == "L1", (
        f"Expected the lift code to be reusable in a new season, got {reused_lift_code['lift_code']}"
    )

    next_winters_trail = api.create_terrain_area(
        payloads.terrain_area_payload(
            next_winter["id"], reused_lift_code["id"], trail_code="T1"
        ),
        DIRECTOR_HEADERS,
    )
    reused_trail_code = validate_success(next_winters_trail, 201)
    assert reused_trail_code["trail_code"] == "T1", (
        f"Expected the trail code to be reusable in a new season, got {reused_trail_code['trail_code']}"
    )

    next_winters_day = api.create_day_plan(
        payloads.day_plan_payload(next_winter["id"], operating_date="2026-08-01"),
        DIRECTOR_HEADERS,
    )
    reused_operating_date = validate_success(next_winters_day, 201)
    assert reused_operating_date["operating_date"] == "2026-08-01", (
        "Expected the operating date to be reusable in a new season, got "
        f"{reused_operating_date['operating_date']}"
    )

    # The season label is the exception: it is scoped to the whole mountain.
    label_already_used = api.create_season(
        payloads.season_payload(season_label="2026-27"), DIRECTOR_HEADERS
    )
    validate_error(label_already_used, errors.ERR_DUPLICATE_CODE)

    for season, label in ((this_winter, "2026-27"), (next_winter, "2027-28")):
        rows, meta = validate_paginated(
            api.list_terrain_areas(DIRECTOR_HEADERS, season_id=season["id"])
        )
        assert meta["total_count"] == 1, (
            f"Season {label} should hold exactly one trail, got {meta['total_count']}"
        )
        assert rows[0]["trail_code"] == "T1", (
            f"Season {label} should hold trail T1, got {rows[0]['trail_code']}"
        )


# ─── The plant-wide sweep runs after the pump-house sweep ───

def test_a_session_within_every_pump_house_ceiling_can_still_bust_the_plant_wide_ceiling(
    api, mountain
):
    """A session that fits comfortably inside its own pump house is still refused when the summed flow across every pump house of the season overruns the plant ceiling, and a request that busts both ceilings reports the pump house.

    The same construction is then repeated plant-wide, summing flow across every pump house of the season over every boundary span; if that plant-wide peak exceeds the season's `plant_max_gpm` the request is refused with `ERR_PLANT_CAPACITY_EXCEEDED`.

    The pump-house ceiling is always tested before the plant ceiling, so a request that busts both reports the pump-house code.

    Pump-house concurrent flow ceiling — `ERR_PUMP_CAPACITY_EXCEEDED` (422), on snowmaking session creation.

    Design: Corner/validations/the_plant_wide_sweep_runs_after_the_pump_house_sweep_and_across_pump_houses
    """
    season = mountain.create_season(plant_max_gpm=6000)
    lift = mountain.create_lift(season["id"])
    mountain.inspect_lift(lift["id"], "PASS")
    lower_bowl = mountain.create_terrain_area(season["id"], lift["id"], trail_code="T1")
    upper_bowl = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T2", name="Upper Bowl"
    )
    north_face = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T3", name="North Face"
    )
    base_house = mountain.create_pump_house(
        season["id"], pump_house_code="PH1", max_gpm=4000
    )
    mid_house = mountain.create_pump_house(
        season["id"], pump_house_code="PH2", name="Mid Mountain Pump House", max_gpm=4000
    )

    # 3500 gpm out of the base house from 08:00 to 12:00 leaves that house 500 gpm
    # of headroom and the plant 2500 gpm of headroom.
    mountain.schedule_session(
        lower_bowl["id"],
        base_house["id"],
        window_start="2026-08-01T08:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        gpm=3500,
    )

    upper_bowl_version = mountain.area_version(upper_bowl["id"])

    # 3000 gpm out of the *other* house fits that house easily, but the two
    # sessions overlap from 10:00 to 12:00, where the plant would carry 6500 gpm.
    overlapping_the_plant = api.create_session(
        payloads.session_payload(
            upper_bowl["id"],
            mid_house["id"],
            upper_bowl_version,
            window_start="2026-08-01T10:00:00Z",
            window_end="2026-08-01T14:00:00Z",
            gpm=3000,
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(overlapping_the_plant, errors.ERR_PLANT_CAPACITY_EXCEEDED)
    check.assert_integer(mountain.area_version(upper_bowl["id"]), upper_bowl_version)

    # Pushed past the first session's window, the same flow is accepted.
    after_the_overlap = api.create_session(
        payloads.session_payload(
            upper_bowl["id"],
            mid_house["id"],
            upper_bowl_version,
            window_start="2026-08-01T12:00:00Z",
            window_end="2026-08-01T16:00:00Z",
            gpm=3000,
        ),
        SNOWMAKING_HEADERS,
    )
    accepted = validate_success(after_the_overlap, 201)
    check.assert_water_af(accepted["water_af_reserved"], 2.210)

    # 4200 gpm out of the base house busts that house *and* the plant; the
    # pump-house code is the one reported.
    busts_both_ceilings = api.create_session(
        payloads.session_payload(
            north_face["id"],
            base_house["id"],
            mountain.area_version(north_face["id"]),
            window_start="2026-08-01T10:00:00Z",
            window_end="2026-08-01T14:00:00Z",
            gpm=4200,
        ),
        SNOWMAKING_HEADERS,
    )
    validate_error(busts_both_ceilings, errors.ERR_PUMP_CAPACITY_EXCEEDED)

    base_after = mountain.pump_house(base_house["id"])
    check.assert_integer(base_after["peak_committed_gpm"], 3500)
    check.assert_integer(base_after["active_session_count"], 0)
    mid_after = mountain.pump_house(mid_house["id"])
    check.assert_integer(mid_after["peak_committed_gpm"], 3000)

    accounting = get_success_data(
        api.get_season_snow_accounting(season["id"], SNOWMAKING_HEADERS)
    )
    check.assert_water_af(accounting["water_reserved_af"], 4.788)
    check.assert_water_af(accounting["water_right_remaining_af"], 245.212)


# ─── A trail cannot reopen while its patroller is on a call ───

def test_a_trail_held_short_of_patrollers_reopens_only_once_the_incident_is_closed(
    api, mountain
):
    """A trail pushed onto a patrol hold by a responder leaving the pool refuses to reopen while it is short-staffed, and reopening still takes a deliberate decision once the responder is free again.

    `assigned_patroller_count` is the number of patrollers whose `assigned_terrain_area_id` points at the area **and** whose `status` is `AVAILABLE`.

    Recovery is again explicit: an area already on `PATROL_HOLD` is not reopened merely because its patroller came free.

    Patrol staffing floor — `ERR_PATROL_STAFFING_INSUFFICIENT` (422), on the opening decision.

    Design: Corner/validations/a_patrol_staffing_shortfall_blocks_the_reopen_and_is_cured_by_closing_the_incident
    """
    state = mountain.open_mountain()
    responder, remaining = state["patroller_ids"]

    incident = mountain.report_incident(
        state["area_id"], reporter_code="RPT-1", severity="MINOR"
    )
    dispatched = mountain.dispatch_incident(incident["id"], responder)
    assert dispatched["state"] == "DISPATCHED", (
        f"Setup expects the responder to be dispatched, got {dispatched['state']}"
    )
    assert mountain.patroller(responder)["status"] == "ON_INCIDENT", (
        "Setup expects the dispatched responder to leave the staffing pool, got "
        f"{mountain.patroller(responder)['status']}"
    )

    # One of the two rostered patrollers is on the call, so the trail carries one
    # available patroller against a floor of two and has been pushed onto a hold.
    held = mountain.area(state["area_id"])
    check.assert_integer(held["assigned_patroller_count"], 1)
    assert held["opening_state"] == "PATROL_HOLD", (
        f"Expected the shortfall to push the trail onto PATROL_HOLD, got {held['opening_state']}"
    )

    short_staffed = api.decide_opening(
        state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(short_staffed, errors.ERR_PATROL_STAFFING_INSUFFICIENT)

    closed = mountain.close_incident(incident["id"], responder, "RELEASED_ON_HILL")
    assert closed["state"] == "CLOSED", (
        f"Expected the incident to close, got {closed['state']}"
    )
    assert mountain.patroller(responder)["status"] == "AVAILABLE", (
        "Closing the incident returns the responder to the pool, got "
        f"{mountain.patroller(responder)['status']}"
    )
    assert mountain.patroller(remaining)["status"] == "AVAILABLE", (
        "The patroller who never left the pool should still be available, got "
        f"{mountain.patroller(remaining)['status']}"
    )

    # The staffing floor is satisfied again, but the hold does not lift itself.
    cured = mountain.area(state["area_id"])
    check.assert_integer(cured["assigned_patroller_count"], 2)
    assert cured["opening_state"] == "PATROL_HOLD", (
        "A trail on PATROL_HOLD must not reopen merely because its patroller came "
        f"free, got {cured['opening_state']}"
    )

    reopened = validate_success(
        api.decide_opening(
            state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN", (
        f"Expected the deliberate reopen to take the trail to OPEN, got {reopened['opening_state']}"
    )
    check.assert_integer(mountain.day_plan(state["day_plan_id"])["open_terrain_count"], 1)


# ─── An avalanche clearance dies on its expiry instant ───

def test_an_avalanche_clearance_stops_counting_the_instant_it_expires(api, mountain):
    """A ski cut buys eight hours of avalanche clearance, and standing the logical clock exactly on the expiry instant refuses the opening decision until a fresh mission is thrown.

    A `hazard_rating_post` of `LOW` or `MODERATE` moves the mission `EXECUTED → CLEARED`, stamps `cleared_at`, records `cleared_by_patroller_id`, and sets the terrain area's `mitigation_clearance_expires_at` to the logical clock plus the mission's `clearance_valid_hours`; readiness is then re-evaluated for the area, which may fire `PREP → READY`.

    Its `clearance_valid_hours` is fixed at creation by the method it will use — 24 hours for `EXPLOSIVE` and for `GAS_EXPLODER`, and only 8 hours for `SKI_CUT`, which reflects how much less of the slope a ski cut actually tests — and it is that figure the eventual clearance applies.

    Avalanche clearance currency — `ERR_MITIGATION_NOT_CURRENT` (422), on the opening decision.

    Design: Corner/validations/an_avalanche_clearance_expires_on_the_clock_at_exactly_its_expiry_instant
    """
    state = mountain.ready_area(area_overrides={"avalanche_terrain": True})
    cutter, signer = state["patroller_ids"]

    # A ski cut thrown at midnight on the logical clock, signed off by the other
    # patroller, is worth eight hours of clearance.
    ski_cut = mountain.clear_avalanche_terrain(
        state["area_id"],
        cutter,
        signer,
        method="SKI_CUT",
        charges_used=0,
        hazard_rating_post="LOW",
        route_code="AV-1",
        planned_charges=0,
    )
    assert ski_cut["state"] == "CLEARED", (
        f"Setup expects the ski cut to be signed off, got {ski_cut['state']}"
    )
    check.assert_integer(ski_cut["clearance_valid_hours"], 8)

    cleared_trail = mountain.area(state["area_id"])
    check.assert_instant_equals(
        cleared_trail["mitigation_clearance_expires_at"], "2026-08-01T08:00:00Z"
    )
    assert cleared_trail["opening_state"] == "READY", (
        f"The clearance should have fired PREP to READY, got {cleared_trail['opening_state']}"
    )

    day_plan = mountain.create_day_plan(state["season_id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0)
    mountain.set_lift_status(state["lift_id"], "OPEN")

    # Eight hours to the second after the cut, the clearance is no longer current,
    # because currency requires the clock to be strictly before the expiry.
    mountain.set_clock("2026-08-01T08:00:00Z")
    on_the_expiry_instant = api.decide_opening(
        state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(on_the_expiry_instant, errors.ERR_MITIGATION_NOT_CURRENT)

    # Only a fresh mission, planned, executed and cleared again, reopens the slope.
    second_cut = mountain.clear_avalanche_terrain(
        state["area_id"],
        cutter,
        signer,
        method="SKI_CUT",
        charges_used=0,
        hazard_rating_post="LOW",
        route_code="AV-2",
        planned_charges=0,
    )
    check.assert_integer(second_cut["clearance_valid_hours"], 8)
    recleared = mountain.area(state["area_id"])
    check.assert_instant_equals(
        recleared["mitigation_clearance_expires_at"], "2026-08-01T16:00:00Z"
    )

    opened = validate_success(
        api.decide_opening(
            state["area_id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert opened["opening_state"] == "OPEN", (
        f"Expected the freshly cleared slope to open, got {opened['opening_state']}"
    )


# ─── A cat pass stops counting at the freshness horizon ───

def test_a_groomed_trail_stops_counting_as_groomed_exactly_at_the_freshness_horizon(
    api, mountain
):
    """A completed cat pass keeps a trail current for the season's freshness hours and no longer, so the last second before the horizon opens the trail and the horizon instant itself does not.

    Completion also stamps the area's `last_groomed_at` with the logical clock and sets `groom_ready` to true when the coverage figure is at least 70.0 percent and the clock is still strictly before `last_groomed_at` plus the season's `groom_freshness_hours` — which, at the default policy, means an area counts as groomed for the 18 hours following the completing pass and then quietly stops counting.

    Groom currency — `ERR_GROOM_NOT_CURRENT` (422), on the opening decision.

    Design: Corner/validations/groom_currency_expires_on_the_clock_at_exactly_the_freshness_horizon
    """
    season = mountain.create_season(groom_freshness_hours=18)
    lift = mountain.ready_lift(season["id"])
    lower_bowl = mountain.create_terrain_area(season["id"], lift["id"], trail_code="T1")
    upper_bowl = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T2", name="Upper Bowl"
    )

    # Both trails are measured and groomed on the midnight cat shift. Twenty-four
    # passes at 0.75 acres a pass cover all 18.0 acres, so coverage caps at 100.0.
    for trail, route in ((lower_bowl, "R1"), (upper_bowl, "R2")):
        mountain.record_reading(trail["id"], stake_code="S1", depth_in=40.0)
        mountain.groom_area(trail["id"], 24, cat_route_code=route, sequence_index=1)

    mountain.staff_patrol(season["id"], lower_bowl["id"], 2)
    for code, cert in (("P3", "EMT"), ("P4", "PARAMEDIC")):
        mountain.create_patroller(
            season["id"],
            patroller_code=code,
            cert_level=cert,
            on_duty=True,
            assigned_terrain_area_id=upper_bowl["id"],
        )

    day_plan = mountain.create_day_plan(season["id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0)
    mountain.set_lift_status(lift["id"], "OPEN")

    # One second short of eighteen hours after the pass, the groom still counts.
    mountain.set_clock("2026-08-01T17:59:59Z")
    inside_the_horizon = validate_success(
        api.decide_opening(
            upper_bowl["id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert inside_the_horizon["opening_state"] == "OPEN", (
        "A trail groomed one second inside the freshness horizon must open, got "
        f"{inside_the_horizon['opening_state']}"
    )

    # On the horizon itself the same groom no longer counts.
    mountain.set_clock("2026-08-01T18:00:00Z")
    on_the_horizon = api.decide_opening(
        lower_bowl["id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(on_the_horizon, errors.ERR_GROOM_NOT_CURRENT)

    # The coverage the cat actually cut is untouched by the refusal, and the refused
    # decision moves nothing: the trail keeps its READY marker, because the clock
    # running on is not a mutation of the area.
    stale = mountain.area(lower_bowl["id"])
    check.assert_one_decimal(stale["groom_coverage_pct"], 100.0)
    assert stale["opening_state"] == "READY", (
        f"Expected the refused trail to stay in READY, got {stale['opening_state']}"
    )

    # A fresh pass on the same route restamps the groom and reopens the trail.
    fresh_pass = mountain.plan_groom(
        lower_bowl["id"],
        cat_route_code="R1",
        sequence_index=2,
        window_start="2026-08-01T18:00:00Z",
        window_end="2026-08-01T20:00:00Z",
    )
    mountain.dispatch_groom(fresh_pass["id"])
    completed = mountain.complete_groom(fresh_pass["id"], 24)
    check.assert_one_decimal(completed["coverage_pct"], 100.0)

    regroomed = mountain.area(lower_bowl["id"])
    check.assert_instant_equals(regroomed["last_groomed_at"], "2026-08-01T18:00:00Z")

    reopened = validate_success(
        api.decide_opening(
            lower_bowl["id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN", (
        f"Expected the freshly groomed trail to open, got {reopened['opening_state']}"
    )

    # Both trails of the season are open, so everything that could be open is.
    day = mountain.day_plan(day_plan["id"])
    check.assert_integer(day["open_terrain_count"], 2)
    assert day["posture"] == "PUBLISHED_FULL", (
        f"With every trail open the day should read PUBLISHED_FULL, got {day['posture']}"
    )


# ─── An expired inspection stops the lift and the trail it serves ───

def test_an_expired_lift_inspection_stops_both_the_opening_decision_and_the_standby_move(
    api, mountain
):
    """Once the clock reaches the instant a lift's inspection expires, the trail the lift serves cannot be opened and the lift cannot be brought back to standby, until a fresh passing inspection is recorded.

    A passing inspection sets `mechanical_status` to `INSPECTION_PASSED` and sets `inspection_valid_until` to 24 hours after the inspection instant, which is the entire basis of the currency test used elsewhere: an inspection is current while the logical clock is strictly before `inspection_valid_until`.

    `CLOSED → STANDBY` requires a current inspection: `mechanical_status` must be `INSPECTION_PASSED` and the logical clock must be strictly before `inspection_valid_until`, otherwise the request is refused with `ERR_LIFT_INSPECTION_EXPIRED`.

    The lift's mechanical inspection is current — `ERR_LIFT_INSPECTION_EXPIRED` (422), on the lift service-status change and on the opening decision.

    Design: Corner/validations/an_expired_lift_inspection_blocks_both_the_opening_decision_and_the_standby_transition
    """
    # A 48 hour groom policy keeps the groom gate out of the way, so the only
    # currency that runs out inside the test is the lift's inspection.
    season = mountain.create_season(groom_freshness_hours=48)
    lift = mountain.create_lift(season["id"])
    inspected = mountain.inspect_lift(lift["id"], "PASS")
    check.assert_instant_equals(inspected["inspection_valid_until"], "2026-08-02T00:00:00Z")
    # Operators cover the lift across both instants the test visits.
    mountain.staff_lift(
        lift["id"],
        shift_start="2026-08-01T00:00:00Z",
        shift_end="2026-08-03T00:00:00Z",
    )
    mountain.set_lift_status(lift["id"], "STANDBY")

    area = mountain.create_terrain_area(season["id"], lift["id"])
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    mountain.groom_area(area["id"], 20)
    mountain.staff_patrol(season["id"], area["id"], 2)

    day_plan = mountain.create_day_plan(season["id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0)
    mountain.set_lift_status(lift["id"], "OPEN")

    # Exactly 24 hours after the inspection, the currency window has closed.
    mountain.set_clock("2026-08-02T00:00:00Z")
    blocked_opening = api.decide_opening(
        area["id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
    )
    validate_error(blocked_opening, errors.ERR_LIFT_INSPECTION_EXPIRED)

    # Closing the lift needs no current inspection, and the trail was never open,
    # so nothing cascades onto it.
    closed = validate_success(
        api.set_lift_service_status(
            lift["id"], payloads.service_status_payload("CLOSED"), LIFT_OPS_HEADERS
        )
    )
    assert closed["service_status"] == "CLOSED", (
        f"Expected the lift to close, got {closed['service_status']}"
    )
    assert mountain.area(area["id"])["opening_state"] == "READY", (
        "A trail that was not open must not be cascaded by the lift closing, got "
        f"{mountain.area(area['id'])['opening_state']}"
    )

    # The expired inspection, not the state machine, is what refuses the move back.
    blocked_standby = api.set_lift_service_status(
        lift["id"], payloads.service_status_payload("STANDBY"), LIFT_OPS_HEADERS
    )
    validate_error(blocked_standby, errors.ERR_LIFT_INSPECTION_EXPIRED)

    refreshed = mountain.inspect_lift(lift["id"], "PASS")
    assert refreshed["mechanical_status"] == "INSPECTION_PASSED", (
        f"Expected a passing inspection to pass the lift, got {refreshed['mechanical_status']}"
    )
    assert refreshed["last_inspection_result"] == "PASS", (
        f"Expected the outcome to be recorded as PASS, got {refreshed['last_inspection_result']}"
    )
    check.assert_instant_equals(refreshed["inspection_valid_until"], "2026-08-03T00:00:00Z")

    to_standby = validate_success(
        api.set_lift_service_status(
            lift["id"], payloads.service_status_payload("STANDBY"), LIFT_OPS_HEADERS
        )
    )
    assert to_standby["service_status"] == "STANDBY", (
        f"Expected the refreshed lift to reach STANDBY, got {to_standby['service_status']}"
    )
    to_open = validate_success(
        api.set_lift_service_status(
            lift["id"], payloads.service_status_payload("OPEN"), LIFT_OPS_HEADERS
        )
    )
    assert to_open["service_status"] == "OPEN", (
        f"Expected the refreshed lift to reach OPEN, got {to_open['service_status']}"
    )

    reopened = validate_success(
        api.decide_opening(
            area["id"], payloads.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN", (
        f"Expected the trail to open behind a currently inspected lift, got {reopened['opening_state']}"
    )
