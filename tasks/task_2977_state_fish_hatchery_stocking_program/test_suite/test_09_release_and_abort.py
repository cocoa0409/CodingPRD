"""
Closing the trip: releasing the fish, and unwinding a trip that never happened.

Covers the four conditions on a release — the destination still being open, the
thermal delta, the ceilinged acclimation requirement and the receiving water's
48-hour rest — and then the two halves of the compensating pair: an abort that
reverses a four-way reservation exactly, and a release that moves the same money
sideways rather than back.
"""

from test_helpers import (
    ADMIN_HEADERS,
    assert_appropriation_ledger,
    assert_fish_conservation,
    assert_instant_equals,
    assert_integer_equals,
    assert_is_none,
    assert_number_equals,
    validate_error,
    validate_success,
)
from test_helpers import api_errors as err
from test_helpers import constants as k
from test_helpers import factories as f
from test_helpers import fixtures as fx

# The logical clock the base trip is scheduled, loaded and released under.
TRIP_CLOCK = f.instant(2026, 9, 1, 8)

# Blue Mesa's rest buffer runs from the first release to exactly 48 hours later.
BUFFER_EXPIRES_AT = f.instant(2026, 9, 3, 8)
ONE_SECOND_EARLY = "2026-09-03T07:59:59Z"


def _second_trip_to_the_same_water(api):
    """
    A first trip released into Blue Mesa, then a second trip loaded and waiting.

    The second trip is deliberately booked on the same truck for 2026-09-03,
    06:00 to 12:00, which does not touch the first trip's 08:00-to-14:00 interval
    on 2026-09-01, so nothing about the truck's calendar is in play. Its 2500 fish
    weigh 250.00 lb, cost 82500 cents and draw 3.750 lpm.
    """
    ctx = fx.released_trip(api)
    ctx["request_two"] = fx.create_stocking_request(
        api,
        ctx["water"],
        requested_count=2500,
        justification="Second Blue Mesa plant two days after the opener",
    )
    ctx["plan_two"] = fx.create_allocation_plan(
        api, ctx["hatchery"], available_count=2500
    )
    fx.attach_request(api, ctx["request_two"], ctx["plan_two"], ADMIN_HEADERS)
    fx.run_plan(api, ctx["plan_two"])
    ctx["request_two"] = fx.read_request(api, ctx["request_two"]["id"])
    ctx["event_two"] = fx.create_stocking_event(
        api,
        ctx["hatchery"],
        ctx["request_two"],
        ctx["lot"]["id"],
        ctx["unit"],
        fish_count=2500,
        scheduled_depart_at=f.instant(2026, 9, 3, 6),
        scheduled_return_at=f.instant(2026, 9, 3, 12),
    )
    fx.set_clock(api, f.instant(2026, 9, 3, 6))
    ctx["event_two"] = fx.load_event(
        api,
        ctx["hatchery"],
        ctx["event_two"]["id"],
        f.instant(2026, 9, 3, 6),
        12.0,
        250.0,
    )
    return ctx


def test_the_acclimation_requirement_ceils_to_whole_six_minute_steps(api):
    """
    A 7.50-degree gap costs eight whole steps and therefore 48 minutes, exactly what
    an 8.00-degree gap would cost — a prorating implementation would ask for 45. One
    minute short is refused and the trip stays aboard the truck; exactly the required
    figure is accepted.

    PRD 3.8: "Third, the tempering must have been long enough: the trip's
    `tempering_minutes_required` is the temperature delta divided by a 1.0-degree step,
    that quotient rounded **up** to a whole step, multiplied by 6 minutes per step, and
    the supplied `tempering_minutes` must be at least that figure or the answer is
    `ERR_ACCLIMATION_INSUFFICIENT` (HTTP 422)."

    PRD 3.8: "Because the step count is rounded up, a partial degree costs a whole
    step: a delta of 7.5 degrees requires the same 48 minutes as a delta of 8.0
    degrees, while a delta of 8.01 degrees requires 54."

    Design: Corner/calculations/acclimation_requirement_ceils_to_whole_six_minute_steps
    """
    ctx = fx.in_transit_trip(api)
    event_id = ctx["event"]["id"]

    one_minute_short = api.release_stocking_event(
        event_id,
        f.release_payload(f.instant(2026, 9, 1, 12), 4.5, 47, 20),
        ctx["manager"],
    )

    validate_error(one_minute_short, err.ERR_ACCLIMATION_INSUFFICIENT, 422)
    assert fx.read_event(api, event_id)["status"] == k.EVENT_IN_TRANSIT

    released = validate_success(
        api.release_stocking_event(
            event_id,
            f.release_payload(f.instant(2026, 9, 1, 12), 4.5, 48, 20),
            ctx["manager"],
        ),
        200,
    )

    assert released["status"] == k.EVENT_RELEASED, released["status"]
    assert_integer_equals(
        released["tempering_minutes_required"], 48, "tempering_minutes_required"
    )
    assert_integer_equals(released["tempering_minutes"], 48, "tempering_minutes")
    assert_integer_equals(released["released_count"], 2380, "released_count")
    # Computed at load from 12.0 degrees, below the warm-water threshold.
    assert_integer_equals(released["max_fish_allowed"], 2500, "max_fish_allowed")


def test_a_thirteen_degree_gap_is_refused_on_the_delta_not_on_the_tempering(api):
    """
    A 25.0-degree destination against 12.0-degree truck water is a 13.00-degree gap,
    past the ceiling, so the delta rule answers first and no quantity of tempering can
    rescue the release.

    PRD 3.8: "Second, the thermal shock must be within tolerance: the temperature delta
    is the absolute difference between `site_water_temp_c` and the trip's recorded
    `load_water_temp_c`, rounded to two decimal places, and it must not exceed 10.0
    degrees Celsius or the answer is `ERR_TEMP_DELTA_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/release_with_a_thirteen_degree_gap_reports_temp_delta_exceeded
    """
    ctx = fx.in_transit_trip(api)

    response = api.release_stocking_event(
        ctx["event"]["id"],
        f.release_payload(f.instant(2026, 9, 1, 12), 25.0, 78),
        ctx["manager"],
    )

    validate_error(response, err.ERR_TEMP_DELTA_EXCEEDED, 422)

    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    assert_is_none(event["released_count"], "released_count")
    assert_is_none(event["released_at"], "released_at")

    water = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(water["released_count_ytd"], 0, "released_count_ytd")
    assert_is_none(water["last_release_at"], "last_release_at")


def test_release_into_a_water_closed_while_the_truck_was_out_is_refused(api):
    """
    The gating row is two hops from the trip being written, reached through the request
    to the destination water: every temperature and tempering figure is legal, but the
    water was retired while the unit was in transit.

    PRD 3.8: "First, the receiving water must still be `ACTIVE`; a water closed since
    the trip was scheduled answers `ERR_WATER_CLOSED` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/release_requires_the_destination_water_active
    """
    ctx = fx.in_transit_trip(api)
    closed = fx.close_water(api, ctx["water"])
    assert closed["status"] == k.WATER_CLOSED, closed["status"]

    response = api.release_stocking_event(
        ctx["event"]["id"],
        f.release_payload(f.instant(2026, 9, 1, 11), 4.5, 48, 20),
        ctx["manager"],
    )

    validate_error(response, err.ERR_WATER_CLOSED, 409)

    # 7.50 degrees and 48 minutes are both legal, so neither temperature rule fired.
    event = fx.read_event(api, ctx["event"]["id"])
    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    assert_is_none(event["released_count"], "released_count")
    assert_is_none(event["released_at"], "released_at")


def test_the_release_refused_by_a_closed_water_settles_nothing(api):
    """
    Nothing downstream of the refused release moves: the truck is still holding the
    trip, the water's year-to-date figures are untouched, the grant is still merely
    allocated, and the transport cost is still only committed.

    PRD 3.8: "First, the receiving water must still be `ACTIVE`; a water closed since
    the trip was scheduled answers `ERR_WATER_CLOSED` (HTTP 409)."

    PRD 3.8: "The fish remain counted in the lot's `reserved_count` and are still
    counted in `count_on_hand`: they have left the raceway physically but not yet on the
    books."

    Design: Difficulty/cross_entity_state_dependency/release_requires_the_destination_water_active
    """
    ctx = fx.in_transit_trip(api)
    fx.close_water(api, ctx["water"])

    validate_error(
        api.release_stocking_event(
            ctx["event"]["id"],
            f.release_payload(f.instant(2026, 9, 1, 11), 4.5, 48, 20),
            ctx["manager"],
        ),
        err.ERR_WATER_CLOSED,
        409,
    )

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]
    assert unit["current_event_id"] == ctx["event"]["id"], unit["current_event_id"]

    water = fx.read_water(api, ctx["water"]["id"])
    assert water["status"] == k.WATER_CLOSED, water["status"]
    assert_integer_equals(water["released_count_ytd"], 0, "released_count_ytd")
    assert_is_none(water["last_release_at"], "last_release_at")

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_ALLOCATED, request["status"]

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 2400, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_committed_cents"], 81000, "budget_committed_cents"
    )
    assert_appropriation_ledger(station)


def test_a_second_release_one_second_inside_the_rest_buffer_is_refused(api):
    """
    The resource here is the receiving water and the clock, not the truck's calendar:
    Blue Mesa was last stocked at 2026-09-01T08:00:00Z, so a release with the clock at
    2026-09-03T07:59:59Z is one second short of its rest.

    PRD 3.8: "Fourth, the receiving water must have had its rest: when the water carries
    a `last_release_at` from an earlier trip, the clock must stand at or after that
    instant plus 48 hours, or the answer is `ERR_WATER_REST_BUFFER` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/water_rest_buffer_refuses_a_release_one_second_early
    """
    ctx = _second_trip_to_the_same_water(api)
    fx.set_clock(api, ONE_SECOND_EARLY)

    response = api.release_stocking_event(
        ctx["event_two"]["id"],
        f.release_payload(f.instant(2026, 9, 3, 7, 30), 4.5, 48, 0),
        ctx["manager"],
    )

    validate_error(response, err.ERR_WATER_REST_BUFFER, 409)

    water = fx.read_water(api, ctx["water"]["id"])
    assert_instant_equals(water["last_release_at"], TRIP_CLOCK, "last_release_at")
    assert_integer_equals(water["released_count_ytd"], 2380, "released_count_ytd")

    event = fx.read_event(api, ctx["event_two"]["id"])
    assert event["status"] == k.EVENT_IN_TRANSIT, event["status"]
    assert_is_none(event["released_count"], "released_count")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_IN_USE, unit["status"]


def test_the_rest_buffer_far_edge_is_inclusive_at_exactly_forty_eight_hours(api):
    """
    The identical call that is refused one second early succeeds the moment the clock
    reaches exactly 48 hours after the previous release, and the water's rest then
    restarts from the new release.

    PRD 3.8: "Exactly 48 hours after the previous release is permitted; 47 hours and 59
    minutes is not."

    Design: Difficulty/resource_temporal_overlap/water_rest_buffer_refuses_a_release_one_second_early
    """
    ctx = _second_trip_to_the_same_water(api)
    fx.set_clock(api, ONE_SECOND_EARLY)
    payload = f.release_payload(f.instant(2026, 9, 3, 7, 30), 4.5, 48, 0)

    validate_error(
        api.release_stocking_event(ctx["event_two"]["id"], payload, ctx["manager"]),
        err.ERR_WATER_REST_BUFFER,
        409,
    )

    fx.set_clock(api, BUFFER_EXPIRES_AT)

    released = validate_success(
        api.release_stocking_event(ctx["event_two"]["id"], payload, ctx["manager"]),
        200,
    )

    assert released["status"] == k.EVENT_RELEASED, released["status"]
    assert_integer_equals(released["released_count"], 2500, "released_count")
    assert_instant_equals(released["released_at"], BUFFER_EXPIRES_AT, "released_at")

    water = fx.read_water(api, ctx["water"]["id"])
    assert_instant_equals(
        water["last_release_at"], BUFFER_EXPIRES_AT, "last_release_at"
    )
    assert_integer_equals(water["released_count_ytd"], 4880, "released_count_ytd")


def test_aborting_a_scheduled_trip_unreserves_the_fish_and_the_money(api):
    """
    An abort reverses the reservation exactly: the fish are unreserved without ever
    leaving `count_on_hand`, and the committed cents go back to available rather than
    into spent.

    PRD 3.8: "It returns the fish by subtracting the `fish_count` from the lot's
    `reserved_count` while leaving `count_on_hand` untouched — the fish were never
    shipped, so they are simply unreserved — and advances the lot's `version`."

    Design: Difficulty/compensating_invariant/event_abort_restores_fish_budget_and_grant_identities
    """
    ctx = fx.scheduled_trip(api)

    aborted = validate_success(
        api.abort_stocking_event(ctx["event"]["id"], ctx["manager"]), 200
    )

    assert aborted["status"] == k.EVENT_ABORTED, aborted["status"]
    assert aborted["abort_reason"] == k.ABORT_REASON_OPERATOR, aborted["abort_reason"]
    assert_integer_equals(aborted["released_count"], 0, "released_count")
    assert_instant_equals(aborted["aborted_at"], TRIP_CLOCK, "aborted_at")

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")
    # 20000 eggs taken, 4000 lost to mortality, none released.
    assert_integer_equals(lot["initial_count"], 20000, "initial_count")
    assert_integer_equals(
        lot["cumulative_mortality_count"], 4000, "cumulative_mortality_count"
    )
    assert_fish_conservation(lot, released_total=0)

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 0, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 50000000, "budget_available_cents"
    )
    assert_appropriation_ledger(station)

    # The trip was aborted before it was ever loaded, so it never held the truck.
    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")


def test_the_abort_returns_the_grant_and_cannot_be_applied_twice(api):
    """
    The fourth arm of the reversal is the demand side: the grant goes back, the water's
    year-to-date allocation is reduced by exactly the surrendered grant, and because
    `ABORTED` is terminal a second abort cannot restore any of it again.

    PRD 3.8: "It returns the grant by moving the request to `DEFERRED` with its
    `allocated_count` reset to 0 and its `deferral_reason` set to `EVENT_ABORTED`, and by
    subtracting that surrendered grant from the receiving water's `allocated_count_ytd`,
    with the water's `plan_shortfall_count` and `plan_fill_pct` recomputed."

    Design: Difficulty/compensating_invariant/event_abort_restores_fish_budget_and_grant_identities
    """
    ctx = fx.scheduled_trip(api)
    validate_success(
        api.abort_stocking_event(ctx["event"]["id"], ctx["manager"]), 200
    )

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_DEFERRED, request["status"]
    assert_integer_equals(request["allocated_count"], 0, "allocated_count")
    assert request["deferral_reason"] == k.DEFERRAL_EVENT_ABORTED, request[
        "deferral_reason"
    ]
    assert_is_none(request["allocated_at"], "allocated_at")

    water = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(water["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_integer_equals(water["released_count_ytd"], 0, "released_count_ytd")
    assert_integer_equals(water["plan_shortfall_count"], 2000, "plan_shortfall_count")
    assert_number_equals(water["plan_fill_pct"], 0.0, 2, "plan_fill_pct")

    validate_error(
        api.abort_stocking_event(ctx["event"]["id"], ctx["manager"]),
        err.ERR_INVALID_STATE,
        409,
    )

    # No double restoration.
    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 16000, "count_on_hand")
    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_available_cents"], 50000000, "budget_available_cents"
    )


def test_release_moves_the_committed_cents_sideways_into_spent(api):
    """
    The non-reversing half of the same pair: the identical 81000 cents that an abort
    would have refunded move instead from committed into spent, and the 2400 fish leave
    `count_on_hand` rather than returning to it. Both three-term identities still balance
    against the same totals as the abort case.

    PRD 2.5: "Scheduling a trip commits its cost; aborting the trip releases exactly the
    same cents back to available; releasing the fish moves exactly the same cents from
    committed to spent."

    PRD 3.8: "On the lot, the `fish_count` is subtracted from both `reserved_count` and
    `count_on_hand`, the `transport_mortality_count` is added to
    `cumulative_mortality_count`, `biomass_lbs` is recomputed, and a lot emptied by the
    trip may reach the `RELEASED` stage."

    Design: Difficulty/compensating_invariant/release_moves_budget_from_committed_to_spent_without_drift
    """
    ctx = fx.released_trip(api)

    released = ctx["event"]
    assert released["status"] == k.EVENT_RELEASED, released["status"]
    assert_integer_equals(released["released_count"], 2380, "released_count")
    assert_instant_equals(released["released_at"], TRIP_CLOCK, "released_at")

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(
        station["budget_committed_cents"], 0, "budget_committed_cents"
    )
    assert_integer_equals(station["budget_spent_cents"], 81000, "budget_spent_cents")
    assert_integer_equals(
        station["budget_available_cents"], 49919000, "budget_available_cents"
    )
    assert_appropriation_ledger(station)

    lot = fx.read_lot(api, ctx["hatchery"], ctx["lot"]["id"])
    assert_integer_equals(lot["reserved_count"], 0, "reserved_count")
    assert_integer_equals(lot["count_on_hand"], 13600, "count_on_hand")
    assert_integer_equals(
        lot["cumulative_mortality_count"], 4020, "cumulative_mortality_count"
    )
    assert_integer_equals(lot["initial_count"], 20000, "initial_count")
    assert_fish_conservation(lot, released_total=2380)


def test_the_released_trip_settles_the_water_the_grant_and_the_truck_and_is_terminal(api):
    """
    The other three of the six settlement places: the water takes the released fish and
    gives back the grant it had merely been promised, the request is filled, the truck is
    free — and because `RELEASED` is terminal the spent cents can never be un-spent.

    PRD 3.8: "On the receiving water, the `released_count` is added to
    `released_count_ytd`, the filled request's `allocated_count` is subtracted from
    `allocated_count_ytd` because that grant is no longer merely promised,
    `last_release_at` is set to the clock, and `plan_shortfall_count` and `plan_fill_pct`
    are recomputed against the water's `stocking_plan_count`."

    PRD 3.8: "And on the demand side the filled request moves to `FULFILLED` with
    `fulfilled_at` stamped from the clock, which in turn may close the last open request
    on an allocation plan and take that plan to `CLOSED`."

    PRD 3.8: "Both `RELEASED` and `ABORTED` are terminal: neither can be loaded, released
    or aborted again."

    Design: Difficulty/compensating_invariant/release_moves_budget_from_committed_to_spent_without_drift
    """
    ctx = fx.released_trip(api)

    water = fx.read_water(api, ctx["water"]["id"])
    assert_integer_equals(water["released_count_ytd"], 2380, "released_count_ytd")
    assert_integer_equals(water["allocated_count_ytd"], 0, "allocated_count_ytd")
    assert_instant_equals(water["last_release_at"], TRIP_CLOCK, "last_release_at")

    request = fx.read_request(api, ctx["request"]["id"])
    assert request["status"] == k.REQUEST_FULFILLED, request["status"]
    assert_instant_equals(request["fulfilled_at"], TRIP_CLOCK, "fulfilled_at")
    assert_integer_equals(request["allocated_count"], 2400, "allocated_count")

    unit = fx.read_unit(api, ctx["unit"]["id"])
    assert unit["status"] == k.UNIT_AVAILABLE, unit["status"]
    assert_is_none(unit["current_event_id"], "current_event_id")

    validate_error(
        api.abort_stocking_event(ctx["event"]["id"], ctx["manager"]),
        err.ERR_INVALID_STATE,
        409,
    )

    station = fx.read_hatchery(api, ctx["hatchery"])
    assert_integer_equals(station["budget_spent_cents"], 81000, "budget_spent_cents")
    assert_appropriation_ledger(station)
