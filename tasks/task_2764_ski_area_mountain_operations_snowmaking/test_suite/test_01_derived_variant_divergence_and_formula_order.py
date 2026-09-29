"""Derived mountain figures whose value depends on a declared policy or a
declared step order.

Four behaviours live here. A terrain area's settled base depth is re-derived
from its snow stake readings under the season's stake statistic, so one physical
reading set resolves to two different depths. A snowmaking session's water is
booked twice over — once as the planned reservation of the whole declared
window, once as the metered draw of the minutes the guns actually ran. That
metered water is then priced across the season's recurring energy price windows,
where each window's kilowatt-hours and cost are rounded before the costs are
summed. And the operating day's comfortable carrying capacity is reduced by a
crowding factor that is evaluated exactly once, on the uncrowded figure.
"""

from prd_bench_local_runner.testing import validate_success

from test_helpers.assertions import (
    as_number,
    assert_accounting_identity,
    assert_energy_kwh,
    assert_integer,
    assert_one_decimal,
    assert_usd,
    assert_water_af,
    assert_water_ledger_identity,
    expected_base_depth,
    expected_base_energy_cost,
    expected_capacity,
    expected_energy_kwh,
    expected_water_af,
    expected_window_energy_cost,
    whole_minutes_between,
)
from test_helpers.constants import (
    DEMAND_SURCHARGE_GPM_SHARE,
    GROOM_READY_MIN_COVERAGE_PCT,
)
from test_helpers.factories import (
    opening_decision_payload,
    session_payload,
    session_status_payload,
    snow_depth_reading_payload,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    SNOWMAKING_HEADERS,
)

# ─── The stake policies and the reading set they disagree on ──
MEAN_OF_STAKES = "MEAN_OF_STAKES"
MIN_OF_STAKES = "MIN_OF_STAKES"

STAKE_READINGS = (("S1", 33.4), ("S2", 27.6), ("S3", 41.9))
MEAN_POLICY_DEPTH_IN = 34.3
MIN_POLICY_DEPTH_IN = 27.6
SURVIVING_STAKE_COUNT = 3

# ─── The metered snowmaking session ───────────────────
SESSION_WINDOW_START = "2026-08-01T05:00:00Z"
SESSION_WINDOW_END = "2026-08-01T12:00:00Z"
SESSION_GPM = 1200
SESSION_GUN_COUNT = 30
PLANNED_MINUTES = 420
RUN_MINUTES = 360
PLANNED_WATER_AF = 1.547
METERED_WATER_AF = 1.326
SEASONAL_WATER_RIGHT_AF = 250.000
WATER_RIGHT_REMAINING_AF = 248.674
KWH_PER_AF = 620.0
TOTAL_ENERGY_KWH = 822.120
BASE_ENERGY_COST_USD = 106.20
COST_OF_ROUNDING_ONCE_AT_THE_END_USD = 106.19
PLANT_MAX_GPM = 6000

# The priced interval [05:00, 11:00) sliced across the price windows, as
# (minutes inside the window, price per kilowatt-hour).
PRICED_WINDOW_SLICES = ((60, 0.062), (180, 0.113), (120, 0.187))

# ─── The three open areas of the carrying-capacity day ─
OPEN_LIFT_CAPACITY_PPH = 1800
OPEN_TERRAIN_ACRES = 40.0
RAW_CCC = 1080
GUEST_CAPACITY = 918
CAPACITY_WITHOUT_THE_REDUCTION = 1080
NON_SEASON_POOL = 642


# ─── Local state builders ─────────────────────────────

def _season_with_two_measured_stakes(mountain, season_label, base_depth_policy):
    """A season under the named stake policy whose single BLUE terrain area
    already carries the first two stake readings of the reading set."""
    season = mountain.create_season(
        season_label=season_label, base_depth_policy=base_depth_policy
    )
    lift = mountain.create_lift(season["id"])
    area = mountain.create_terrain_area(season["id"], lift["id"])
    for stake_code, depth_in in STAKE_READINGS[:2]:
        mountain.record_reading(area["id"], stake_code=stake_code, depth_in=depth_in)
    return {"season_id": season["id"], "area_id": area["id"]}


def _record_last_stake(api, area_id):
    """Record the deepest stake of the reading set, the reading that settles the
    area's base depth."""
    stake_code, depth_in = STAKE_READINGS[2]
    return api.record_snow_depth_reading(
        area_id,
        snow_depth_reading_payload(stake_code=stake_code, depth_in=depth_in),
        GROOMING_HEADERS,
    )


def _scheduled_session(mountain):
    """An open mountain with an online pump house and one scheduled session
    covering the seven-hour window at the committed flow."""
    state = mountain.open_mountain(with_pump_house=True)
    session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start=SESSION_WINDOW_START,
        window_end=SESSION_WINDOW_END,
        gun_count=SESSION_GUN_COUNT,
        gpm=SESSION_GPM,
    )
    state["session"] = session
    state["session_id"] = session["id"]
    return state


def _session_run_for_six_of_its_seven_hours(mountain):
    """The scheduled session started on time, paused after two hours, resumed
    two hours later and left running until the clock stands past its window."""
    state = _scheduled_session(mountain)
    mountain.run_session_cycle(
        state["session_id"],
        [
            ("2026-08-01T05:00:00Z", "RUNNING"),
            ("2026-08-01T07:00:00Z", "PAUSED"),
            ("2026-08-01T09:00:00Z", "RUNNING"),
        ],
    )
    mountain.set_clock("2026-08-01T13:00:00Z")
    return state


def _three_open_areas_under_two_lifts(mountain):
    """An operating day with two staffed lifts open and three groomed, patrolled
    terrain areas, the last of which is still closed and ready to be opened."""
    season = mountain.create_season()
    lifts = []
    for lift_code, name, lift_type, capacity, operator_code in (
        ("L1", "Summit Express", "DETACHABLE", 1100, "OP-1"),
        ("L2", "Cirque Chair", "FIXED_GRIP", 700, "OP-2"),
    ):
        lift = mountain.create_lift(
            season["id"],
            lift_code=lift_code,
            name=name,
            lift_type=lift_type,
            hourly_capacity_pph=capacity,
            required_operator_count=1,
            wind_hold_threshold_mph=40.0,
        )
        mountain.inspect_lift(lift["id"], "PASS")
        mountain.assign_operator(
            lift["id"], operator_code=operator_code, role_on_lift="TOP_OP"
        )
        mountain.set_lift_status(lift["id"], "STANDBY")
        lifts.append(lift)

    areas = []
    plan = (
        ("T1", "Lower Bowl", "BLUE", 18.0, 0, "R1", "CAT-1", 20, ("P1", "P2")),
        ("T2", "Meadow Lane", "GREEN", 14.0, 0, "R2", "CAT-2", 14, ("P3", "P4")),
        ("T3", "North Chute", "BLACK", 8.0, 1, "R3", "CAT-3", 9, ("P5", "P6")),
    )
    for (
        trail_code,
        name,
        terrain_class,
        acres,
        lift_index,
        route_code,
        cat_code,
        passes,
        patroller_codes,
    ) in plan:
        area = mountain.create_terrain_area(
            season["id"],
            lifts[lift_index]["id"],
            trail_code=trail_code,
            name=name,
            terrain_class=terrain_class,
            acres=acres,
        )
        mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
        mountain.groom_area(
            area["id"],
            passes,
            cat_route_code=route_code,
            snowcat_unit_code=cat_code,
        )
        for patroller_code in patroller_codes:
            mountain.create_patroller(
                season["id"],
                patroller_code=patroller_code,
                cert_level="EMT",
                on_duty=True,
                assigned_terrain_area_id=area["id"],
            )
        settled = mountain.area(area["id"])
        assert settled["groom_ready"] is True
        assert as_number(settled["groom_coverage_pct"]) >= GROOM_READY_MIN_COVERAGE_PCT
        areas.append(area)

    day_plan = mountain.create_day_plan(season["id"])
    mountain.publish_day_plan(day_plan["id"])
    mountain.post_weather(day_plan["id"], 10.0, 22.0)
    for lift in lifts:
        mountain.set_lift_status(lift["id"], "OPEN")
    mountain.decide_opening(areas[0]["id"], "OPEN")
    mountain.decide_opening(areas[1]["id"], "OPEN")
    return {
        "season_id": season["id"],
        "day_plan_id": day_plan["id"],
        "last_area_id": areas[2]["id"],
        "area_ids": [area["id"] for area in areas],
    }


# ─── The season's stake statistic decides the base depth ──

def test_mean_of_stakes_settles_base_depth_at_the_average_of_the_surviving_stakes(api, mountain):
    """Under MEAN_OF_STAKES the settled base depth is the average of the surviving stake depths, not the thinnest of them.

    Otherwise the season's `base_depth_policy` decides: under `MEAN_OF_STAKES` the depth is the sum of the surviving depths divided by the surviving stake count, rounded half up to one decimal place; under `MIN_OF_STAKES` it is the smallest surviving depth, rounded half up to one decimal place.

    Design: Difficulty/dual_variant_calc/base_depth_policy_variant_divergence_on_terrain_area
    """
    state = _season_with_two_measured_stakes(mountain, "2026-27-MEAN", MEAN_OF_STAKES)

    validate_success(_record_last_stake(api, state["area_id"]), 201)

    area = validate_success(api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS))
    depths = [depth_in for _, depth_in in STAKE_READINGS]
    assert_one_decimal(area["base_depth_in"], MEAN_POLICY_DEPTH_IN)
    assert_one_decimal(
        area["base_depth_in"], expected_base_depth(depths, MEAN_OF_STAKES)
    )
    assert as_number(area["base_depth_in"]) != MIN_POLICY_DEPTH_IN


def test_min_of_stakes_settles_base_depth_at_the_thinnest_surviving_stake(api, mountain):
    """Under MIN_OF_STAKES the settled base depth is the smallest surviving stake depth, not the average of them.

    Otherwise the season's `base_depth_policy` decides: under `MEAN_OF_STAKES` the depth is the sum of the surviving depths divided by the surviving stake count, rounded half up to one decimal place; under `MIN_OF_STAKES` it is the smallest surviving depth, rounded half up to one decimal place.

    Design: Difficulty/dual_variant_calc/base_depth_policy_variant_divergence_on_terrain_area
    """
    state = _season_with_two_measured_stakes(mountain, "2026-27-MIN", MIN_OF_STAKES)

    validate_success(_record_last_stake(api, state["area_id"]), 201)

    area = validate_success(api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS))
    depths = [depth_in for _, depth_in in STAKE_READINGS]
    assert_one_decimal(area["base_depth_in"], MIN_POLICY_DEPTH_IN)
    assert_one_decimal(
        area["base_depth_in"], expected_base_depth(depths, MIN_OF_STAKES)
    )
    assert as_number(area["base_depth_in"]) != MEAN_POLICY_DEPTH_IN


def test_the_same_stake_readings_settle_at_different_depths_under_the_two_policies(api, mountain):
    """One physical reading set measured on two areas settles nearly seven inches apart because their seasons carry different stake statistics.

    Otherwise the season's `base_depth_policy` decides: under `MEAN_OF_STAKES` the depth is the sum of the surviving depths divided by the surviving stake count, rounded half up to one decimal place; under `MIN_OF_STAKES` it is the smallest surviving depth, rounded half up to one decimal place.

    Design: Difficulty/dual_variant_calc/base_depth_policy_variant_divergence_on_terrain_area
    """
    averaging = _season_with_two_measured_stakes(mountain, "2026-27-MEAN", MEAN_OF_STAKES)
    thinnest = _season_with_two_measured_stakes(mountain, "2026-27-MIN", MIN_OF_STAKES)

    validate_success(_record_last_stake(api, averaging["area_id"]), 201)
    validate_success(_record_last_stake(api, thinnest["area_id"]), 201)

    averaged_area = validate_success(
        api.get_terrain_area(averaging["area_id"], DIRECTOR_HEADERS)
    )
    thinnest_area = validate_success(
        api.get_terrain_area(thinnest["area_id"], DIRECTOR_HEADERS)
    )
    assert_one_decimal(averaged_area["base_depth_in"], MEAN_POLICY_DEPTH_IN)
    assert_one_decimal(thinnest_area["base_depth_in"], MIN_POLICY_DEPTH_IN)
    divergence = round(
        as_number(averaged_area["base_depth_in"])
        - as_number(thinnest_area["base_depth_in"]),
        1,
    )
    assert divergence == 6.7


def test_the_surviving_stake_count_is_reported_alongside_either_settled_depth(api, mountain):
    """Three distinct stakes survive the lookback under either statistic, so the reported stake count is identical even where the depths diverge.

    `base_depth_stake_count` is then the number of distinct stakes surviving that collapse.

    Design: Difficulty/dual_variant_calc/base_depth_policy_variant_divergence_on_terrain_area
    """
    averaging = _season_with_two_measured_stakes(mountain, "2026-27-MEAN", MEAN_OF_STAKES)
    thinnest = _season_with_two_measured_stakes(mountain, "2026-27-MIN", MIN_OF_STAKES)

    validate_success(_record_last_stake(api, averaging["area_id"]), 201)
    validate_success(_record_last_stake(api, thinnest["area_id"]), 201)

    averaged_area = validate_success(
        api.get_terrain_area(averaging["area_id"], DIRECTOR_HEADERS)
    )
    thinnest_area = validate_success(
        api.get_terrain_area(thinnest["area_id"], DIRECTOR_HEADERS)
    )
    assert_integer(averaged_area["base_depth_stake_count"], SURVIVING_STAKE_COUNT)
    assert_integer(thinnest_area["base_depth_stake_count"], SURVIVING_STAKE_COUNT)


# ─── Reserved water against metered water ─────────────

def test_a_new_session_reserves_water_for_every_minute_of_its_declared_window(api, mountain):
    """Scheduling books the whole seven-hour window as an upper bound, so the reservation covers 420 minutes of pumping before a single gun has run.

    The session's `planned_minutes` is the number of whole minutes between `window_start` and `window_end`, and the water it reserves follows directly: the committed flow in gallons per minute is multiplied by `planned_minutes` to give gallons, that total is divided by the 325,851 gallons that make up one acre-foot, and the quotient is rounded half up to three decimal places to give `water_af_reserved`.

    Design: Difficulty/dual_variant_calc/water_volume_variant_divergence_on_snowmaking_session
    """
    state = mountain.open_mountain(with_pump_house=True)

    response = api.create_session(
        session_payload(
            state["area_id"],
            state["pump_house_id"],
            mountain.area_version(state["area_id"]),
            window_start=SESSION_WINDOW_START,
            window_end=SESSION_WINDOW_END,
            gun_count=SESSION_GUN_COUNT,
            gpm=SESSION_GPM,
        ),
        SNOWMAKING_HEADERS,
    )

    session = validate_success(response, 201)
    assert_integer(session["planned_minutes"], PLANNED_MINUTES)
    assert_integer(
        session["planned_minutes"],
        whole_minutes_between(SESSION_WINDOW_START, SESSION_WINDOW_END),
    )
    assert_water_af(session["water_af_reserved"], PLANNED_WATER_AF)
    assert_water_af(
        session["water_af_reserved"], expected_water_af(SESSION_GPM, PLANNED_MINUTES)
    )
    season = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    assert_water_af(season["water_reserved_af"], PLANNED_WATER_AF)


def test_metered_water_bills_only_the_minutes_the_guns_actually_ran(api, mountain):
    """A session paused for one hour of its window meters 360 running minutes, so its actual draw falls well short of the reservation it was booked against.

    Metered water follows the same arithmetic as the reservation but on real minutes: the committed `gpm` multiplied by `accumulated_run_minutes`, divided by the 325,851 gallons in an acre-foot, rounded half up to three decimal places, stored as `water_af_actual`.

    Design: Difficulty/dual_variant_calc/water_volume_variant_divergence_on_snowmaking_session
    """
    state = _session_run_for_six_of_its_seven_hours(mountain)

    response = api.set_session_status(
        state["session_id"], session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
    )

    session = validate_success(response)
    assert session["state"] == "COMPLETED"
    assert_integer(session["accumulated_run_minutes"], RUN_MINUTES)
    assert_water_af(session["water_af_actual"], METERED_WATER_AF)
    assert_water_af(
        session["water_af_actual"], expected_water_af(SESSION_GPM, RUN_MINUTES)
    )
    assert as_number(session["water_af_actual"]) != PLANNED_WATER_AF
    shortfall = round(
        as_number(session["water_af_reserved"]) - as_number(session["water_af_actual"]), 3
    )
    assert shortfall == 0.221


def test_completing_a_session_moves_its_water_from_reserved_to_drawn(api, mountain):
    """Completion releases the planned reservation and charges the metered draw instead, so the seasonal allowance is reduced by the water that really flowed.

    Concretely, `water_used_af` accumulates the metered draw of completed sessions, `water_reserved_af` holds the planned reservations of sessions that are still scheduled, running or paused, and the remaining allowance is the seasonal right less both figures.

    Design: Difficulty/dual_variant_calc/water_volume_variant_divergence_on_snowmaking_session
    """
    state = _session_run_for_six_of_its_seven_hours(mountain)

    validate_success(
        api.set_session_status(
            state["session_id"], session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
        )
    )

    season = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    assert_water_af(season["water_used_af"], METERED_WATER_AF)
    assert_water_af(season["water_reserved_af"], 0.000)
    assert_water_ledger_identity(season, WATER_RIGHT_REMAINING_AF)
    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], SNOWMAKING_HEADERS)
    )
    assert_water_af(rollup["water_used_af"], METERED_WATER_AF)
    assert_water_af(rollup["water_reserved_af"], 0.000)
    assert_water_af(rollup["water_right_remaining_af"], WATER_RIGHT_REMAINING_AF)
    assert_accounting_identity(rollup)


# ─── Energy priced window by window ───────────────────

def test_total_energy_consumption_scales_the_metered_water_by_the_energy_intensity(api, mountain):
    """Consumption is derived from the water that actually flowed and the season's energy intensity, not from the water the session reserved.

    Total consumption `energy_kwh` is the metered water multiplied by the season's `snowmaking_kwh_per_af`, rounded half up to three decimal places.

    Design: Difficulty/combinatorial_formula/energy_cost_per_window_rounding_order_on_snowmaking_session
    """
    state = _session_run_for_six_of_its_seven_hours(mountain)

    response = api.set_session_status(
        state["session_id"], session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
    )

    session = validate_success(response)
    assert_water_af(session["water_af_actual"], METERED_WATER_AF)
    assert_energy_kwh(session["energy_kwh"], TOTAL_ENERGY_KWH)
    assert_energy_kwh(
        session["energy_kwh"], expected_energy_kwh(METERED_WATER_AF, KWH_PER_AF)
    )


def test_energy_cost_rounds_each_price_window_before_the_windows_are_summed(api, mountain):
    """The six running hours straddle three price windows, and rounding each window's cost before adding them lands a cent above the figure a single final rounding would give.

    Rounding per window and then summing is normative — summing unrounded costs and rounding once at the end produces a figure that can differ by a cent, and that reading is wrong.

    Design: Difficulty/combinatorial_formula/energy_cost_per_window_rounding_order_on_snowmaking_session
    """
    state = _session_run_for_six_of_its_seven_hours(mountain)

    response = api.set_session_status(
        state["session_id"], session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
    )

    session = validate_success(response)
    per_window = [
        expected_window_energy_cost(TOTAL_ENERGY_KWH, minutes, RUN_MINUTES, price)
        for minutes, price in PRICED_WINDOW_SLICES
    ]
    shares = [round(share, 3) for share, _ in per_window]
    costs = [round(cost, 2) for _, cost in per_window]
    assert shares == [137.020, 411.060, 274.040]
    assert costs == [8.50, 46.45, 51.25]
    assert round(sum(shares), 3) == TOTAL_ENERGY_KWH
    assert expected_base_energy_cost(costs) == BASE_ENERGY_COST_USD
    assert_usd(session["energy_cost_usd"], BASE_ENERGY_COST_USD)
    assert as_number(session["energy_cost_usd"]) != COST_OF_ROUNDING_ONCE_AT_THE_END_USD


def test_a_committed_flow_below_the_plant_share_leaves_the_demand_surcharge_unfired(api, mountain):
    """One session at 1,200 gallons per minute never reaches four fifths of the plant ceiling, so the day's snowmaking is billed without the demand surcharge.

    The plant demand surcharge applies when the pump house's `peak_committed_gpm` is at least eighty percent of the season's `plant_max_gpm`; `demand_surcharge_applied` records whether it fired.

    Design: Difficulty/combinatorial_formula/energy_cost_per_window_rounding_order_on_snowmaking_session
    """
    state = _session_run_for_six_of_its_seven_hours(mountain)
    season = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    committed = validate_success(
        api.get_pump_house(state["pump_house_id"], SNOWMAKING_HEADERS)
    )
    assert_integer(committed["peak_committed_gpm"], SESSION_GPM)
    assert_integer(season["plant_max_gpm"], PLANT_MAX_GPM)
    assert as_number(committed["peak_committed_gpm"]) < (
        DEMAND_SURCHARGE_GPM_SHARE * as_number(season["plant_max_gpm"])
    )

    response = api.set_session_status(
        state["session_id"], session_status_payload("COMPLETED"), SNOWMAKING_HEADERS
    )

    session = validate_success(response)
    assert session["demand_surcharge_applied"] is False
    assert_usd(session["energy_cost_usd"], BASE_ENERGY_COST_USD)


# ─── Carrying capacity down the ordered ladder ────────

def test_the_uncrowded_carrying_capacity_takes_sixty_percent_of_the_open_uphill_capacity(api, mountain):
    """With both lifts spinning, the day's open uphill capacity is the sum of their hourly capacities and the uncrowded carrying capacity is six tenths of it, floored.

    Third, `raw_ccc` — the uncrowded comfortable carrying capacity — is the open uphill capacity multiplied by 0.60, floored to a whole number of guests.

    Design: Difficulty/combinatorial_formula/guest_capacity_evaluation_order_on_raw_ccc
    """
    state = _three_open_areas_under_two_lifts(mountain)

    validate_success(
        api.decide_opening(
            state["last_area_id"], opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )

    plan = validate_success(
        api.get_day_plan(state["day_plan_id"], GUEST_SERVICES_HEADERS)
    )
    assert_integer(plan["open_lift_capacity_pph"], OPEN_LIFT_CAPACITY_PPH)
    assert_integer(plan["raw_ccc"], RAW_CCC)
    assert_integer(
        plan["raw_ccc"],
        expected_capacity(OPEN_LIFT_CAPACITY_PPH, OPEN_TERRAIN_ACRES)["raw_ccc"],
    )


def test_the_crowding_reduction_is_weighed_once_on_the_uncrowded_capacity(api, mountain):
    """Forty open acres carrying 1,080 uncrowded guests is denser than the comfort threshold, so capacity is cut once to 918 and the cut is never reconsidered against the reduced figure.

    Re-testing the density on 918 — which would fall back under the threshold and restore capacity to 1,080 — is the forbidden reading; the threshold is evaluated exactly once, on `raw_ccc`.

    Design: Difficulty/combinatorial_formula/guest_capacity_evaluation_order_on_raw_ccc
    """
    state = _three_open_areas_under_two_lifts(mountain)

    validate_success(
        api.decide_opening(
            state["last_area_id"], opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )

    plan = validate_success(
        api.get_day_plan(state["day_plan_id"], GUEST_SERVICES_HEADERS)
    )
    assert_one_decimal(plan["terrain_open_acres"], OPEN_TERRAIN_ACRES)
    assert_integer(plan["guest_capacity"], GUEST_CAPACITY)
    assert_integer(
        plan["guest_capacity"],
        expected_capacity(
            plan["open_lift_capacity_pph"], as_number(plan["terrain_open_acres"])
        )["guest_capacity"],
    )
    assert plan["guest_capacity"] != CAPACITY_WITHOUT_THE_REDUCTION


def test_the_non_season_pool_takes_seventy_percent_of_the_reduced_guest_capacity(api, mountain):
    """The pool held back for guests without a season pass is seven tenths of the crowding-reduced capacity, floored, so it inherits the reduction rather than the uncrowded figure.

    Finally, `non_season_pool` is `guest_capacity` multiplied by 0.70, floored.

    Design: Difficulty/combinatorial_formula/guest_capacity_evaluation_order_on_raw_ccc
    """
    state = _three_open_areas_under_two_lifts(mountain)

    validate_success(
        api.decide_opening(
            state["last_area_id"], opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )

    plan = validate_success(
        api.get_day_plan(state["day_plan_id"], GUEST_SERVICES_HEADERS)
    )
    assert_integer(plan["guest_capacity"], GUEST_CAPACITY)
    assert_integer(plan["non_season_pool"], NON_SEASON_POOL)
    assert_integer(
        plan["non_season_pool"],
        expected_capacity(OPEN_LIFT_CAPACITY_PPH, OPEN_TERRAIN_ACRES)["non_season_pool"],
    )


def test_opening_the_last_closed_area_carries_the_day_to_a_fully_published_posture(api, mountain):
    """Once the third and last area opens, every area the season could open is open and the operating day's posture advances from partially to fully published.

    After any recompute, `PUBLISHED_PARTIAL → PUBLISHED_FULL` fires when `open_terrain_count` equals the number of the season's terrain areas whose `opening_state` is anything other than `SEASON_CLOSED` — that is, when everything that could be open is open.

    Design: Difficulty/combinatorial_formula/guest_capacity_evaluation_order_on_raw_ccc
    """
    state = _three_open_areas_under_two_lifts(mountain)
    before = validate_success(
        api.get_day_plan(state["day_plan_id"], GUEST_SERVICES_HEADERS)
    )
    assert before["posture"] == "PUBLISHED_PARTIAL"

    validate_success(
        api.decide_opening(
            state["last_area_id"], opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )

    plan = validate_success(
        api.get_day_plan(state["day_plan_id"], GUEST_SERVICES_HEADERS)
    )
    assert_integer(plan["open_terrain_count"], len(state["area_ids"]))
    assert plan["posture"] == "PUBLISHED_FULL"


def test_the_season_rollup_reports_every_openable_acre_as_open(api, mountain):
    """With all three areas open, the open acreage equals the acreage of everything not closed for the season, so the reported share of open terrain is the whole of it.

    The season snow and water accounting rollup reports, for one season, its `season_id`, `water_right_seasonal_af`, `water_used_af` as the sum of `water_af_actual` over `COMPLETED` sessions, `water_reserved_af` as the sum of `water_af_reserved` over `SCHEDULED`, `RUNNING` and `PAUSED` sessions, `water_right_remaining_af` as the seasonal right less those two figures, `snow_produced_swe_af` as the sum of `snow_swe_af` over `COMPLETED` sessions — each of these five rounded half up to three decimal places — `energy_cost_total_usd` as the sum of `energy_cost_usd` over `COMPLETED` sessions rounded half up to two decimals, `completed_session_count` and `aborted_session_count`, `open_area_count`, `open_acres` as the summed `acres` of `OPEN` areas, `openable_acres` as the summed `acres` of areas in `READY`, `OPEN` or `PATROL_HOLD`, both rounded half up to one decimal, and `terrain_open_pct` as `open_acres` divided by the summed `acres` of all areas not in `SEASON_CLOSED`, multiplied by one hundred and rounded half up to one decimal, reported as 0.0 when the season has no acreage at all.

    Design: Difficulty/combinatorial_formula/guest_capacity_evaluation_order_on_raw_ccc
    """
    state = _three_open_areas_under_two_lifts(mountain)

    validate_success(
        api.decide_opening(
            state["last_area_id"], opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )

    rollup = validate_success(
        api.get_season_snow_accounting(state["season_id"], GUEST_SERVICES_HEADERS)
    )
    assert_integer(rollup["open_area_count"], len(state["area_ids"]))
    assert_one_decimal(rollup["open_acres"], OPEN_TERRAIN_ACRES)
    assert_one_decimal(rollup["openable_acres"], OPEN_TERRAIN_ACRES)
    assert_one_decimal(rollup["terrain_open_pct"], 100.0)
