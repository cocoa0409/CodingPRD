"""Read-only mountain rollups and the error families that guard every identifier.

Two reads close the operating loop: the season snow-and-water accounting rollup and
the terrain opening report for one operating day. Both are projections of stored
state, so their figures have to agree with the rows that feed them — the lifts that
are actually OPEN, the areas that are open or merely openable, and the sessions whose
water is used, reserved or released. Alongside them sit the families of refusal that
every request has to pass through first: a bogus path segment answers with its own
typed not-found code, a body reference from another season is a cross-season refusal
rather than a missing row, an acting patroller who cannot be resolved is unauthorized
while one who is merely off duty is not, and a payload that breaks its own schema is
reported ahead of any business rule it happens to break as well.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_CROSS_SEASON_REFERENCE,
    ERR_DAY_PLAN_NOT_FOUND,
    ERR_ENERGY_WINDOW_COVERAGE_GAP,
    ERR_GROOMING_TASK_NOT_FOUND,
    ERR_INCIDENT_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_LIFT_NOT_FOUND,
    ERR_MISSION_NOT_FOUND,
    ERR_PATROLLER_NOT_FOUND,
    ERR_PATROLLER_NOT_ON_DUTY,
    ERR_PUMP_HOUSE_NOT_FOUND,
    ERR_READING_TIMESTAMP_FUTURE,
    ERR_RECORD_NOT_FOUND,
    ERR_RESERVATION_NOT_FOUND,
    ERR_SEASON_NOT_FOUND,
    ERR_SEASON_NOT_OPERATING,
    ERR_SESSION_NOT_FOUND,
    ERR_SOD_VIOLATION,
    ERR_STAFF_ASSIGNMENT_NOT_FOUND,
    ERR_TERRAIN_AREA_NOT_FOUND,
    ERR_UNAUTHORIZED,
    ERR_WORKFLOW_STATE_INVALID,
)
from test_helpers.assertions import (
    OPENING_REPORT_FIELDS,
    SNOW_ACCOUNTING_FIELDS,
    assert_accounting_identity,
    assert_fields_present,
    assert_instant_equals,
    assert_integer,
    assert_one_decimal,
    assert_usd,
    assert_water_af,
    find_row,
)
from test_helpers.constants import INITIAL_CLOCK
from test_helpers.test_users import (
    DIRECTOR_HEADERS,
    GROOMING_HEADERS,
    GUEST_SERVICES_HEADERS,
    LIFT_OPS_HEADERS,
    SNOWMAKING_HEADERS,
    make_patroller_headers,
)

# A second well-formed identifier that belongs to no row, for the requests that
# have to carry two unresolvable references at once.
OTHER_MISSING_UUID = "00000000-0000-0000-0000-0000000000fe"


def test_the_opening_report_counts_only_open_lifts_and_re_evaluates_crowding_when_a_second_lift_opens(
    api, mountain
):
    """Only lifts in OPEN feed the uphill capacity, and the crowding threshold is re-tested on the raw figure alone.

    First, `open_lift_capacity_pph` is the sum of `hourly_capacity_pph` across the season's lifts whose `service_status` is `OPEN`; a lift on a wind or mechanical hold contributes nothing at all.

    Fifth, a density factor of 0.85 applies when that density is strictly greater than 25.0 guests per acre, and 1.00 otherwise — a density of exactly 25.0 does not trigger the reduction.

    Design: Corner/endpoints/the_opening_report_counts_only_open_lifts_and_re_evaluates_crowding_on_every_change
    """
    state = mountain.open_mountain(
        lift_overrides={"hourly_capacity_pph": 750, "wind_hold_threshold_mph": 40.0}
    )
    day_plan_id = state["day_plan_id"]

    opening = validate_success(
        api.get_opening_report(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    assert_fields_present(opening, OPENING_REPORT_FIELDS)
    assert opening["day_plan_id"] == day_plan_id
    assert opening["posture"] == "PUBLISHED_FULL"
    assert_integer(opening["open_terrain_count"], 1)
    assert_one_decimal(opening["terrain_open_acres"], 18.0)
    assert_one_decimal(opening["openable_acres"], 18.0)
    assert_one_decimal(opening["terrain_open_pct"], 100.0)
    # 750 uphill at the 0.60 utilisation factor is a raw_ccc of 450, and 450 over
    # 18.0 acres is a density of exactly 25.0, which does not trip the reduction.
    assert_integer(opening["open_lift_capacity_pph"], 750)
    assert_integer(opening["raw_ccc"], 450)
    assert_integer(opening["guest_capacity"], 450)
    assert_integer(opening["non_season_pool"], 315)
    assert_integer(opening["admitted_guest_count"], 0)
    assert_integer(opening["non_season_admitted_count"], 0)
    assert_integer(opening["waitlisted_guest_count"], 0)
    assert_integer(opening["parking_stalls_total"], 500)
    assert_integer(opening["parking_stalls_used"], 0)
    assert_integer(opening["held_area_count"], 0)
    assert_integer(opening["wind_held_lift_count"], 0)
    assert_integer(opening["mech_held_lift_count"], 0)

    carpet = mountain.create_lift(
        state["season_id"],
        lift_code="L2",
        name="Learning Carpet",
        lift_type="SURFACE",
        wind_hold_threshold_mph=40.0,
        hourly_capacity_pph=60,
        required_operator_count=1,
    )
    mountain.inspect_lift(carpet["id"], "PASS")
    mountain.assign_operator(
        carpet["id"], operator_code="OP-3", role_on_lift="TOP_OP"
    )
    mountain.set_lift_status(carpet["id"], "STANDBY")

    on_standby = validate_success(
        api.get_opening_report(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    assert_integer(on_standby["open_lift_capacity_pph"], 750)
    assert_integer(on_standby["raw_ccc"], 450)
    assert_integer(on_standby["guest_capacity"], 450)
    assert_integer(on_standby["non_season_pool"], 315)
    assert_integer(on_standby["open_terrain_count"], 1)
    assert_one_decimal(on_standby["terrain_open_acres"], 18.0)

    mountain.set_lift_status(carpet["id"], "OPEN")

    crowded = validate_success(
        api.get_opening_report(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    # 810 uphill gives a raw_ccc of 486 and a density of 27.0, which is strictly
    # above 25.0, so the 0.85 factor applies once, on the raw figure.
    assert_integer(crowded["open_lift_capacity_pph"], 810)
    assert_integer(crowded["raw_ccc"], 486)
    assert_integer(crowded["guest_capacity"], 413)
    assert_integer(crowded["non_season_pool"], 289)
    assert crowded["guest_capacity"] < crowded["raw_ccc"]
    assert_integer(crowded["open_terrain_count"], 1)
    assert_one_decimal(crowded["terrain_open_acres"], 18.0)

    stored = validate_success(api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))
    assert_integer(stored["open_lift_capacity_pph"], 810)
    assert_integer(stored["raw_ccc"], 486)
    assert_integer(stored["guest_capacity"], 413)
    assert_integer(stored["non_season_pool"], 289)


def test_snow_accounting_opens_at_the_full_water_right_and_keeps_openable_acres_apart_from_the_open_percentage(
    api, mountain
):
    """The accounting rollup starts with the whole seasonal right unspent, and a closed area drops out of open acres and the open percentage while its reservation stands.

    Concretely, `water_used_af` accumulates the metered draw of completed sessions, `water_reserved_af` holds the planned reservations of sessions that are still scheduled, running or paused, and the remaining allowance is the seasonal right less both figures.

    The season snow and water accounting rollup reports, for one season, its `season_id`, `water_right_seasonal_af`, `water_used_af` as the sum of `water_af_actual` over `COMPLETED` sessions, `water_reserved_af` as the sum of `water_af_reserved` over `SCHEDULED`, `RUNNING` and `PAUSED` sessions, `water_right_remaining_af` as the seasonal right less those two figures, `snow_produced_swe_af` as the sum of `snow_swe_af` over `COMPLETED` sessions — each of these five rounded half up to three decimal places — `energy_cost_total_usd` as the sum of `energy_cost_usd` over `COMPLETED` sessions rounded half up to two decimals, `completed_session_count` and `aborted_session_count`, `open_area_count`, `open_acres` as the summed `acres` of `OPEN` areas, `openable_acres` as the summed `acres` of areas in `READY`, `OPEN` or `PATROL_HOLD`, both rounded half up to one decimal, and `terrain_open_pct` as `open_acres` divided by the summed `acres` of all areas not in `SEASON_CLOSED`, multiplied by one hundred and rounded half up to one decimal, reported as 0.0 when the season has no acreage at all.

    Design: Corner/endpoints/snow_accounting_starts_at_the_full_water_right_and_openable_acres_diverge_from_the_open_percentage
    """
    state = mountain.open_mountain(with_pump_house=True)
    season_id = state["season_id"]
    area_id = state["area_id"]

    untouched = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_fields_present(untouched, SNOW_ACCOUNTING_FIELDS)
    assert untouched["season_id"] == season_id
    assert_water_af(untouched["water_right_seasonal_af"], 250.000)
    assert_water_af(untouched["water_used_af"], 0.000)
    assert_water_af(untouched["water_reserved_af"], 0.000)
    assert_water_af(untouched["snow_produced_swe_af"], 0.000)
    assert_water_af(untouched["water_right_remaining_af"], 250.000)
    assert_usd(untouched["energy_cost_total_usd"], 0.00)
    assert_integer(untouched["completed_session_count"], 0)
    assert_integer(untouched["aborted_session_count"], 0)
    assert_integer(untouched["open_area_count"], 1)
    assert_one_decimal(untouched["open_acres"], 18.0)
    assert_one_decimal(untouched["openable_acres"], 18.0)
    assert_one_decimal(untouched["terrain_open_pct"], 100.0)
    assert_accounting_identity(untouched)

    session = validate_success(
        api.create_session(
            f.session_payload(
                area_id, state["pump_house_id"], mountain.area_version(area_id)
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert session["state"] == "SCHEDULED"
    assert_integer(session["planned_minutes"], 420)
    assert_water_af(session["water_af_reserved"], 1.547)
    # The CLOSED -> PREP side effect of a create only applies from CLOSED, so an
    # area that is already open is left where it stands.
    assert mountain.area(area_id)["opening_state"] == "OPEN"

    with_reservation = validate_success(
        api.get_season_snow_accounting(season_id, SNOWMAKING_HEADERS)
    )
    assert_water_af(with_reservation["water_reserved_af"], 1.547)
    assert_water_af(with_reservation["water_used_af"], 0.000)
    assert_water_af(with_reservation["water_right_remaining_af"], 248.453)
    assert_integer(with_reservation["completed_session_count"], 0)
    assert_integer(with_reservation["aborted_session_count"], 0)
    assert_accounting_identity(with_reservation)

    closed = validate_success(
        api.decide_opening(
            area_id, f.opening_decision_payload("CLOSE"), DIRECTOR_HEADERS
        )
    )
    assert closed["opening_state"] == "CLOSED"
    still_scheduled = validate_success(
        api.get_session(session["id"], SNOWMAKING_HEADERS)
    )
    assert still_scheduled["state"] == "SCHEDULED"
    assert still_scheduled["abort_reason"] is None

    after_close = validate_success(
        api.get_season_snow_accounting(season_id, DIRECTOR_HEADERS)
    )
    assert_integer(after_close["open_area_count"], 0)
    assert_one_decimal(after_close["open_acres"], 0.0)
    assert_one_decimal(after_close["openable_acres"], 0.0)
    assert_one_decimal(after_close["terrain_open_pct"], 0.0)
    assert_water_af(after_close["water_reserved_af"], 1.547)
    assert_water_af(after_close["water_used_af"], 0.000)
    assert_water_af(after_close["water_right_remaining_af"], 248.453)
    assert_accounting_identity(after_close)


def test_the_duty_toggle_pushes_the_open_area_onto_a_patrol_hold_but_coming_back_on_duty_never_reopens_it(
    api, mountain
):
    """One boolean on one endpoint runs the staffing cascade in one direction only: the area falls to PATROL_HOLD and stays there when the patroller returns.

    Either way the assigned area's count is recomputed, and when the recomputed count falls below the season's `min_patrollers_per_open_area` while that area is `OPEN`, the area is pushed `OPEN → PATROL_HOLD` with the full downstream chain — grooming tasks deferred, snowmaking sessions aborted, water reservations released, the active day plan's counters and posture recomputed.

    Coming back on duty may re-satisfy the readiness gates and fire `PREP → READY`, but an area already sitting on `PATROL_HOLD` is never auto-reopened by a duty change.

    Design: Corner/endpoints/the_duty_toggle_is_one_endpoint_whose_payload_decides_whether_a_cascade_runs
    """
    state = mountain.open_mountain()
    area_id = state["area_id"]
    day_plan_id = state["day_plan_id"]
    second_patroller = state["patroller_ids"][1]

    fully_open = validate_success(api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))
    # 1800 uphill gives a raw_ccc of 1080 and a density of 60.0 over 18.0 acres,
    # so the 0.85 factor applies: 918 admissible guests and a 642 non-season pool.
    assert_integer(fully_open["raw_ccc"], 1080)
    assert_integer(fully_open["guest_capacity"], 918)
    assert_integer(fully_open["non_season_pool"], 642)
    assert fully_open["posture"] == "PUBLISHED_FULL"

    off_duty = validate_success(
        api.set_patroller_duty(
            second_patroller, f.duty_payload(False), DIRECTOR_HEADERS
        )
    )
    assert off_duty["on_duty"] is False
    assert off_duty["status"] == "OFF_DUTY"

    held = validate_success(api.get_terrain_area(area_id, DIRECTOR_HEADERS))
    assert_integer(held["assigned_patroller_count"], 1)
    assert held["opening_state"] == "PATROL_HOLD"

    partial = validate_success(api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))
    assert partial["posture"] == "PUBLISHED_PARTIAL"
    assert_integer(partial["open_terrain_count"], 0)
    assert_one_decimal(partial["terrain_open_acres"], 0.0)
    # With no acreage open the density is 0.0, so the factor reverts to 1.00 and
    # the admissible count climbs back to the unreduced raw_ccc.
    assert_integer(partial["raw_ccc"], 1080)
    assert_integer(partial["guest_capacity"], 1080)
    assert_integer(partial["non_season_pool"], 756)

    back_on_duty = validate_success(
        api.set_patroller_duty(
            second_patroller, f.duty_payload(True), DIRECTOR_HEADERS
        )
    )
    assert back_on_duty["on_duty"] is True
    assert back_on_duty["status"] == "AVAILABLE"

    still_held = validate_success(api.get_terrain_area(area_id, DIRECTOR_HEADERS))
    assert_integer(still_held["assigned_patroller_count"], 2)
    assert still_held["opening_state"] == "PATROL_HOLD"

    reopened = validate_success(
        api.decide_opening(
            area_id, f.opening_decision_payload("OPEN"), DIRECTOR_HEADERS
        )
    )
    assert reopened["opening_state"] == "OPEN"

    republished = validate_success(api.get_day_plan(day_plan_id, DIRECTOR_HEADERS))
    assert republished["posture"] == "PUBLISHED_FULL"
    assert_integer(republished["guest_capacity"], 918)


def test_a_new_snowmaking_session_supersedes_only_the_overlapping_scheduled_peer_and_hands_back_its_reservation(
    api, mountain
):
    """A create aborts the scheduled peer whose window overlaps it, refunds that peer's reserved water, and leaves a merely adjacent window alone.

    And any session on that same terrain area that is still `SCHEDULED` and whose window overlaps the new one is superseded: it moves `SCHEDULED → ABORTED` with `abort_reason` `SUPERSEDED`, its `water_af_reserved` is subtracted back out of the season's `water_reserved_af`, and its own `version` increments by 1.

    The session's `planned_minutes` is the number of whole minutes between `window_start` and `window_end`, and the water it reserves follows directly: the committed flow in gallons per minute is multiplied by `planned_minutes` to give gallons, that total is divided by the 325,851 gallons that make up one acre-foot, and the quotient is rounded half up to three decimal places to give `water_af_reserved`.

    Design: Corner/endpoints/a_new_session_supersedes_only_the_overlapping_peer_on_the_same_area_and_refunds_its_reservation
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"])
    pump_house = mountain.create_pump_house(season["id"])
    assert area["opening_state"] == "CLOSED"

    first = validate_success(
        api.create_session(
            f.session_payload(
                area["id"], pump_house["id"], mountain.area_version(area["id"])
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert first["state"] == "SCHEDULED"
    assert_integer(first["planned_minutes"], 420)
    assert_water_af(first["water_af_reserved"], 1.547)
    assert mountain.area(area["id"])["opening_state"] == "PREP"

    reserved_season = mountain.season(season["id"])
    assert_water_af(reserved_season["water_reserved_af"], 1.547)
    assert_water_af(reserved_season["water_used_af"], 0.000)

    second = validate_success(
        api.create_session(
            f.session_payload(
                area["id"],
                pump_house["id"],
                mountain.area_version(area["id"]),
                window_start="2026-08-01T06:00:00Z",
                window_end="2026-08-01T10:00:00Z",
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert second["state"] == "SCHEDULED"
    assert_integer(second["planned_minutes"], 240)
    assert_water_af(second["water_af_reserved"], 0.884)

    superseded = validate_success(api.get_session(first["id"], SNOWMAKING_HEADERS))
    assert superseded["state"] == "ABORTED"
    assert superseded["abort_reason"] == "SUPERSEDED"
    assert_instant_equals(superseded["ended_at"], INITIAL_CLOCK)
    assert_water_af(superseded["water_af_actual"], 0.000)
    assert_water_af(superseded["snow_swe_af"], 0.000)
    assert_usd(superseded["energy_cost_usd"], 0.00)

    refunded = validate_success(
        api.get_season_snow_accounting(season["id"], SNOWMAKING_HEADERS)
    )
    assert_water_af(refunded["water_reserved_af"], 0.884)
    assert_water_af(refunded["water_used_af"], 0.000)
    assert_water_af(refunded["water_right_remaining_af"], 249.116)
    assert_integer(refunded["aborted_session_count"], 1)
    assert_integer(refunded["completed_session_count"], 0)
    assert_accounting_identity(refunded)

    third = validate_success(
        api.create_session(
            f.session_payload(
                area["id"],
                pump_house["id"],
                mountain.area_version(area["id"]),
                window_start="2026-08-01T12:00:00Z",
                window_end="2026-08-01T14:00:00Z",
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert_integer(third["planned_minutes"], 120)
    assert_water_af(third["water_af_reserved"], 0.442)

    untouched = validate_success(api.get_session(second["id"], SNOWMAKING_HEADERS))
    assert untouched["state"] == "SCHEDULED"
    assert untouched["abort_reason"] is None

    final = validate_success(
        api.get_season_snow_accounting(season["id"], SNOWMAKING_HEADERS)
    )
    assert_water_af(final["water_reserved_af"], 1.326)
    assert_water_af(final["water_used_af"], 0.000)
    assert_water_af(final["water_right_remaining_af"], 248.674)
    assert_accounting_identity(final)


def test_checking_a_party_in_at_the_gate_moves_no_admission_counter_and_leaves_the_day_plan_untouched(
    api, mountain
):
    """A gate check-in advances only the reservation, because the seat and the stalls were consumed when the party was confirmed.

    Checking a party in at the gate moves it `CONFIRMED → CHECKED_IN` and stamps `checked_in_at`; it is admissible only from `CONFIRMED`, requires the active day plan to be `PUBLISHED_PARTIAL` or `PUBLISHED_FULL`, and increments the reservation's `version` by 1.

    Check-in changes no counter, because a checked-in party consumed its seat and its stalls at confirmation.

    Design: Corner/endpoints/check_in_advances_the_reservation_without_moving_a_single_day_counter
    """
    state = mountain.open_mountain()
    day_plan_id = state["day_plan_id"]

    before_booking = validate_success(
        api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    reservation = validate_success(
        api.create_reservation(
            f.reservation_payload(
                day_plan_id,
                before_booking["version"],
                party_code="G1",
                pass_type="DAY_TICKET",
                party_size=10,
                vehicle_count=3,
            ),
            GUEST_SERVICES_HEADERS,
        ),
        201,
    )
    assert reservation["state"] == "CONFIRMED"
    assert reservation["waitlist_reason"] == "NONE"
    assert_integer(reservation["allocated_stalls"], 3)
    assert_instant_equals(reservation["confirmed_at"], INITIAL_CLOCK)

    on_confirmation = validate_success(
        api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    assert_integer(on_confirmation["admitted_guest_count"], 10)
    assert_integer(on_confirmation["non_season_admitted_count"], 10)
    assert_integer(on_confirmation["waitlisted_guest_count"], 0)
    assert_integer(on_confirmation["parking_stalls_used"], 3)

    checked_in = validate_success(
        api.check_in_reservation(reservation["id"], GUEST_SERVICES_HEADERS)
    )
    assert checked_in["state"] == "CHECKED_IN"
    assert_instant_equals(checked_in["checked_in_at"], INITIAL_CLOCK)
    assert checked_in["version"] == reservation["version"] + 1

    after_check_in = validate_success(
        api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    assert_integer(after_check_in["admitted_guest_count"], 10)
    assert_integer(after_check_in["non_season_admitted_count"], 10)
    assert_integer(after_check_in["waitlisted_guest_count"], 0)
    assert_integer(after_check_in["parking_stalls_used"], 3)
    assert after_check_in["version"] == on_confirmation["version"]

    validate_error(
        api.check_in_reservation(reservation["id"], GUEST_SERVICES_HEADERS),
        ERR_WORKFLOW_STATE_INVALID,
        409,
    )

    released = validate_success(
        api.release_reservation(reservation["id"], GUEST_SERVICES_HEADERS)
    )
    assert released["state"] == "RELEASED"
    assert_integer(released["allocated_stalls"], 0)
    assert_instant_equals(released["released_at"], INITIAL_CLOCK)

    after_release = validate_success(
        api.get_day_plan(day_plan_id, GUEST_SERVICES_HEADERS)
    )
    assert_integer(after_release["admitted_guest_count"], 0)
    assert_integer(after_release["non_season_admitted_count"], 0)
    assert_integer(after_release["parking_stalls_used"], 0)

    rows, meta = validate_paginated(
        api.list_day_plan_reservations(
            day_plan_id, GUEST_SERVICES_HEADERS, state="RELEASED"
        )
    )
    assert_integer(meta["total_count"], 1)
    assert len(rows) == 1
    assert rows[0]["id"] == reservation["id"]


def test_the_lift_roster_list_is_scoped_to_the_lift_in_the_path_and_its_state_and_role_filters_apply_together(
    api, mountain
):
    """A roster read returns only the addressed lift's assignments, keeps a released row listable, and intersects its two filters rather than uniting them.

    A lift's roster can be listed filtered by assignment `state` and by `role_on_lift`.

    `staffed_operator_count` on a lift is never typed in — it is the number of that lift's assignments in `state` `ASSIGNED` whose shift covers the current logical clock, meaning `shift_start` is at or before the clock and `shift_end` is strictly after it.

    Design: Corner/endpoints/the_staff_assignment_child_list_is_parent_scoped_and_its_two_filters_compose
    """
    season = mountain.create_season()
    summit = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(summit["id"], "PASS")
    top_operator = mountain.assign_operator(
        summit["id"], operator_code="OP-1", role_on_lift="TOP_OP"
    )
    mountain.assign_operator(
        summit["id"], operator_code="OP-2", role_on_lift="BOTTOM_OP"
    )

    carpet = mountain.create_lift(
        season["id"],
        lift_code="L2",
        name="Learning Carpet",
        lift_type="SURFACE",
        wind_hold_threshold_mph=40.0,
        hourly_capacity_pph=60,
        required_operator_count=1,
    )
    mountain.inspect_lift(carpet["id"], "PASS")
    mountain.assign_operator(
        carpet["id"], operator_code="OP-3", role_on_lift="TOP_OP"
    )
    mountain.release_operator(top_operator["id"])

    whole_roster, meta = validate_paginated(
        api.list_lift_staff_assignments(summit["id"], LIFT_OPS_HEADERS)
    )
    assert_integer(meta["total_count"], 2)
    assert {row["operator_code"] for row in whole_roster} == {"OP-1", "OP-2"}
    assert all(row["lift_id"] == summit["id"] for row in whole_roster)

    still_assigned, meta = validate_paginated(
        api.list_lift_staff_assignments(
            summit["id"], LIFT_OPS_HEADERS, state="ASSIGNED"
        )
    )
    assert_integer(meta["total_count"], 1)
    assert find_row(still_assigned, operator_code="OP-2")["state"] == "ASSIGNED"

    top_operators, meta = validate_paginated(
        api.list_lift_staff_assignments(
            summit["id"], LIFT_OPS_HEADERS, role_on_lift="TOP_OP"
        )
    )
    assert_integer(meta["total_count"], 1)
    assert find_row(top_operators, operator_code="OP-1")["state"] == "RELEASED"

    both_filters, meta = validate_paginated(
        api.list_lift_staff_assignments(
            summit["id"], LIFT_OPS_HEADERS, state="ASSIGNED", role_on_lift="TOP_OP"
        )
    )
    assert_integer(meta["total_count"], 0)
    assert both_filters == []

    carpet_roster, meta = validate_paginated(
        api.list_lift_staff_assignments(
            carpet["id"], LIFT_OPS_HEADERS, state="ASSIGNED"
        )
    )
    assert_integer(meta["total_count"], 1)
    assert find_row(carpet_roster, operator_code="OP-3")["lift_id"] == carpet["id"]

    summit_now = validate_success(api.get_lift(summit["id"], LIFT_OPS_HEADERS))
    assert_integer(summit_now["staffed_operator_count"], 1)
    assert summit_now["service_status"] == "CLOSED"

    carpet_now = validate_success(api.get_lift(carpet["id"], LIFT_OPS_HEADERS))
    assert_integer(carpet_now["staffed_operator_count"], 1)
    assert carpet_now["mechanical_status"] == "INSPECTION_PASSED"


def test_every_typed_not_found_code_is_reachable_from_a_bogus_path_segment_on_an_empty_mountain(
    api
):
    """Each resource family answers an unresolvable identifier in its own path with its own 404 code, and a path segment resolves before the action's workflow rules.

    Left-to-right resolution of every templated path segment — the family-specific 404 code, or `ERR_RECORD_NOT_FOUND`, on every endpoint that has a templated segment.

    Each resource family has its own not-found code: `ERR_SEASON_NOT_FOUND`, `ERR_TERRAIN_AREA_NOT_FOUND`, `ERR_LIFT_NOT_FOUND`, `ERR_PUMP_HOUSE_NOT_FOUND`, `ERR_SESSION_NOT_FOUND`, `ERR_GROOMING_TASK_NOT_FOUND`, `ERR_STAFF_ASSIGNMENT_NOT_FOUND`, `ERR_PATROLLER_NOT_FOUND`, `ERR_MISSION_NOT_FOUND`, `ERR_INCIDENT_NOT_FOUND`, `ERR_DAY_PLAN_NOT_FOUND` and `ERR_RESERVATION_NOT_FOUND` — all HTTP 404.

    Design: Corner/errors/every_typed_not_found_error_id_is_reachable_from_a_bogus_path_segment
    """
    missing = NON_EXISTENT_UUID
    reported = []

    def refuse(response, expected_error_id):
        reported.append(validate_error(response, expected_error_id, 404)["error_id"])

    refuse(api.get_season(missing, DIRECTOR_HEADERS), ERR_SEASON_NOT_FOUND)
    refuse(api.get_lift(missing, DIRECTOR_HEADERS), ERR_LIFT_NOT_FOUND)
    refuse(api.get_terrain_area(missing, DIRECTOR_HEADERS), ERR_TERRAIN_AREA_NOT_FOUND)
    refuse(api.get_pump_house(missing, DIRECTOR_HEADERS), ERR_PUMP_HOUSE_NOT_FOUND)
    refuse(api.get_session(missing, DIRECTOR_HEADERS), ERR_SESSION_NOT_FOUND)
    refuse(api.get_grooming_task(missing, DIRECTOR_HEADERS), ERR_GROOMING_TASK_NOT_FOUND)
    refuse(api.get_patroller(missing, DIRECTOR_HEADERS), ERR_PATROLLER_NOT_FOUND)
    refuse(api.get_mission(missing, DIRECTOR_HEADERS), ERR_MISSION_NOT_FOUND)
    refuse(api.get_incident(missing, DIRECTOR_HEADERS), ERR_INCIDENT_NOT_FOUND)
    refuse(api.get_day_plan(missing, DIRECTOR_HEADERS), ERR_DAY_PLAN_NOT_FOUND)
    refuse(
        api.get_reservation(missing, GUEST_SERVICES_HEADERS), ERR_RESERVATION_NOT_FOUND
    )
    # A derived read resolves its templated segment exactly like a plain read, so
    # it refuses rather than returning a zero-filled rollup.
    refuse(
        api.get_season_snow_accounting(missing, DIRECTOR_HEADERS), ERR_SEASON_NOT_FOUND
    )
    # And a templated segment on an action resolves before the action's own
    # workflow rule can be consulted.
    refuse(
        api.release_lift_staff_assignment(missing, LIFT_OPS_HEADERS),
        ERR_STAFF_ASSIGNMENT_NOT_FOUND,
    )

    assert len(reported) == 13
    assert len(set(reported)) == 12
    assert ERR_RECORD_NOT_FOUND not in reported


def test_a_body_reference_from_another_season_is_a_cross_season_refusal_while_an_unresolvable_one_is_a_not_found(
    api, mountain
):
    """Body references are resolved in declaration order: one that resolves into the wrong season is a cross-season refusal, one that resolves to nothing is that family's own 404.

    References carried in a request body are resolved the same way, in the order the fields are declared on the endpoint: `season_id`, then `serving_lift_id`, then `terrain_area_id`, then `pump_house_id`, then `lift_id`, then `day_plan_id`, then `assigned_terrain_area_id`, then `patroller_id`.

    Each unresolvable reference raises its own family's not-found code.

    A reference that *does* resolve but belongs to a different season than a sibling reference in the same request — a terrain area whose serving lift lives in another season, for instance — is rejected with `ERR_CROSS_SEASON_REFERENCE` (HTTP 422).

    Design: Corner/errors/a_body_foreign_key_from_another_season_is_a_cross_season_error_while_a_bogus_one_is_a_not_found
    """
    season_a = mountain.create_season()
    lift_a = mountain.create_lift(season_a["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift_a["id"], "PASS")
    area_a = mountain.create_terrain_area(season_a["id"], lift_a["id"])
    pump_house_a = mountain.create_pump_house(season_a["id"])

    season_b = mountain.create_season(season_label="2027-28")
    lift_b = mountain.create_lift(
        season_b["id"],
        lift_code="L2",
        name="Season B Summit",
        wind_hold_threshold_mph=40.0,
    )
    pump_house_b = mountain.create_pump_house(
        season_b["id"], pump_house_code="PH2", name="Season B Pumphouse"
    )
    observed_area_version = mountain.area_version(area_a["id"])

    def probe(season_id, serving_lift_id):
        return f.terrain_area_payload(
            season_id,
            serving_lift_id,
            trail_code="T7",
            name="Cross Season Probe",
            acres=6.0,
        )

    validate_error(
        api.create_terrain_area(probe(season_b["id"], lift_a["id"]), DIRECTOR_HEADERS),
        ERR_CROSS_SEASON_REFERENCE,
        422,
    )
    validate_error(
        api.create_terrain_area(
            probe(season_a["id"], NON_EXISTENT_UUID), DIRECTOR_HEADERS
        ),
        ERR_LIFT_NOT_FOUND,
        404,
    )
    validate_error(
        api.create_terrain_area(
            probe(NON_EXISTENT_UUID, lift_a["id"]), DIRECTOR_HEADERS
        ),
        ERR_SEASON_NOT_FOUND,
        404,
    )
    # Both references are unresolvable, and season_id is declared first, so the
    # lift's own code never surfaces.
    validate_error(
        api.create_terrain_area(
            probe(NON_EXISTENT_UUID, OTHER_MISSING_UUID), DIRECTOR_HEADERS
        ),
        ERR_SEASON_NOT_FOUND,
        404,
    )
    # The pairing is checked even when neither reference is a season_id.
    validate_error(
        api.create_session(
            f.session_payload(
                area_a["id"], pump_house_b["id"], observed_area_version
            ),
            SNOWMAKING_HEADERS,
        ),
        ERR_CROSS_SEASON_REFERENCE,
        422,
    )

    unspent = validate_success(api.get_season(season_a["id"], SNOWMAKING_HEADERS))
    assert_water_af(unspent["water_reserved_af"], 0.000)

    accepted = validate_success(
        api.create_terrain_area(probe(season_b["id"], lift_b["id"]), DIRECTOR_HEADERS),
        201,
    )
    assert accepted["trail_code"] == "T7"
    assert accepted["season_id"] == season_b["id"]
    assert accepted["serving_lift_id"] == lift_b["id"]

    session = validate_success(
        api.create_session(
            f.session_payload(
                area_a["id"], pump_house_a["id"], observed_area_version
            ),
            SNOWMAKING_HEADERS,
        ),
        201,
    )
    assert_water_af(session["water_af_reserved"], 1.547)


def test_an_acting_patroller_who_resolves_to_no_row_is_unauthorized_while_one_who_is_merely_off_duty_is_refused_on_eligibility(
    api, mountain
):
    """An unresolvable acting identity is a 403 on the mitigation endpoints, and a patroller who does resolve but is off duty is refused on the duty rule instead.

    A `Patroller`-owned action whose `X-User-ID` does not resolve to an existing patroller row is rejected with `ERR_UNAUTHORIZED` (HTTP 403).

    It requires the mission to be `PLANNED`, the season not to be `CLOSED` — mitigation, like grooming, runs in `PRESEASON` so that avalanche terrain can reach readiness before the mountain opens — and the acting patroller to be on duty, otherwise `ERR_PATROLLER_NOT_ON_DUTY`.

    The clearing `Patroller` must not be the patroller who executed it — a matching `X-User-ID` is refused with `ERR_SOD_VIOLATION` — must be on duty, and must carry a `cert_level` of `EMT` or `PARAMEDIC`, with `BASIC` and `OEC` refused as `ERR_PATROLLER_CERT_INSUFFICIENT`.

    Design: Corner/errors/an_unresolvable_acting_patroller_is_unauthorized_and_an_ineligible_one_is_not
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(
        season["id"], lift["id"], avalanche_terrain=True
    )
    on_duty_patroller = mountain.create_patroller(
        season["id"],
        patroller_code="P1",
        full_name="Ada Patrol",
        cert_level="EMT",
        blaster_certified=True,
        on_duty=True,
        assigned_terrain_area_id=area["id"],
    )
    off_duty_patroller = mountain.create_patroller(
        season["id"],
        patroller_code="P2",
        full_name="Bo Patrol",
        cert_level="PARAMEDIC",
        blaster_certified=True,
        on_duty=False,
        assigned_terrain_area_id=area["id"],
    )
    mission = mountain.plan_mission(area["id"], planned_charges=2)
    assert mission["state"] == "PLANNED"

    charges = f.mission_execute_payload(2)
    # A permitted role header whose user id resolves to nothing at all.
    validate_error(
        api.execute_mission(
            mission["id"], charges, make_patroller_headers(NON_EXISTENT_UUID)
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # A user id that resolves, but to a season rather than to a patroller.
    validate_error(
        api.execute_mission(
            mission["id"], charges, make_patroller_headers(season["id"])
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    # A real patroller who is simply not on duty fails the eligibility rule.
    validate_error(
        api.execute_mission(
            mission["id"], charges, make_patroller_headers(off_duty_patroller["id"])
        ),
        ERR_PATROLLER_NOT_ON_DUTY,
        422,
    )

    executed = validate_success(
        api.execute_mission(
            mission["id"], charges, make_patroller_headers(on_duty_patroller["id"])
        )
    )
    assert executed["state"] == "EXECUTED"
    assert_integer(executed["charges_used"], 2)
    assert_integer(executed["road_closure_minutes"], 40)

    stored = validate_success(api.get_mission(mission["id"], DIRECTOR_HEADERS))
    assert stored["executed_by_patroller_id"] == on_duty_patroller["id"]
    assert_instant_equals(stored["executed_at"], INITIAL_CLOCK)

    sign_off = f.mission_clear_payload("LOW")
    validate_error(
        api.clear_mission(
            mission["id"], sign_off, make_patroller_headers(NON_EXISTENT_UUID)
        ),
        ERR_UNAUTHORIZED,
        403,
    )
    validate_error(
        api.clear_mission(
            mission["id"], sign_off, make_patroller_headers(on_duty_patroller["id"])
        ),
        ERR_SOD_VIOLATION,
        409,
    )
    validate_error(
        api.clear_mission(
            mission["id"], sign_off, make_patroller_headers(off_duty_patroller["id"])
        ),
        ERR_PATROLLER_NOT_ON_DUTY,
        422,
    )

    unchanged = validate_success(api.get_mission(mission["id"], DIRECTOR_HEADERS))
    assert unchanged["state"] == "EXECUTED"


def test_a_schema_violation_is_reported_ahead_of_the_business_rule_the_same_request_also_breaks(
    api, mountain
):
    """A request that is both schema-invalid and business-invalid reports the schema failure, and the business rule surfaces only once the schema defect is removed.

    Because a single request can violate several rules at once, the order in which checks run is part of the contract: the **first** failing check decides the response, and later checks are never reported.

    Request-body schema conformance — required fields present, types correct, enum values inside their declared domains, numbers inside their declared ranges, arrays inside their declared cardinality — `ERR_INVALID_REQUEST` (400), on every endpoint.

    While `season_state` is `CLOSED`, every write against that season's objects is refused with `ERR_SEASON_NOT_OPERATING`; the terrain opening decision, snowmaking session status changes and guest admission additionally require `OPERATING` rather than merely not-closed, whereas publishing a day plan is permitted from either `PRESEASON` or `OPERATING`, precisely because the first publish is what performs the promotion.

    Design: Corner/errors/a_schema_violation_is_reported_ahead_of_every_business_rule_it_coincides_with
    """
    season = mountain.create_season()
    lift = mountain.create_lift(season["id"], wind_hold_threshold_mph=40.0)
    mountain.inspect_lift(lift["id"], "PASS")
    area = mountain.create_terrain_area(season["id"], lift["id"])
    assert season["season_state"] == "PRESEASON"
    assert area["opening_state"] == "CLOSED"

    # The same price schedule throughout: a hole between hour 9 and hour 10.
    gapped_windows = f.energy_windows_full_day()
    gapped_windows[2]["start_hour_utc"] = 10

    validate_error(
        api.create_season(
            f.season_payload(
                season_label="2027-28",
                base_depth_policy="MEDIAN_OF_STAKES",
                energy_windows=gapped_windows,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.create_season(
            f.season_payload(
                season_label="2027-28",
                base_depth_policy="MIN_OF_STAKES",
                energy_windows=gapped_windows,
            ),
            DIRECTOR_HEADERS,
        ),
        ERR_ENERGY_WINDOW_COVERAGE_GAP,
        422,
    )
    # Neither rejection persisted a row, so the label is still free.
    accepted_season = validate_success(
        api.create_season(
            f.season_payload(
                season_label="2027-28",
                base_depth_policy="MIN_OF_STAKES",
                energy_windows=f.energy_windows_full_day(),
            ),
            DIRECTOR_HEADERS,
        ),
        201,
    )
    assert accepted_season["season_state"] == "PRESEASON"

    validate_error(
        api.decide_opening(
            area["id"],
            f.opening_decision_payload("MAYBE", note="probe"),
            DIRECTOR_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.decide_opening(
            area["id"],
            f.opening_decision_payload("OPEN", note="probe"),
            DIRECTOR_HEADERS,
        ),
        ERR_SEASON_NOT_OPERATING,
        409,
    )

    validate_error(
        api.record_snow_depth_reading(
            area["id"],
            f.snow_depth_reading_payload(
                depth_in=-5.0, measured_at="2026-08-01T00:00:01Z"
            ),
            GROOMING_HEADERS,
        ),
        ERR_INVALID_REQUEST,
        400,
    )
    validate_error(
        api.record_snow_depth_reading(
            area["id"],
            f.snow_depth_reading_payload(
                depth_in=40.0, measured_at="2026-08-01T00:00:01Z"
            ),
            GROOMING_HEADERS,
        ),
        ERR_READING_TIMESTAMP_FUTURE,
        422,
    )
    reading = validate_success(
        api.record_snow_depth_reading(
            area["id"],
            f.snow_depth_reading_payload(depth_in=40.0, measured_at=INITIAL_CLOCK),
            GROOMING_HEADERS,
        ),
        201,
    )

    rows, meta = validate_paginated(
        api.list_snow_depth_readings(area["id"], GROOMING_HEADERS)
    )
    assert_integer(meta["total_count"], 1)
    assert len(rows) == 1
    assert rows[0]["id"] == reading["id"]
