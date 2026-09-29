"""Derived mountain figures and the guest admission waterfall.

The readiness numbers on a terrain area are measured rather than declared: a
base depth collapsed out of the stake readings that are still recent enough to
count, a groom coverage percentage that discounts a winched pass and a black
pitch, and a terrain park risk score that grows faster than the feature list
once the park outgrows its free allowance. Those numbers roll up into the
operating day, where uphill capacity and open acreage decide how many guests
the mountain can comfortably carry, how many of them may hold a non-season
pass, and which arriving party is confirmed, waitlisted or turned away
outright. The behaviours grouped here pin the arithmetic of those figures at
their boundary values, the fixed order in which an admission decision consults
parking and the pass pool, the chronological sweep that reseats waitlisted
parties when a confirmed one gives its stalls back, and the way a snowmaking
session freezes the weather band it started in.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_errors import (
    ERR_DAY_PLAN_NOT_PUBLISHED,
    ERR_WORKFLOW_STATE_INVALID,
)
from test_helpers.assertions import (
    as_number,
    assert_instant_equals,
    assert_integer,
    assert_number_equals,
    assert_one_decimal,
    expected_base_depth,
    expected_capacity,
    expected_coverage_pct,
    expected_exposure_factor,
    expected_park_risk_score,
    expected_snow_yield_factor,
)
from test_helpers.factories import (
    close_day_payload,
    grooming_completion_payload,
    opening_decision_payload,
    park_build_payload,
    park_feature,
    reservation_payload,
    session_status_payload,
)
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    SNOWMAKING_HEADERS,
)


def test_base_depth_keeps_the_latest_measurement_of_each_stake_whatever_the_insert_order(
    api, mountain
):
    """A stake's newest measurement decides the base depth even when it was filed first.

    Within that window the readings are collapsed to one per stake: for each distinct `stake_code`, the reading with the greatest `measured_at` wins, and where two readings share that instant the one with the later `created_at` wins.

    Design: Corner/calculations/base_depth_collapses_to_the_latest_reading_per_stake_regardless_of_insert_order
    """
    mountain.set_clock("2026-08-01T06:00:00Z")
    season = mountain.create_season(base_depth_policy="MEAN_OF_STAKES")
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T1", name="Sunbowl", acres=18.0
    )

    mountain.record_reading(
        area["id"], stake_code="S1", depth_in=28.0, measured_at="2026-08-01T06:00:00Z"
    )
    mountain.record_reading(
        area["id"], stake_code="S1", depth_in=40.0, measured_at="2026-08-01T00:00:00Z"
    )

    after_stale_insert = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(after_stale_insert["base_depth_in"], 28.0)
    assert_integer(after_stale_insert["base_depth_stake_count"], 1)

    stake_rows, stake_meta = validate_paginated(
        api.list_snow_depth_readings(area["id"], GROOMING_HEADERS, stake_code="S1")
    )
    assert_integer(stake_meta["total_count"], 2)
    assert len(stake_rows) == 2, "Both readings for the stake must remain retrievable"

    mountain.record_reading(
        area["id"], stake_code="S2", depth_in=36.0, measured_at="2026-08-01T03:00:00Z"
    )

    after_second_stake = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(
        after_second_stake["base_depth_in"],
        expected_base_depth([28.0, 36.0], "MEAN_OF_STAKES"),
    )
    assert_one_decimal(after_second_stake["base_depth_in"], 32.0)
    assert_integer(after_second_stake["base_depth_stake_count"], 2)

    all_rows, all_meta = validate_paginated(
        api.list_snow_depth_readings(area["id"], GROOMING_HEADERS)
    )
    assert_integer(all_meta["total_count"], 3)
    assert len(all_rows) == 3, "Nothing was overwritten by the collapse"


def test_a_reading_older_than_the_two_day_lookback_leaves_the_base_depth_behind(api, mountain):
    """A stake measured 49 hours ago stops feeding the base depth of its area.

    Only readings whose `measured_at` falls inside a two-day lookback — that is, at or after the instant 48 hours before the current logical clock — are considered at all; anything older is discarded even when it is the only reading a stake has ever produced, which means `base_depth_stake_count` shrinks over time if the stakes go unread.

    Design: Corner/calculations/the_forty_eight_hour_lookback_drops_a_stale_stake_and_shrinks_the_count
    """
    mountain.set_clock("2026-08-01T00:00:00Z")
    season = mountain.create_season(base_depth_policy="MEAN_OF_STAKES")
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"], lift["id"], trail_code="T1", name="Sunbowl", acres=18.0
    )
    mountain.record_reading(
        area["id"], stake_code="S1", depth_in=40.0, measured_at="2026-08-01T00:00:00Z"
    )

    inside_the_window = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(inside_the_window["base_depth_in"], 40.0)
    assert_integer(inside_the_window["base_depth_stake_count"], 1)

    mountain.set_clock("2026-08-03T01:00:00Z")
    mountain.record_reading(
        area["id"], stake_code="S2", depth_in=36.0, measured_at="2026-08-03T01:00:00Z"
    )

    after_the_cutoff = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(after_the_cutoff["base_depth_in"], 36.0)
    assert_integer(after_the_cutoff["base_depth_stake_count"], 1)
    assert as_number(after_the_cutoff["base_depth_in"]) != 38.0, (
        "A mean over both stakes would be 38.0, which means the cutoff was never applied"
    )

    rows, meta = validate_paginated(
        api.list_snow_depth_readings(area["id"], GROOMING_HEADERS)
    )
    assert_integer(meta["total_count"], 2)
    assert len(rows) == 2, "The stale reading is excluded from the figure, not deleted"


def test_the_park_exposure_allowance_is_exactly_one_at_five_features_and_steps_after_that(
    api, mountain
):
    """Five features carry no exposure penalty, and each further feature adds a tenth.

    Six features therefore carry a factor of 1.1 and seven carry 1.2, while five features or fewer carry exactly 1.0 — the allowance is a floor at zero extra features, never a discount below 1.0.

    `park_risk_score` is the raw score multiplied by the exposure factor, rounded half up to one decimal place, then capped at 100.0 with the cap applied after the rounding.

    Design: Corner/calculations/park_risk_exposure_factor_is_exactly_one_at_five_features_and_steps_after
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"],
        lift["id"],
        trail_code="TP",
        name="Main Park",
        terrain_class="PARK",
        acres=18.0,
    )

    five_features = [
        park_feature("JUMP", "L"),
        park_feature("JUMP", "M"),
        park_feature("RAIL", "M"),
        park_feature("RAIL", "S"),
        park_feature("JIB", "S"),
    ]
    six_features = five_features + [park_feature("HALFPIPE", "S")]
    seven_features = six_features + [park_feature("HALFPIPE", "L")]
    ten_large_halfpipes = [park_feature("HALFPIPE", "L") for _ in range(10)]

    expected_scores = [
        (five_features, 5, 1.0, 34.0),
        (six_features, 6, 1.1, 50.6),
        (seven_features, 7, 1.2, 84.0),
        (ten_large_halfpipes, 10, 1.5, 100.0),
    ]

    previous_version = area["version"]
    for features, count, factor, score in expected_scores:
        built = validate_success(
            api.build_park(area["id"], park_build_payload(features), GROOMING_HEADERS)
        )
        assert_integer(built["park_feature_count"], count)
        assert_number_equals(expected_exposure_factor(count), factor)
        assert_one_decimal(built["park_risk_score"], score)
        assert_one_decimal(built["park_risk_score"], expected_park_risk_score(features))
        assert built["park_state"] == "PARK_BUILT", (
            f"A build leaves the park built, got {built['park_state']!r}"
        )
        assert built["park_inspected_by_user_id"] is None, (
            "A rebuild clears the previous inspection sign-off"
        )
        assert_integer(built["version"], previous_version + 1)
        previous_version = built["version"]

    final = validate_success(api.get_terrain_area(area["id"], DIRECTOR_HEADERS))
    assert_integer(final["park_feature_count"], 10)
    assert_one_decimal(final["park_risk_score"], 100.0)


def test_a_winched_black_route_grooms_at_seventy_two_percent_of_its_pass_acreage(api, mountain):
    """Winch and pitch discounts multiply into the coverage a completed groom reports.

    Groomed acreage is the number of passes multiplied by the swath a single cat pass covers — 0.75 acres per pass — then multiplied by two efficiency factors: a winch factor of 0.8 when `winch_required` is true and 1.0 otherwise, and a class factor of 0.9 when the area's `terrain_class` is `BLACK` and 1.0 otherwise.

    Coverage is never accumulated across tasks: only the completing task's own passes count, so the most recently completed task on an area defines that area's coverage outright.

    Design: Corner/calculations/groom_coverage_on_a_winched_black_route_applies_both_penalty_factors
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"],
        lift["id"],
        trail_code="T2",
        name="Northwoods",
        terrain_class="BLACK",
        acres=12.0,
        min_open_base_depth_in=30,
    )
    mountain.record_reading(area["id"], stake_code="S1", depth_in=40.0)
    mountain.create_patroller(
        season["id"],
        patroller_code="P1",
        cert_level="EMT",
        on_duty=True,
        assigned_terrain_area_id=area["id"],
    )
    mountain.create_patroller(
        season["id"],
        patroller_code="P2",
        cert_level="PARAMEDIC",
        on_duty=True,
        assigned_terrain_area_id=area["id"],
    )

    first_task = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=1,
        snowcat_unit_code="CAT-1",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T04:00:00Z",
        winch_required=True,
        winch_anchor_code="ANC-4",
    )
    mountain.dispatch_groom(first_task["id"])
    first_completed = validate_success(
        api.complete_grooming_task(
            first_task["id"], grooming_completion_payload(14), GROOMING_HEADERS
        )
    )
    assert_one_decimal(first_completed["coverage_pct"], 63.0)
    assert_one_decimal(
        first_completed["coverage_pct"],
        expected_coverage_pct(14, 12.0, winch_required=True, terrain_class="BLACK"),
    )

    short_of_the_floor = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(short_of_the_floor["groom_coverage_pct"], 63.0)
    assert short_of_the_floor["groom_ready"] is False, (
        "63.0 percent coverage is under the readiness floor"
    )
    assert short_of_the_floor["opening_state"] == "PREP", (
        f"The area stays in preparation, got {short_of_the_floor['opening_state']!r}"
    )

    second_task = mountain.plan_groom(
        area["id"],
        cat_route_code="R1",
        sequence_index=2,
        snowcat_unit_code="CAT-1",
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T08:00:00Z",
        winch_required=True,
        winch_anchor_code="ANC-4",
    )
    mountain.dispatch_groom(second_task["id"])
    second_completed = validate_success(
        api.complete_grooming_task(
            second_task["id"], grooming_completion_payload(23), GROOMING_HEADERS
        )
    )
    assert_one_decimal(second_completed["coverage_pct"], 100.0)
    assert_one_decimal(
        second_completed["coverage_pct"],
        expected_coverage_pct(23, 12.0, winch_required=True, terrain_class="BLACK"),
    )

    fully_groomed = validate_success(api.get_terrain_area(area["id"], GROOMING_HEADERS))
    assert_one_decimal(fully_groomed["groom_coverage_pct"], 100.0)
    assert fully_groomed["groom_ready"] is True, (
        "A capped coverage figure clears the readiness floor"
    )
    assert fully_groomed["opening_state"] == "READY", (
        f"Every other gate was already satisfied, got {fully_groomed['opening_state']!r}"
    )
    assert_instant_equals(fully_groomed["last_groomed_at"], "2026-08-01T00:00:00Z")

    unchanged_first = validate_success(
        api.get_grooming_task(first_task["id"], GROOMING_HEADERS)
    )
    assert_one_decimal(unchanged_first["coverage_pct"], 63.0)


def test_a_crowding_density_of_exactly_twenty_five_guests_per_acre_leaves_capacity_whole(
    api, mountain
):
    """The crowding reduction waits for a density strictly past 25.0 guests per acre.

    Fifth, a density factor of 0.85 applies when that density is strictly greater than 25.0 guests per acre, and 1.00 otherwise — a density of exactly 25.0 does not trigger the reduction.

    Either decision recomputes the season's `open_area_count` and increments the season's `version` by 1; recomputes the active day plan's `open_terrain_count`, `terrain_open_acres`, `open_lift_capacity_pph`, `raw_ccc`, `guest_capacity` and `non_season_pool` and increments the day plan's `version` by 1; and increments the area's own `version` by 1.

    Design: Corner/calculations/crowding_density_at_exactly_twenty_five_does_not_trigger_the_reduction
    """
    state = mountain.open_mountain(
        lift_overrides={"hourly_capacity_pph": 750, "wind_hold_threshold_mph": 40.0}
    )

    on_the_threshold = expected_capacity(750, 18.0)
    assert_number_equals(on_the_threshold["crowding_density"], 25.0)
    assert_number_equals(on_the_threshold["density_factor"], 1.00)

    at_full_capacity = validate_success(
        api.get_day_plan(state["day_plan_id"], DIRECTOR_HEADERS)
    )
    assert_integer(at_full_capacity["open_lift_capacity_pph"], 750)
    assert_one_decimal(at_full_capacity["terrain_open_acres"], 18.0)
    assert_integer(at_full_capacity["open_terrain_count"], 1)
    assert_integer(at_full_capacity["raw_ccc"], 450)
    assert_integer(at_full_capacity["guest_capacity"], 450)
    assert_integer(at_full_capacity["non_season_pool"], 315)
    assert_integer(at_full_capacity["guest_capacity"], on_the_threshold["guest_capacity"])
    assert_integer(at_full_capacity["non_season_pool"], on_the_threshold["non_season_pool"])

    narrower = mountain.create_terrain_area(
        state["season_id"],
        state["lift_id"],
        trail_code="T2",
        name="Cornice Chute",
        terrain_class="BLUE",
        acres=15.0,
        min_open_base_depth_in=30,
    )
    mountain.record_reading(narrower["id"], stake_code="S9", depth_in=40.0)
    mountain.groom_area(
        narrower["id"],
        20,
        cat_route_code="R2",
        sequence_index=1,
        snowcat_unit_code="CAT-2",
        window_start="2026-08-01T00:00:00Z",
        window_end="2026-08-01T04:00:00Z",
    )
    mountain.create_patroller(
        state["season_id"],
        patroller_code="P3",
        cert_level="EMT",
        on_duty=True,
        assigned_terrain_area_id=narrower["id"],
    )
    mountain.create_patroller(
        state["season_id"],
        patroller_code="P4",
        cert_level="PARAMEDIC",
        on_duty=True,
        assigned_terrain_area_id=narrower["id"],
    )
    mountain.decide_opening(narrower["id"], "OPEN")

    validate_success(
        api.decide_opening(
            state["area_id"], opening_decision_payload("CLOSE"), DIRECTOR_HEADERS
        )
    )

    past_the_threshold = expected_capacity(750, 15.0)
    assert_number_equals(past_the_threshold["crowding_density"], 30.0)
    assert_number_equals(past_the_threshold["density_factor"], 0.85)

    reduced = validate_success(api.get_day_plan(state["day_plan_id"], DIRECTOR_HEADERS))
    assert_integer(reduced["open_lift_capacity_pph"], 750)
    assert_one_decimal(reduced["terrain_open_acres"], 15.0)
    assert_integer(reduced["open_terrain_count"], 1)
    assert_integer(reduced["raw_ccc"], 450)
    assert_integer(reduced["guest_capacity"], 382)
    assert_integer(reduced["non_season_pool"], 267)
    assert_integer(reduced["guest_capacity"], past_the_threshold["guest_capacity"])
    assert_integer(reduced["non_season_pool"], past_the_threshold["non_season_pool"])


def test_admission_reports_parking_before_the_pass_pool_and_a_season_party_skips_the_pool(
    api, mountain
):
    """The first failing bucket names the reason, and a season pass never meets the pool.

    The outcome is decided by a waterfall of four buckets consumed in a fixed order, and the first bucket that fails decides the outcome — no later bucket is consulted and no earlier one is revisited.

    Bucket two is the pass-class pool, which `SEASON` and `EMPLOYEE` parties bypass entirely: for a `RECIPROCAL` or `DAY_TICKET` party, `non_season_admitted_count` plus `party_size` exceeding `non_season_pool` sets `WAITLISTED` with `waitlist_reason` `CAPACITY`.

    Design: Corner/calculations/admission_reports_parking_before_the_pool_and_season_passes_bypass_the_pool
    """
    state = mountain.open_mountain(
        lift_overrides={"hourly_capacity_pph": 20, "wind_hold_threshold_mph": 40.0},
        day_plan_overrides={"parking_stalls_total": 2},
    )
    day_plan_id = state["day_plan_id"]

    sized_down = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    tight_day = expected_capacity(20, 18.0)
    assert_integer(sized_down["raw_ccc"], 12)
    assert_integer(sized_down["guest_capacity"], 12)
    assert_integer(sized_down["non_season_pool"], 8)
    assert_integer(sized_down["parking_stalls_total"], 2)
    assert_integer(sized_down["guest_capacity"], tight_day["guest_capacity"])
    assert_integer(sized_down["non_season_pool"], tight_day["non_season_pool"])

    busts_parking_and_the_pool = validate_success(
        api.create_reservation(
            reservation_payload(
                day_plan_id,
                sized_down["version"],
                party_code="PC-1",
                pass_type="DAY_TICKET",
                party_size=9,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert busts_parking_and_the_pool["state"] == "WAITLISTED", (
        f"Three vehicles do not fit two stalls, got {busts_parking_and_the_pool['state']!r}"
    )
    assert busts_parking_and_the_pool["waitlist_reason"] == "PARKING", (
        "Parking is tested before the pass-class pool"
    )
    assert_integer(busts_parking_and_the_pool["allocated_stalls"], 0)

    busts_only_the_pool = validate_success(
        api.create_reservation(
            reservation_payload(
                day_plan_id,
                mountain.day_plan_version(day_plan_id),
                party_code="PC-2",
                pass_type="DAY_TICKET",
                party_size=9,
                vehicle_count=1,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert busts_only_the_pool["state"] == "WAITLISTED", (
        f"Nine day tickets do not fit a pool of eight, got {busts_only_the_pool['state']!r}"
    )
    assert busts_only_the_pool["waitlist_reason"] == "CAPACITY", (
        "With one vehicle the party clears parking and fails the pool"
    )

    bypasses_the_pool = validate_success(
        api.create_reservation(
            reservation_payload(
                day_plan_id,
                mountain.day_plan_version(day_plan_id),
                party_code="PC-3",
                pass_type="SEASON",
                party_size=9,
                vehicle_count=1,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert bypasses_the_pool["state"] == "CONFIRMED", (
        f"A season party never meets the pool, got {bypasses_the_pool['state']!r}"
    )
    assert bypasses_the_pool["waitlist_reason"] == "NONE"
    assert_integer(bypasses_the_pool["allocated_stalls"], 1)
    assert_instant_equals(bypasses_the_pool["confirmed_at"], "2026-08-01T00:00:00Z")

    counters = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(counters["admitted_guest_count"], 9)
    assert_integer(counters["non_season_admitted_count"], 0)
    assert_integer(counters["waitlisted_guest_count"], 18)
    assert_integer(counters["parking_stalls_used"], 1)


def test_a_party_larger_than_the_whole_mountain_is_denied_and_cannot_be_released(api, mountain):
    """A party that cannot fit an empty mountain is turned away for good, not waitlisted.

    Bucket zero is whole-mountain sanity: a party whose `party_size` alone exceeds the day's `guest_capacity` is set to `DENIED` with `waitlist_reason` `NONE` and `allocated_stalls` 0, and `DENIED` is terminal — such a party is never waitlisted, because no release could ever make it fit.

    Exact fits are admissions, not rejections: a party that consumes the last remaining seat of the pool is confirmed.

    Design: Corner/calculations/a_party_larger_than_guest_capacity_is_denied_and_can_never_be_promoted
    """
    state = mountain.open_mountain(
        lift_overrides={"hourly_capacity_pph": 20, "wind_hold_threshold_mph": 40.0},
        day_plan_overrides={"parking_stalls_total": 2},
    )
    day_plan_id = state["day_plan_id"]

    sized_down = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(sized_down["guest_capacity"], 12)

    denied = validate_success(
        api.create_reservation(
            reservation_payload(
                day_plan_id,
                sized_down["version"],
                party_code="PC-1",
                pass_type="DAY_TICKET",
                party_size=13,
                vehicle_count=1,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert denied["state"] == "DENIED", (
        f"Thirteen guests exceed a capacity of twelve, got {denied['state']!r}"
    )
    assert denied["waitlist_reason"] == "NONE"
    assert_integer(denied["allocated_stalls"], 0)
    assert denied["confirmed_at"] is None, "A denied party was never confirmed"

    consumes_nothing = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(consumes_nothing["admitted_guest_count"], 0)
    assert_integer(consumes_nothing["waitlisted_guest_count"], 0)
    assert_integer(consumes_nothing["parking_stalls_used"], 0)

    validate_error(
        api.release_reservation(denied["id"], GUEST_SERVICES_HEADERS),
        ERR_WORKFLOW_STATE_INVALID,
        409,
    )

    exact_fit = validate_success(
        api.create_reservation(
            reservation_payload(
                day_plan_id,
                mountain.day_plan_version(day_plan_id),
                party_code="PC-2",
                pass_type="SEASON",
                party_size=12,
                vehicle_count=1,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert exact_fit["state"] == "CONFIRMED", (
        f"Twelve guests do not exceed twelve, got {exact_fit['state']!r}"
    )
    assert exact_fit["waitlist_reason"] == "NONE"
    assert_integer(exact_fit["allocated_stalls"], 1)


def test_the_promotion_sweep_walks_past_a_waitlisted_party_that_still_cannot_park(api, mountain):
    """A release reseats the party behind the one that still does not fit.

    A candidate that still does not fit is skipped and left `WAITLISTED`, and — critically — the sweep continues past it rather than stopping.

    Design: Corner/calculations/the_waitlist_promotion_sweep_does_not_stop_at_the_first_candidate_that_still_does_not_fit
    """
    state = mountain.open_mountain(
        lift_overrides={"hourly_capacity_pph": 20, "wind_hold_threshold_mph": 40.0},
        day_plan_overrides={"parking_stalls_total": 4},
    )
    day_plan_id = state["day_plan_id"]

    sized_down = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(sized_down["guest_capacity"], 12)
    assert_integer(sized_down["parking_stalls_total"], 4)

    holds_every_stall = mountain.create_reservation(
        day_plan_id,
        party_code="PC-C1",
        pass_type="SEASON",
        party_size=6,
        vehicle_count=4,
    )
    assert holds_every_stall["state"] == "CONFIRMED", (
        f"Four vehicles fit a four stall lot, got {holds_every_stall['state']!r}"
    )
    assert_integer(holds_every_stall["allocated_stalls"], 4)

    never_fits = mountain.create_reservation(
        day_plan_id,
        party_code="PC-W1",
        pass_type="SEASON",
        party_size=3,
        vehicle_count=5,
    )
    assert never_fits["state"] == "WAITLISTED"
    assert never_fits["waitlist_reason"] == "PARKING"

    fits_after_a_release = mountain.create_reservation(
        day_plan_id,
        party_code="PC-W2",
        pass_type="SEASON",
        party_size=2,
        vehicle_count=1,
    )
    assert fits_after_a_release["state"] == "WAITLISTED"
    assert fits_after_a_release["waitlist_reason"] == "PARKING"

    released = validate_success(
        api.release_reservation(holds_every_stall["id"], GUEST_SERVICES_HEADERS)
    )
    assert released["state"] == "RELEASED"
    assert_integer(released["allocated_stalls"], 0)

    skipped = validate_success(api.get_reservation(never_fits["id"], GUEST_SERVICES_HEADERS))
    assert skipped["state"] == "WAITLISTED", (
        f"Five vehicles never fit a four stall lot, got {skipped['state']!r}"
    )
    assert skipped["waitlist_reason"] == "PARKING"
    assert_integer(skipped["allocated_stalls"], 0)

    promoted = validate_success(
        api.get_reservation(fits_after_a_release["id"], GUEST_SERVICES_HEADERS)
    )
    assert promoted["state"] == "CONFIRMED", (
        f"The sweep continued past the party that could not park, got {promoted['state']!r}"
    )
    assert promoted["waitlist_reason"] == "NONE"
    assert_integer(promoted["allocated_stalls"], 1)
    assert_instant_equals(promoted["confirmed_at"], "2026-08-01T00:00:00Z")

    counters = validate_success(api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS))
    assert_integer(counters["admitted_guest_count"], 2)
    assert_integer(counters["waitlisted_guest_count"], 3)
    assert_integer(counters["parking_stalls_used"], 1)


def test_a_session_freezes_the_wet_bulb_band_it_started_in(api, mountain):
    """A band edge belongs to the colder band, and the factor is fixed at the start.

    Otherwise, a wet bulb above 24.0 sets `snow_yield_factor` to 0.60; a wet bulb at or below 24.0 but above 20.0 sets it to 0.85; and a wet bulb at or below 20.0 sets it to 1.00.

    A later weather update on its own never retroactively changes the factor of a session already running.

    Design: Corner/calculations/wet_bulb_band_boundaries_fall_into_the_colder_band_and_are_frozen_at_start
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wet_bulb_f=24.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400, "gun_count": 40},
    )

    first_session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T05:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        gun_count=30,
        gpm=1200,
    )
    on_the_upper_edge = validate_success(
        api.set_session_status(
            first_session["id"], session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        )
    )
    assert on_the_upper_edge["state"] == "RUNNING"
    assert_one_decimal(on_the_upper_edge["wet_bulb_f"], 24.0)
    assert_number_equals(on_the_upper_edge["snow_yield_factor"], 0.85)
    assert_number_equals(expected_snow_yield_factor(24.0), 0.85)

    mountain.post_weather(state["day_plan_id"], wet_bulb_f=20.0)

    second_session = mountain.schedule_session(
        state["area_id"],
        state["pump_house_id"],
        window_start="2026-08-01T12:00:00Z",
        window_end="2026-08-01T19:00:00Z",
        gun_count=30,
        gpm=1200,
    )
    on_the_lower_edge = validate_success(
        api.set_session_status(
            second_session["id"], session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        )
    )
    assert on_the_lower_edge["state"] == "RUNNING"
    assert_one_decimal(on_the_lower_edge["wet_bulb_f"], 20.0)
    assert_number_equals(on_the_lower_edge["snow_yield_factor"], 1.00)
    assert_number_equals(expected_snow_yield_factor(20.0), 1.00)

    unmoved = validate_success(api.get_session(first_session["id"], SNOWMAKING_HEADERS))
    assert unmoved["state"] == "RUNNING"
    assert_one_decimal(unmoved["wet_bulb_f"], 24.0)
    assert_number_equals(unmoved["snow_yield_factor"], 0.85)

    plant = validate_success(api.get_pump_house(state["pump_house_id"], SNOWMAKING_HEADERS))
    assert_integer(plant["active_session_count"], 2)
    assert_integer(plant["peak_committed_gpm"], 1200)


def test_closing_the_day_leaves_a_paused_session_with_no_plan_to_resume_against(api, mountain):
    """A draft plan is never today's plan, and a closed one stops being today's plan.

    Plans in `DRAFT` and `DAY_CLOSED` are excluded; a plan on `WEATHER_HOLD` deliberately remains active, so that wind readings and hold releases still resolve against it.

    If no candidate exists — a season whose only plan is still a draft, for example — every operation that needs an active plan is rejected with `ERR_DAY_PLAN_NOT_PUBLISHED` (HTTP 409).

    Design: Corner/calculations/the_active_day_plan_selector_excludes_draft_and_day_closed_plans
    """
    state = mountain.open_mountain(
        lift_overrides={"wind_hold_threshold_mph": 40.0},
        wet_bulb_f=22.0,
        with_pump_house=True,
        pump_house_overrides={"max_gpm": 2400, "gun_count": 40},
    )
    later_dated_draft = mountain.create_day_plan(
        state["season_id"], operating_date="2026-08-02", parking_stalls_total=500
    )
    assert later_dated_draft["posture"] == "DRAFT", (
        f"The next day is only planned, got {later_dated_draft['posture']!r}"
    )

    session = mountain.schedule_session(state["area_id"], state["pump_house_id"])
    running = validate_success(
        api.set_session_status(
            session["id"], session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        )
    )
    assert running["state"] == "RUNNING"
    assert_one_decimal(running["wet_bulb_f"], 22.0)

    paused = validate_success(
        api.set_session_status(
            session["id"], session_status_payload("PAUSED"), SNOWMAKING_HEADERS
        )
    )
    assert paused["state"] == "PAUSED"
    minutes_before_the_rejection = paused["accumulated_run_minutes"]

    closed = validate_success(
        api.close_day(state["day_plan_id"], DIRECTOR_HEADERS, close_day_payload(False))
    )
    assert closed["posture"] == "DAY_CLOSED", (
        f"The operating day is over, got {closed['posture']!r}"
    )
    put_to_bed = validate_success(api.get_terrain_area(state["area_id"], DIRECTOR_HEADERS))
    assert put_to_bed["opening_state"] == "CLOSED"
    stopped = validate_success(api.get_lift(state["lift_id"], DIRECTOR_HEADERS))
    assert stopped["service_status"] == "CLOSED"

    validate_error(
        api.set_session_status(
            session["id"], session_status_payload("RUNNING"), SNOWMAKING_HEADERS
        ),
        ERR_DAY_PLAN_NOT_PUBLISHED,
        409,
    )

    still_paused = validate_success(api.get_session(session["id"], SNOWMAKING_HEADERS))
    assert still_paused["state"] == "PAUSED", (
        f"The rejected resume left the session alone, got {still_paused['state']!r}"
    )
    assert_integer(still_paused["accumulated_run_minutes"], minutes_before_the_rejection)

    season = validate_success(api.get_season(state["season_id"], DIRECTOR_HEADERS))
    assert season["season_state"] == "OPERATING", (
        "A close that is not final leaves the season operating"
    )
