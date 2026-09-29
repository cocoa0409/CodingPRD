"""Derived figures: rate-book branches, rounding mode, input sets and variants.

The hourly branch, the half-cent rounding pair, the membership filter that keeps
open segments out of a cycle while the exposure read accrues them, the reclaim
split constant and waterfall cap, the per-car sequence scope, the projection
horizon, fleet utilization and the default statement variant.
"""

from test_helpers import (
    AUGUST_BOOTSTRAP,
    AUGUST_END,
    BACK_76H,
    DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS,
    DELIVERY_OUT_AT,
    OUT_76H,
    RETURN_AT_11464,
    ApiClient,
    allow_reclaim,
    assert_hours,
    assert_instant_equals,
    assert_money,
    assert_pct,
    capture_delivery,
    closed_movement_of,
    closed_segment_world,
    computed_cycle,
    exposure,
    file_reclaim,
    hourly_world,
    open_movement_of,
    read_movement,
    register_car,
    segment_76h_world,
    set_clock,
    standard_world,
    validate_success,
)
import test_helpers.factories as f

TWENTY_FOUR_HOUR_OUT = "2026-08-24T00:00:00Z"
TWENTY_FOUR_HOUR_BACK = "2026-08-25T00:00:00Z"
OPEN_SEGMENT_START = "2026-08-27T00:00:00Z"
PROJECTION_START = "2026-08-30T00:00:00Z"
PROJECTION_CLOCK = "2026-09-02T00:00:00Z"


class TestHourlyRateBookBranch:
    """An HOURLY car type prices hours directly and never ceilings to days."""

    def test_fifty_chargeable_hours_price_at_seven_thousand_five_hundred(self, api: ApiClient):
        """54.00 elapsed hours give 50.00 chargeable, 0 days and 7500 cents of time.

        PRD: "In `HOURLY` mode, `chargeable_days` plays no part in the price and the segment reports it as 0, while `time_component_cents` is `chargeable_hours` multiplied by `hourly_rate_cents` and rounded half up to a whole cent."

        Design: Corner/calculations/hourly_car_type_time_component_uses_the_hourly_rate
        """
        world, car_id, movement = hourly_world(api)

        assert_hours(movement["chargeable_hours"], 50.00, "chargeable_hours")
        assert movement["chargeable_days"] == 0
        assert_money(movement["time_component_cents"], 7500, "time_component_cents")

    def test_an_empty_segment_still_bills_mileage_when_the_type_allows_it(self, api: ApiClient):
        """With loaded_mileage_only false the 90 EMPTY miles bill 212 cents.

        PRD: "Billable miles are zero when the car type has `loaded_mileage_only` true and the segment's `load_status` is `EMPTY`; otherwise billable miles are the full segment miles."

        Design: Corner/calculations/hourly_car_type_time_component_uses_the_hourly_rate
        """
        world, car_id, movement = hourly_world(api)

        assert movement["load_status"] == "EMPTY"
        assert movement["end_odometer_miles"] - movement["start_odometer_miles"] == 90
        assert_money(movement["mileage_component_cents"], 212, "mileage_component_cents")
        assert_money(movement["gross_hire_cents"], 7712, "gross_hire_cents")
        assert_money(movement["net_hire_cents"], 7712, "net_hire_cents")


class TestMileageRoundingMode:
    """Two lines land exactly on the half cent and both must round upward."""

    def test_ninety_and_thirty_miles_round_to_two_hundred_twelve_and_seventy_one(self, api: ApiClient):
        """211.5 becomes 212 and 70.5 becomes 71, never 211 and never 70.

        PRD: "`mileage_component_cents` is billable miles multiplied by `mileage_rate_millicents_per_mile`, divided by 1000 to convert millicents to cents, and rounded half up — **once per segment**."

        Design: Corner/calculations/mileage_rounding_is_half_up_not_half_even
        """
        world = standard_world(api)
        second = register_car(api, "CX 100002", world.xm, world.cx, world=world)

        set_clock(api, TWENTY_FOUR_HOUR_OUT, world)
        capture_delivery(api, world.car, world.jct, world.cx, world.bn,
                         TWENTY_FOUR_HOUR_OUT, 1000, "LOADED", world=world)
        capture_delivery(api, second, world.jct, world.cx, world.bn,
                         TWENTY_FOUR_HOUR_OUT, 2000, "LOADED", world=world)
        set_clock(api, TWENTY_FOUR_HOUR_BACK, world)
        capture_delivery(api, world.car, world.jct, world.bn, world.cx,
                         TWENTY_FOUR_HOUR_BACK, 1090, "LOADED", world=world)
        capture_delivery(api, second, world.jct, world.bn, world.cx,
                         TWENTY_FOUR_HOUR_BACK, 2030, "LOADED", world=world)

        first_line = closed_movement_of(api, world.car, world.bn,
                                       world.accountant(world.bn))
        second_line = closed_movement_of(api, second, world.bn,
                                        world.accountant(world.bn))

        assert first_line["end_odometer_miles"] - first_line["start_odometer_miles"] == 90
        assert_money(first_line["mileage_component_cents"], 212, "90-mile line")
        assert first_line["mileage_component_cents"] != 211

        assert second_line["end_odometer_miles"] - second_line["start_odometer_miles"] == 30
        assert_money(second_line["mileage_component_cents"], 71, "30-mile line")
        assert second_line["mileage_component_cents"] != 70

        for label, line in (("90-mile", first_line), ("30-mile", second_line)):
            assert_hours(line["chargeable_hours"], 20.00, f"{label} chargeable_hours")
            assert line["chargeable_days"] == 1
            assert_money(line["time_component_cents"], 2350, f"{label} time component")
        assert_money(first_line["gross_hire_cents"], 2562, "90-mile gross_hire_cents")
        assert_money(second_line["gross_hire_cents"], 2421, "30-mile gross_hire_cents")


def _one_closed_and_one_open_segment(api):
    """BN holds two CX cars: one returned on 08-28, one still out since 08-27."""
    world = standard_world(api)
    second = register_car(api, "CX 100002", world.xm, world.cx, world=world)

    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     1000, "LOADED", world=world)
    set_clock(api, OPEN_SEGMENT_START, world)
    capture_delivery(api, second, world.jct, world.cx, world.bn, OPEN_SEGMENT_START,
                     2000, "LOADED", world=world)
    set_clock(api, RETURN_AT_11464, world)
    capture_delivery(api, world.car, world.jct, world.bn, world.cx, RETURN_AT_11464,
                     1240, "LOADED", world=world)
    return world, second


class TestCycleMembershipVersusExposure:
    """The cycle counts only closed in-period lines; the exposure read accrues the rest."""

    def test_the_still_open_segment_is_not_a_member_line(self, api: ApiClient):
        """One member line of 11464 nets 11407 while the open segment stays unvalued.

        PRD: "A segment is a member when its `status` is `CLOSED`, its `handling_road_id` is the cycle's payer, its `owner_road_id` is the cycle's payee, its `hire_liable` is true, and its `end_at` falls in the half-open period from `period_start_at` up to but excluding `period_end_at`; `VOID` segments and still-`OPEN` segments are excluded however much hire they have accrued."

        Design: Corner/calculations/open_and_out_of_period_movements_excluded_from_the_cycle
        """
        world, second = _one_closed_and_one_open_segment(api)
        cycle, computed = computed_cycle(api, world)

        assert computed["movement_line_count"] == 1
        assert_money(computed["gross_hire_cents"], 11464, "gross_hire_cents")
        assert_money(computed["clearinghouse_fee_cents"], 57, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 11407, "net_settlement_cents")

        still_open = open_movement_of(api, second, world.bn,
                                    world.accountant(world.bn))
        assert still_open["status"] == "OPEN"
        assert still_open["settlement_cycle_id"] is None
        assert still_open["gross_hire_cents"] in (0, None)
        assert still_open["net_hire_cents"] in (0, None)

        member = closed_movement_of(api, world.car, world.bn,
                                   world.accountant(world.bn))
        assert member["settlement_cycle_id"] == cycle["id"]

    def test_the_exposure_read_accrues_that_same_open_segment(self, api: ApiClient):
        """BN carries 25464 of exposure: 11464 closed plus 14000 accrued to the clock.

        PRD: "Under the `SNAPSHOT` variant — the default, and the variant that maintains the stored `per_diem_exposure_cents` — a `CLOSED` segment contributes its `net_hire_cents` as it stands, while an `OPEN` segment is accrued as if it closed at the logical clock, running the time component of §3.4 with `end_at` set to now and adding mileage of 0, since no delivery odometer has been reported yet."

        Design: Corner/calculations/open_and_out_of_period_movements_excluded_from_the_cycle
        """
        world, second = _one_closed_and_one_open_segment(api)
        set_clock(api, AUGUST_END, world)

        snapshot = exposure(api, world, world.bn)
        assert snapshot["variant_applied"] == "SNAPSHOT"
        assert snapshot["open_movement_count"] == 1
        assert_money(snapshot["exposure_cents"], 25464, "exposure_cents")
        assert_money(snapshot["closed_unsettled_cents"], 11464, "closed_unsettled_cents")
        assert_money(snapshot["settled_paid_cents"], 0, "settled_paid_cents")


DETENTION_FROM = "2026-08-27T00:00:00Z"
DETENTION_TO = "2026-08-28T06:00:00Z"
DETENTION_NOTIFIED = "2026-08-27T12:00:00Z"


class TestCustomerDetentionSplit:
    """The 0.5 detention share multiplies inside the single rounding."""

    def test_a_thirty_hour_detention_window_credits_sixteen_twenty_five(self, api: ApiClient):
        """split_pct_applied is 0.5 and the credit is 1625, half of 3250.

        PRD: "The raw credit is the segment's `time_component_cents`, multiplied by the effective hours, divided by the segment's `chargeable_hours`, multiplied by the split percentage, and rounded half up — with the split multiplying **inside** that single rounding, never applied to an already-rounded full credit."

        Design: Corner/calculations/customer_detention_reclaim_applies_the_declared_split_constant
        """
        world, movement = segment_76h_world(api)
        assert_money(movement["time_component_cents"], 7800, "time_component_cents")
        assert_hours(movement["chargeable_hours"], 72.00, "chargeable_hours")

        claim = file_reclaim(api, world, movement, "CUSTOMER_DETENTION", DETENTION_FROM,
                            DETENTION_TO, detention_notified_at=DETENTION_NOTIFIED)
        assert_hours(claim["claimed_hours"], 30.00, "claimed_hours")

        allowed = allow_reclaim(api, world, claim)
        assert allowed["status"] == "ALLOWED"
        assert_pct(allowed["split_pct_applied"], 0.5, "split_pct_applied")
        assert_money(allowed["credit_cents"], 1625, "credit_cents")
        assert allowed["credit_cents"] * 2 == 3250

        priced = read_movement(api, world, movement["id"])
        assert_money(priced["reclaim_credit_cents"], 1625, "reclaim_credit_cents")
        assert_money(priced["net_hire_cents"], 7150, "net_hire_cents")
        assert_money(priced["mileage_component_cents"], 975, "mileage_component_cents")


CLAIM_A_TO = "2026-08-27T18:00:00Z"


class TestReclaimWaterfallCap:
    """Two allowed claims fill in window order and stop at the time component."""

    def test_the_later_claim_is_clipped_on_the_segment_but_not_on_its_own_row(self, api: ApiClient):
        """3900 then 4333 fill to exactly 7800, leaving only the 975 of mileage payable.

        PRD: "The running total starts at zero and the remaining capacity starts at the segment's `time_component_cents`; each claim in turn takes the lesser of its own `credit_cents` and the capacity that remains, adding that to the running total and reducing the remaining capacity by it."

        Design: Corner/calculations/two_allowed_reclaims_fill_in_window_order_and_are_capped
        """
        world = standard_world(api, bootstrap_clock=AUGUST_BOOTSTRAP)
        set_clock(api, OUT_76H, world)
        capture_delivery(api, world.car, world.jct, world.cx, world.bn, OUT_76H,
                         12000, "LOADED", world=world)
        validate_success(api.report_bad_order(
            world.car, f.bad_order_payload(OUT_76H), world.clerk(world.bn)))
        set_clock(api, BACK_76H, world)
        validate_success(api.release_to_service(
            world.car, f.release_payload(BACK_76H), world.clerk(world.bn)))
        capture_delivery(api, world.car, world.jct, world.bn, world.cx, BACK_76H,
                         12415, "LOADED", world=world)
        movement = closed_movement_of(api, world.car, world.bn,
                                    world.accountant(world.bn))
        assert_money(movement["time_component_cents"], 7800, "time_component_cents")

        claim_a = file_reclaim(api, world, movement, "BAD_ORDER", OUT_76H, CLAIM_A_TO)
        assert_hours(claim_a["claimed_hours"], 36.00, "claim A claimed_hours")
        movement = read_movement(api, world, movement["id"])
        claim_b = file_reclaim(api, world, movement, "BAD_ORDER", CLAIM_A_TO, BACK_76H)
        assert_hours(claim_b["claimed_hours"], 40.00, "claim B claimed_hours")

        allowed_a = allow_reclaim(api, world, claim_a)
        assert_money(allowed_a["credit_cents"], 3900, "claim A credit_cents")
        after_a = read_movement(api, world, movement["id"])
        assert_money(after_a["reclaim_credit_cents"], 3900, "reclaim_credit_cents")

        allowed_b = allow_reclaim(api, world, claim_b)
        assert_money(allowed_b["credit_cents"], 4333, "claim B credit_cents")

        after_b = read_movement(api, world, movement["id"])
        assert_money(after_b["reclaim_credit_cents"], 7800, "reclaim_credit_cents")
        assert after_b["reclaim_credit_cents"] != 8233
        assert_money(after_b["net_hire_cents"], 975, "net_hire_cents")
        assert allowed_a["status"] == "ALLOWED"
        assert allowed_b["status"] == "ALLOWED"


CAR2_OUT = "2026-08-25T00:00:00Z"
CAR2_BACK = "2026-08-27T00:00:00Z"


def _interleaved_capture_world(api):
    """Car 1's whole trip is captured first, then car 2's earlier trip."""
    world = standard_world(api)
    second = register_car(api, "CX 100002", world.xm, world.cx, world=world)

    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     1000, "LOADED", world=world)
    set_clock(api, RETURN_AT_11464, world)
    capture_delivery(api, world.car, world.jct, world.bn, world.cx, RETURN_AT_11464,
                     1240, "LOADED", world=world)

    capture_delivery(api, second, world.jct, world.cx, world.bn, CAR2_OUT,
                     2000, "LOADED", world=world)
    capture_delivery(api, second, world.jct, world.bn, world.cx, CAR2_BACK,
                     2100, "LOADED", world=world)
    return world, second


class TestSequenceRuleIsScopedPerCar:
    """Another car's later events never block an earlier capture on this car."""

    def test_both_trips_price_from_their_own_boundaries(self, api: ApiClient):
        """Car 2's 08-25 to 08-27 trip is accepted after car 1's 08-28 return.

        PRD: "`interchange_at` must be strictly later than the `interchange_at` of the car's latest `RECORDED` event, and `odometer_miles` must be greater than or equal to that event's `odometer_miles`, both under `ERR_EVENT_OUT_OF_SEQUENCE` — direct capture is append-only in time, and out-of-order insertion is a correction rather than a capture."

        Design: Corner/calculations/events_recorded_out_of_order_across_cars_still_segment_correctly
        """
        world, second = _interleaved_capture_world(api)

        first_line = closed_movement_of(api, world.car, world.bn,
                                       world.accountant(world.bn))
        assert_instant_equals(first_line["start_at"], DELIVERY_OUT_AT, "start_at")
        assert_instant_equals(first_line["end_at"], RETURN_AT_11464, "end_at")
        assert_money(first_line["gross_hire_cents"], 11464, "car 1 gross_hire_cents")

        second_line = closed_movement_of(api, second, world.bn,
                                        world.accountant(world.bn))
        assert_instant_equals(second_line["start_at"], CAR2_OUT, "start_at")
        assert_instant_equals(second_line["end_at"], CAR2_BACK, "end_at")
        assert_money(second_line["gross_hire_cents"], 4935, "car 2 gross_hire_cents")

        for car_id in (world.car, second):
            car = validate_success(api.get_car(car_id, world.owner(world.cx)))
            assert car["custody_status"] == "ON_HOME_ROAD"
            home_leg = open_movement_of(api, car_id, world.cx,
                                       world.accountant(world.cx))
            assert home_leg["hire_liable"] is False

    def test_the_event_log_reads_chronologically_though_the_writes_did_not(self, api: ApiClient):
        """All four events come back in 08-24, 08-25, 08-27, 08-28 order.

        PRD: "Two orderings are worth calling out here because a calculation depends on them: reclaim claims are listed in `window_from` ascending order with ties broken by `created_at` ascending, which is exactly the order in which reclaim credits fill a segment's cap; and interchange events are listed in `interchange_at` ascending order with ties broken by `created_at` ascending, which is the order from which segment boundaries are re-derived after a correction."

        Design: Corner/calculations/events_recorded_out_of_order_across_cars_still_segment_correctly
        """
        world, second = _interleaved_capture_world(api)

        rows = validate_success(api.list_interchange_events(
            world.clerk(world.cx), params={"limit": 50}))
        rows = rows if isinstance(rows, list) else rows["items"]
        assert len(rows) == 4
        instants = [row["interchange_at"] for row in rows]
        for expected, actual in zip(
            [DELIVERY_OUT_AT, CAR2_OUT, CAR2_BACK, RETURN_AT_11464], instants
        ):
            assert_instant_equals(actual, expected, "interchange_at")
        assert all(row["status"] == "RECORDED" for row in rows)


def _projection_world(api):
    """One OPEN BN segment opened on 08-30 with the clock at 09-02."""
    world = standard_world(api)
    set_clock(api, PROJECTION_START, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, PROJECTION_START,
                     1000, "LOADED", world=world)
    set_clock(api, PROJECTION_CLOCK, world)
    return world


class TestProjectedExposureHorizon:
    """PROJECTED accrues 72 hours further and crosses into the escalated tier."""

    def test_the_two_variants_report_the_worked_example_figures(self, api: ApiClient):
        """SNAPSHOT is 7800 and PROJECTED is 17100 on the very same open segment.

        PRD: "One open segment starting at `2026-08-30T00:00:00Z` on an `XM`-rated car with the clock at `2026-09-02T00:00:00Z` gives a snapshot of 7800 — 72.00 elapsed, 68.00 chargeable, three days — and a projection of 17100, accruing to `2026-09-05T00:00:00Z` for 144.00 elapsed, 140.00 chargeable and six days priced as two days at 2350 plus four at 3100; the projection is more than double the snapshot because the escalated second-tier rate dominates the extra three days."

        Design: Corner/calculations/exposure_projected_variant_accrues_the_projection_horizon
        """
        world = _projection_world(api)

        snapshot = exposure(api, world, world.bn)
        assert snapshot["variant_applied"] == "SNAPSHOT"
        assert_money(snapshot["exposure_cents"], 7800, "snapshot exposure_cents")

        projected = exposure(api, world, world.bn, variant="PROJECTED")
        assert projected["variant_applied"] == "PROJECTED"
        assert_money(projected["exposure_cents"], 17100, "projected exposure_cents")

        assert projected["exposure_cents"] - snapshot["exposure_cents"] == 9300
        assert projected["exposure_cents"] > 2 * snapshot["exposure_cents"]
        assert snapshot["open_movement_count"] == 1
        assert projected["open_movement_count"] == 1

    def test_headroom_is_taken_from_the_snapshot_figure(self, api: ApiClient):
        """The default limit of 100000000 less 7800 leaves 99992200 of headroom.

        PRD: "`credit_headroom_cents` is `per_diem_credit_limit_cents` minus the exposure, and a statement compute that would drive headroom negative is refused with `ERR_PER_DIEM_CREDIT_LIMIT_EXCEEDED`."

        Design: Corner/calculations/exposure_projected_variant_accrues_the_projection_horizon
        """
        world = _projection_world(api)

        snapshot = exposure(api, world, world.bn)
        assert_money(snapshot["credit_limit_cents"],
                     DEFAULT_PER_DIEM_CREDIT_LIMIT_CENTS, "credit_limit_cents")
        assert_money(snapshot["credit_headroom_cents"], 99992200,
                     "credit_headroom_cents")
        assert (snapshot["credit_limit_cents"] - snapshot["exposure_cents"]
                == snapshot["credit_headroom_cents"])
        assert_money(snapshot["closed_unsettled_cents"], 0, "closed_unsettled_cents")
        assert_money(snapshot["settled_paid_cents"], 0, "settled_paid_cents")

        road = validate_success(api.get_railroad(world.bn, world.accountant(world.bn)))
        assert_money(road["per_diem_exposure_cents"], 7800, "per_diem_exposure_cents")


BAD_ORDER_AT = "2026-08-25T00:00:00Z"


def _three_car_fleet(api):
    """CX owns three cars: one serviceable on BN, one bad-ordered on BN, one home."""
    world = standard_world(api, extra_roads=("NS",))
    second = register_car(api, "CX 100002", world.xm, world.cx, world=world)
    register_car(api, "CX 100003", world.xm, world.cx, world=world)

    set_clock(api, DELIVERY_OUT_AT, world)
    capture_delivery(api, world.car, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     1000, "LOADED", world=world)
    capture_delivery(api, second, world.jct, world.cx, world.bn, DELIVERY_OUT_AT,
                     2000, "LOADED", world=world)
    set_clock(api, BAD_ORDER_AT, world)
    validate_success(api.report_bad_order(
        second, f.bad_order_payload(BAD_ORDER_AT), world.clerk(world.bn)))
    return world, second


class TestFleetUtilization:
    """Only cars that are both foreign and serviceable count as utilised."""

    def test_the_four_fleet_counts_are_taken_over_the_owned_cars(self, api: ApiClient):
        """Three owned, two foreign, one bad-ordered, one serviceable and foreign.

        PRD: "`owned_car_count` is the number of owned cars; `on_foreign_count` those whose `custody_status` is `ON_FOREIGN_ROAD`; `bad_order_count` those whose `mechanical_status` is `BAD_ORDER` or `UNDER_REPAIR`; and `serviceable_foreign_count` those that are both `ON_FOREIGN_ROAD` and `SERVICEABLE`."

        Design: Corner/calculations/fleet_utilization_rounds_to_two_decimals_and_empty_fleet_is_zero
        """
        world, second = _three_car_fleet(api)

        fleet = exposure(api, world, world.cx, headers=world.owner(world.cx))
        assert fleet["owned_car_count"] == 3
        assert fleet["on_foreign_count"] == 2
        assert fleet["bad_order_count"] == 1
        assert fleet["serviceable_foreign_count"] == 1

        road = validate_success(api.get_railroad(world.cx, world.accountant(world.cx)))
        assert road["owned_car_count"] == 3

    def test_one_serviceable_car_of_three_is_thirty_three_point_three_three(self, api: ApiClient):
        """CX reports 33.33 while a railroad owning nothing reports 0.00.

        PRD: "`utilization_pct` is 100 times `serviceable_foreign_count` divided by `owned_car_count`, rounded half up to exactly two decimal places — 7 owned cars of which 3 are serviceable on a foreign road gives 42.86 — and is 0.00 when the fleet is empty, never an error and never null."

        Design: Corner/calculations/fleet_utilization_rounds_to_two_decimals_and_empty_fleet_is_zero
        """
        world, second = _three_car_fleet(api)

        fleet = exposure(api, world, world.cx, headers=world.owner(world.cx))
        assert_pct(fleet["utilization_pct"], 33.33, "utilization_pct")
        assert abs(float(fleet["utilization_pct"]) - 66.67) > 0.01

        empty = exposure(api, world, world.ns, headers=world.owner(world.ns))
        assert empty["owned_car_count"] == 0
        assert empty["utilization_pct"] is not None
        assert_pct(empty["utilization_pct"], 0.00, "empty fleet utilization_pct")


class TestComputeDefaultsToAsReported:
    """Compute stamps AS_REPORTED and a statement read never re-stamps the row."""

    def test_compute_records_the_as_reported_variant_and_its_own_net(self, api: ApiClient):
        """The stored cycle carries AS_REPORTED with 11464 gross, 57 fee and 11407 net.

        PRD: "Under `AS_REPORTED` — the default, and the only variant in play while no dispute on the cycle has been accepted — a segment contributes its `net_hire_cents`, the figure as originally reported by the handling road, ignoring every dispute outcome."

        Design: Corner/calculations/cycle_compute_defaults_to_the_as_reported_variant
        """
        world, movement = closed_segment_world(api)
        cycle, computed = computed_cycle(api, world)

        assert computed["variant_applied"] == "AS_REPORTED"
        assert_money(computed["gross_hire_cents"], 11464, "gross_hire_cents")
        assert_money(computed["clearinghouse_fee_cents"], 57, "clearinghouse_fee_cents")
        assert_money(computed["net_settlement_cents"], 11407, "net_settlement_cents")
        assert_money(computed["as_reported_net_cents"], 11407, "as_reported_net_cents")
        assert_money(computed["dispute_adjustment_cents"], 0, "dispute_adjustment_cents")
        assert computed["movement_line_count"] == 1

    def test_a_reconciled_statement_read_leaves_the_stored_variant_alone(self, api: ApiClient):
        """The RECONCILED read returns the same 11407 and the row stays AS_REPORTED.

        PRD: "Separately, a computed read returns the statement without mutating anything, so the two variants can be compared side by side: it accepts a `variant` selecting `AS_REPORTED` by default or `RECONCILED`, and returns `settlement_cycle_id`, `variant_applied`, `payer_road_id`, `payee_road_id`, `period_month`, `movement_line_count`, `gross_hire_cents`, `reclaim_credit_cents`, `penalty_cents`, `repair_charge_cents`, `dispute_adjustment_cents`, `pre_fee_net_cents`, `clearinghouse_fee_cents`, `net_settlement_cents`, and the membership lists `included_movement_ids` and `included_repair_bill_ids`."

        Design: Corner/calculations/cycle_compute_defaults_to_the_as_reported_variant
        """
        world, movement = closed_segment_world(api)
        cycle, computed = computed_cycle(api, world)

        statement = validate_success(api.get_settlement_statement(
            cycle["id"], world.accountant(world.bn), params={"variant": "RECONCILED"}))
        assert statement["variant_applied"] == "RECONCILED"
        assert statement["settlement_cycle_id"] == cycle["id"]
        assert_money(statement["dispute_adjustment_cents"], 0, "dispute_adjustment_cents")
        assert_money(statement["net_settlement_cents"], 11407, "net_settlement_cents")
        assert statement["movement_line_count"] == 1
        assert statement["included_movement_ids"] == [movement["id"]]
        assert statement["included_repair_bill_ids"] == []

        after = validate_success(api.get_settlement_cycle(cycle["id"],
                                                        world.accountant(world.cx)))
        assert after["variant_applied"] == "AS_REPORTED"
        assert after["version"] == computed["version"]
