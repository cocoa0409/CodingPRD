"""Arithmetic corners of the derived formulas: the derated-speed rounding, the
capped blockage credit, the three-bucket remedy waterfall against an exactly
exhausted budget, the read-side selector filter and the economics projection
with an empty numerator.

Every literal asserted here is re-derived from the PRD formula rather than
copied from a fixture, so a change of one input moves exactly one number.
"""
from test_helpers import (
    DISPATCHER,
    OPERATOR,
    SUPPORT,
    abort_mission,
    add_order,
    add_robot,
    add_segment,
    dispatch_mission,
    health_action,
    load_mission,
    mission_action,
    read_economics,
    read_merchant,
    read_mission,
    read_order,
    read_robot,
    read_zone,
    remedy_payload,
    set_battery,
    set_clock,
    setup_available_robot,
    setup_en_route_mission,
    setup_loaded_mission,
    setup_received_order,
    setup_second_robot,
    submit_route_plan,
    validate_and_activate_plan,
    validate_error,
    validate_paginated,
    validate_success,
)

#: A walkway long enough that the detour around S3 lengthens the haul.
S6 = {
    "segment_type": "WALKWAY",
    "length_m": 300.0,
    "measured_clearance_cm": 110.0,
    "surface_grade_pct": 3.5,
    "sightline_m": 32.0,
    "pedestrian_flow_per_min": 8.0,
    "curb_ramp_present": True,
}
#: Ninety minutes after the departure of the canonical scenario.
RESUME_CLOCK_UTC = "2026-08-03T10:30:00.000Z"


def _two_loaded_missions_at_different_speeds() -> dict:
    """One zone holding two loaded missions whose robots differ only in
    `max_speed_cm_s`: 100 for the first and 150 for the second."""
    ctx = setup_loaded_mission(robot_overrides={"max_speed_cm_s": 100})
    fast = setup_second_robot(ctx, asset_tag="RBT-002", max_speed_cm_s=150)
    ctx["r2"] = fast["id"]
    second_order = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    ctx["o2"] = second_order["id"]
    second = dispatch_mission(second_order, ctx["r2"])
    ctx["mission2"] = load_mission(second["id"], ctx["m"], 22.0)
    ctx["mi2"] = second["id"]
    return ctx


def _plan_both_missions_over_the_same_corridor(ctx: dict) -> tuple:
    """Submit the identical [S1, S2, S3, S5] sequence on both missions."""
    corridor = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    slow_plan = submit_route_plan(ctx["mission"], corridor)
    fast_plan = submit_route_plan(ctx["mission2"], corridor)
    return slow_plan, fast_plan


class TestPlannedDurationAtTheDeratedSpeed:
    def test_the_same_corridor_plans_to_thirteen_minutes_and_to_nine(self, api):
        """PRD §3.6: "`planned_duration_min` converts the haul into whole minutes
        at a derated speed: the robot's `max_speed_cm_s` multiplied by 0.6 gives
        an effective travel rate in metres per minute, since a rate expressed in
        centimetres per second multiplied by 0.6 is the same rate expressed in
        metres per minute, and `total_length_m` divided by that rate is rounded
        up to the next whole minute — always up, even when the division is exact
        to a fraction of a minute."

        774.0 metres at 60.0 m/min is 12.9 minutes and at 90.0 m/min is 8.6, so
        the two plans differ only by the rounding-up of their own quotient.

        Design: Corner/calculations/planned_duration_rounds_up_at_the_derated_speed
        """
        ctx = _two_loaded_missions_at_different_speeds()

        slow_plan, fast_plan = _plan_both_missions_over_the_same_corridor(ctx)

        assert slow_plan["total_length_m"] == 774.0
        assert fast_plan["total_length_m"] == 774.0
        assert slow_plan["planned_duration_min"] == 13
        assert fast_plan["planned_duration_min"] == 9

    def test_every_other_derived_value_is_identical_on_both_plans(self, api):
        """PRD §3.6: "`total_length_m` is the sum of `length_m` over the sequence
        in the given order, carried to one decimal place."
        PRD §3.6: "`crossing_count` is the number of elements whose
        `segment_type` is `CROSSING`."
        PRD §3.6: "`clearance_margin_cm` is the accessibility slack of the
        tightest segment for this particular robot: for each segment in the
        sequence, subtract the robot's `width_cm` and then a further ordinance
        buffer of 12 centimetres from that segment's `measured_clearance_cm`, and
        take the smallest of those results, rounded to one decimal place."
        PRD §3.6: "`revision_index` is the one-based ordinal of this plan among
        the plans of the same mission ordered by `created_at` ascending, so a
        mission's first plan carries `revision_index` 1 and its first replacement
        carries 2."
        PRD §3.6: "the plan then lands in `plan_state` `DRAFT`"

        Design: Corner/calculations/planned_duration_rounds_up_at_the_derated_speed
        """
        ctx = _two_loaded_missions_at_different_speeds()

        slow_plan, fast_plan = _plan_both_missions_over_the_same_corridor(ctx)

        for plan in (slow_plan, fast_plan):
            assert plan["crossing_count"] == 1
            assert plan["clearance_margin_cm"] == 2.0
            assert plan["revision_index"] == 1
            assert plan["plan_state"] == "DRAFT"


def _late_delivery_after_a_ninety_minute_blockage() -> dict:
    """Depart on the 774.0 m corridor, block on S3, reroute ninety minutes later
    over the 814.0 m detour through S6 and complete, so the settlement reads
    1588.0 travelled metres, two crossings and ninety blocked minutes."""
    ctx = setup_en_route_mission()
    detour = add_segment(ctx["z"], "S6", [ctx["s2"], ctx["s5"]], **S6)
    ctx["s6"] = detour["id"]
    mission_action(
        ctx["mi"], "REPORT_BLOCKAGE", headers=OPERATOR, blocking_segment_id=ctx["s3"]
    )
    set_clock(RESUME_CLOCK_UTC)
    replacement = submit_route_plan(
        read_mission(ctx["mi"]), [ctx["s1"], ctx["s2"], ctx["s6"], ctx["s5"]]
    )
    validate_and_activate_plan(replacement["id"])
    ctx["p2"] = replacement["id"]
    mission_action(ctx["mi"], "RESUME", headers=OPERATOR)
    mission_action(ctx["mi"], "ARRIVE")
    ctx["mission"] = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])
    ctx["order"] = read_order(ctx["o"])
    return ctx


class TestBlockageCreditStopsAtTheCap:
    def test_ninety_blocked_minutes_earn_the_capped_credit_and_not_the_linear_one(self, api):
        """PRD §3.3: "The distance term first converts distance into whole
        100-metre units, rounding any partial unit up, and charges 22 cents per
        unit."
        PRD §3.3: "To that is added a base fee of 349 cents; the payload-tier
        supplement, which is 0 cents for `SMALL`, 120 cents for `MEDIUM` and 260
        cents for `LARGE`; an urgency surcharge of 180 cents when `urgency_flag`
        is true and nothing when it is false; 35 cents for each crossing
        traversed; and 95 cents for each remote intervention counted against the
        delivery."
        PRD §3.3: "A blockage credit is then computed as 8 cents for each whole
        minute the delivery spent blocked, but the credit is capped at 40 percent
        of the gross fee with any fraction of a cent in that cap discarded;
        whichever of the two amounts is smaller is the credit that applies."
        PRD §3.3: "The credit is subtracted from the gross fee, and the merchant
        grade discount is applied exactly once to that whole remaining basis —
        nothing for `STANDARD`, 5 percent off for `PREFERRED` and 12 percent off
        for `ANCHOR` — never per component."
        PRD §3.3: "The result is rounded half up to whole cents at that single
        final step, with no intermediate rounding anywhere in the chain."
        PRD §3.7: "The order moves from `IN_TRANSIT` to the terminal `DELIVERED`
        and `settled_fee_cents` is written from the settlement evaluation of the
        delivery fee — the same formula as the quote of §3.3, but with all four
        future-dependent inputs replaced by what actually happened: the distance
        is the mission's `traveled_distance_m`, the crossing count is its
        `traversed_crossing_count`, the intervention count is its
        `intervention_count` and the blocked minutes are its `blocked_minutes`."

        Sixteen 100-metre units at 22 plus 349 plus 120 plus 180 plus two
        crossings at 35 is a gross of 1071; the linear credit of 720 loses to the
        cap of floor(1071 * 0.4) == 428, and 643 discounted by 5 percent rounds
        to 611.

        Design: Corner/calculations/blockage_credit_stops_at_the_forty_percent_cap
        """
        ctx = _late_delivery_after_a_ninety_minute_blockage()

        order = ctx["order"]
        assert order["order_state"] == "DELIVERED"
        assert order["settled_fee_cents"] == 611
        assert order["exception_reason"] == "LATE"

    def test_the_reroute_banks_both_hauls_and_the_whole_blocked_interval(self, api):
        """PRD §3.7: "On success `blocking_segment_id` is cleared, the blocked
        time is banked — the whole minutes elapsed from `blocked_at_utc` to the
        current instant, discarding any partial minute, are added to
        `blocked_minutes` — and `blocked_at_utc` is cleared to null."
        PRD §3.7: "The replacement plan's `total_length_m` and `crossing_count`
        are then added to the mission's accumulators on top of what the superseded
        plan already contributed, because the robot really did travel both."
        PRD §3.7: "The mission stamps `completed_at_utc` and computes
        `active_minutes` as the whole minutes elapsed from `departed_at_utc` to
        `completed_at_utc`, discarding any partial minute."

        Design: Corner/calculations/blockage_credit_stops_at_the_forty_percent_cap
        """
        ctx = _late_delivery_after_a_ninety_minute_blockage()

        mission = ctx["mission"]
        assert mission["mission_state"] == "COMPLETED"
        assert mission["blocked_minutes"] == 90
        assert mission["blocked_at_utc"] is None
        assert mission["traveled_distance_m"] == 1588.0
        assert mission["traversed_crossing_count"] == 2
        assert mission["active_minutes"] == 90

    def test_the_negative_variance_is_parked_outside_the_two_money_buckets(self, api):
        """PRD §3.7: "The merchant's money then moves from escrow into revenue:
        `escrowed_fee_cents` decreases by `quoted_fee_cents`,
        `recognized_fee_cents` increases by the same `quoted_fee_cents`, and
        `settlement_variance_cents` accumulates the signed difference of
        `settled_fee_cents` minus `quoted_fee_cents`, so a reroute that lengthened
        the haul pushes the variance positive while a large blockage credit can
        push it negative."
        PRD §3.7: "When the mission's `completed_at_utc` is strictly later than
        the order's `promised_by_utc`, `exception_reason` is latched to `LATE` on
        the delivered order without changing `order_state` — a late delivery is
        still a delivery, but it becomes eligible for a remedy."
        PRD §3.7: "The order moves to `EXCEPTION` with the `exception_reason`
        given by the pinned abort mapping, the merchant's quoted amount moves from
        `escrowed_fee_cents` to `released_fee_cents`, and the merchant's
        `exception_count` advances by one."

        Design: Corner/calculations/blockage_credit_stops_at_the_forty_percent_cap
        """
        ctx = _late_delivery_after_a_ninety_minute_blockage()
        quote = ctx["order"]["quoted_fee_cents"]
        assert quote == 850

        merchant = read_merchant(ctx["m"])
        assert merchant["recognized_fee_cents"] == 850
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["released_fee_cents"] == 0
        assert merchant["settlement_variance_cents"] == -239
        assert merchant["exception_count"] == 0


class TestGoodwillCreditChargesOnlyTheThirdBucket:
    def test_the_late_goodwill_amount_is_the_flat_policy_figure_alone(self, api):
        """PRD §3.8: "A `LATE` delivery refunds 25 percent of the fee, compensates
        none of the declared value and adds 150 cents."
        PRD §3.8: "A `GOODWILL_CREDIT` charges only the third bucket, so its
        amount is exactly the policy's flat goodwill figure, and it leaves
        `order_state` completely untouched — a delivered order stays delivered and
        an excepted order stays excepted."
        PRD §3.8: "The third bucket is the policy's flat goodwill amount, which is
        already an exact integer and never rounds."
        PRD §3.8: "Every remedy records three fields on the order regardless of
        kind: `remedy_kind` as requested, `remedy_reason_code` set to the
        `exception_reason` that selected the policy — captured before a
        redelivery clears it, so the reason survives on the order even after the
        field it came from is null — and `remedy_amount_cents` as computed."

        A refund of the same order would charge 153 + 0 + 150; the goodwill credit
        charges the 150 on its own.

        Design: Corner/calculations/goodwill_credit_charges_only_the_third_bucket
        """
        ctx = _late_delivery_after_a_ninety_minute_blockage()

        remedied = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("GOODWILL_CREDIT"), SUPPORT)
        )

        assert remedied["order_state"] == "DELIVERED"
        assert remedied["remedy_kind"] == "GOODWILL_CREDIT"
        assert remedied["remedy_reason_code"] == "LATE"
        assert remedied["remedy_amount_cents"] == 150
        assert remedied["exception_reason"] == "LATE"

    def test_the_credit_moves_the_zone_budget_and_nothing_else(self, api):
        """PRD §3.8: "On success the zone's `remedy_spent_cents` increases by the
        amount and `remedy_budget_remaining_cents` is recomputed as
        `remedy_budget_cents` minus `remedy_spent_cents`, with the zone's
        `version` advancing by one."
        PRD §3.7: "Note carefully that the two money buckets move by the quote,
        never by the settlement; the variance field is the only place the
        difference is recorded."

        Design: Corner/calculations/goodwill_credit_charges_only_the_third_bucket
        """
        ctx = _late_delivery_after_a_ninety_minute_blockage()
        assert read_zone(ctx["z"])["remedy_spent_cents"] == 0

        validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("GOODWILL_CREDIT"), SUPPORT)
        )

        zone = read_zone(ctx["z"])
        assert zone["remedy_spent_cents"] == 150
        assert zone["remedy_budget_remaining_cents"] == 49850
        assert read_merchant(ctx["m"])["recognized_fee_cents"] == 850
        assert read_order(ctx["o"])["settled_fee_cents"] == 611


def _two_blocked_route_exceptions_against_a_575_cent_budget() -> dict:
    """Two 850-cent orders whose missions were both aborted for an unrecoverable
    blockage, in a zone whose whole remedy budget is 575 cents."""
    ctx = setup_received_order(zone_overrides={"remedy_budget_cents": 575})
    second_order = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    ctx["o2"] = second_order["id"]
    first_mission = dispatch_mission(ctx["order"], ctx["r"])
    abort_mission(first_mission["id"], "UNRECOVERABLE_BLOCKAGE")
    second_mission = dispatch_mission(second_order, ctx["r"])
    abort_mission(second_mission["id"], "UNRECOVERABLE_BLOCKAGE")
    ctx["order"] = read_order(ctx["o"])
    ctx["order2"] = read_order(ctx["o2"])
    return ctx


class TestBlockedRoutePolicyAndTheInclusiveBudgetGate:
    def test_a_refund_of_exactly_the_remaining_budget_is_admitted(self, api):
        """PRD §3.7: "`ZONE_REVOKED` maps to `BLOCKED_ROUTE`,
        `DISPATCH_CANCELLED` maps to `ROBOT_FAULT`, and `UNRECOVERABLE_BLOCKAGE`
        maps to `BLOCKED_ROUTE`."
        PRD §3.8: "A `BLOCKED_ROUTE` failure refunds half the fee, compensates
        none of the declared value and adds 150 cents."
        PRD §3.8: "The first bucket is the fee refund: the fee basis is the
        order's `settled_fee_cents` when that field is not null and its
        `quoted_fee_cents` otherwise, since a mission that never completed has no
        settlement, and the basis multiplied by the policy's fee fraction is
        rounded half up to whole cents."
        PRD §3.8: "A `REFUND` charges all three buckets and carries the order to
        the terminal `REFUNDED`, from either `EXCEPTION` or `DELIVERED`."
        PRD §3.8: "The gate is inclusive, so an amount exactly equal to the
        remaining budget is allowed and drives the remaining budget to zero."

        Half of the 850-cent quote is 425, the declared-value bucket is 0 and the
        goodwill bucket is 150, so the amount is exactly the 575 that remains.

        Design: Corner/calculations/blocked_route_policy_row_and_the_inclusive_budget_gate
        """
        ctx = _two_blocked_route_exceptions_against_a_575_cent_budget()
        assert ctx["order"]["exception_reason"] == "BLOCKED_ROUTE"
        assert ctx["order"]["settled_fee_cents"] is None
        assert ctx["order"]["quoted_fee_cents"] == 850

        remedied = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        zone = read_zone(ctx["z"])
        assert remedied["remedy_amount_cents"] == 575
        assert remedied["order_state"] == "REFUNDED"
        assert remedied["remedy_reason_code"] == "BLOCKED_ROUTE"
        assert zone["remedy_spent_cents"] == 575
        assert zone["remedy_budget_remaining_cents"] == 0

    def test_the_second_identical_refund_is_refused_rather_than_partly_paid(self, api):
        """PRD §3.8: "For a `REFUND` and for a `GOODWILL_CREDIT`, the computed
        amount must be no greater than the zone's `remedy_budget_remaining_cents`,
        and an amount above it is refused with `ERR_REMEDY_BUDGET_EXCEEDED` (HTTP
        402)."
        PRD §3.8: "Every remedy records three fields on the order regardless of
        kind: `remedy_kind` as requested, `remedy_reason_code` set to the
        `exception_reason` that selected the policy — captured before a
        redelivery clears it, so the reason survives on the order even after the
        field it came from is null — and `remedy_amount_cents` as computed."

        Design: Corner/calculations/blocked_route_policy_row_and_the_inclusive_budget_gate
        """
        ctx = _two_blocked_route_exceptions_against_a_575_cent_budget()
        validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        validate_error(
            api.issue_order_remedy(ctx["o2"], remedy_payload("REFUND"), SUPPORT),
            "ERR_REMEDY_BUDGET_EXCEEDED",
            402,
        )

        order2 = read_order(ctx["o2"])
        assert order2["order_state"] == "EXCEPTION"
        assert order2["remedy_kind"] is None
        assert order2["remedy_amount_cents"] is None
        assert read_zone(ctx["z"])["remedy_spent_cents"] == 575


def _four_robots_of_which_one_is_eligible() -> dict:
    """One pristine robot, one at 34.9 percent battery, one impaired but on duty
    and one never staged, all homed to the same permitted zone."""
    ctx = setup_available_robot()
    low_battery = setup_second_robot(ctx, asset_tag="RBT-002")
    impaired = setup_second_robot(ctx, asset_tag="RBT-003")
    never_staged = add_robot(ctx["z"], asset_tag="RBT-004", stage=False)
    ctx["r2"] = low_battery["id"]
    ctx["r3"] = impaired["id"]
    ctx["r4"] = never_staged["id"]
    set_battery(ctx["r2"], 34.9)
    health_action(ctx["r3"], "DOWNGRADE", reason="camera lens dusted over")
    health_action(ctx["r3"], "IMPAIR", reason="lidar return fault")
    return ctx


class TestEligibleOnlyAppliesTheSelectorFilter:
    def test_only_the_untouched_robot_survives_the_filter_clauses(self, api):
        """PRD §3.6: "The same filter has a read-side face. The robot list
        endpoint accepts `eligible_only`, and when that flag is true the list is
        narrowed to the eligible pool and ordered by `rolling_autonomy_index`
        descending, then `battery_pct` descending, then `created_at` ascending;
        the `id` is never consulted for ordering, even as a last-resort
        tie-break."
        PRD §3.6: "Its `duty_state` must be `AVAILABLE`, or the dispatch is
        refused with `ERR_ROBOT_NOT_AVAILABLE` (HTTP 409) — a robot that is
        `OFFLINE`, `STAGING`, already `ON_MISSION`, `CHARGING`, in `MAINTENANCE`
        or `RETIRED` is out."
        PRD §3.6: "Its `health_state` must be `NOMINAL` or `DEGRADED`, or the
        dispatch is refused with `ERR_ROBOT_HEALTH_BLOCKED` (HTTP 409)."
        PRD §3.6: "The two remaining clauses share one error: `battery_pct` must
        be at least 35.0 percent and `rolling_autonomy_index` must be at least 70,
        and a failure of either, or a zone in which no robot at all satisfies the
        whole filter, is refused with `ERR_NO_ELIGIBLE_ROBOT` (HTTP 422)."
        PRD §3.4: "A newly registered robot has `duty_state` `OFFLINE`,
        `health_state` `NOMINAL`, `battery_pct` 100.0, `odometer_m` 0.0,
        `yield_event_count` 0, `tamper_flag` false, `lifetime_mission_count`,
        `lifetime_intervention_count`, `lifetime_escalation_count` and
        `clean_mission_count` all zero, both `rolling_autonomy_index` and
        `lifetime_autonomy_index` at 100, and `active_mission_id` and
        `current_bay_reservation_id` both null."

        Design: Corner/calculations/eligible_only_listing_applies_the_selector_filter
        """
        ctx = _four_robots_of_which_one_is_eligible()

        rows, meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"], "eligible_only": "true"})
        )

        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == ctx["r"]
        assert rows[0]["battery_pct"] == 100.0

    def test_each_excluded_robot_keeps_the_dimension_that_excluded_it(self, api):
        """PRD §3.5: "A frame that leaves `battery_pct` at 20.0 percent or below
        downgrades a `NOMINAL` robot to `DEGRADED`; the threshold is inclusive,
        and because the transition is defined only from `NOMINAL`, a robot already
        `DEGRADED`, `IMPAIRED` or `QUARANTINED` is left where it is."
        PRD §3.5: "`IMPAIR` carries `DEGRADED` to `IMPAIRED`; an impaired robot is
        no longer eligible for dispatch, but any mission it is already running
        continues untouched, which is the clearest illustration of the two
        dimensions being independent."
        PRD §3.5: "Every health transition advances the robot's `version` by one
        and, apart from the quarantine cascade, leaves `duty_state` exactly as it
        was."

        A 34.9 percent frame is far above the low-battery threshold, so the robot
        it excludes from the pool is still `NOMINAL`.

        Design: Corner/calculations/eligible_only_listing_applies_the_selector_filter
        """
        ctx = _four_robots_of_which_one_is_eligible()

        low_battery = read_robot(ctx["r2"])
        impaired = read_robot(ctx["r3"])
        never_staged = read_robot(ctx["r4"])

        assert low_battery["battery_pct"] == 34.9
        assert low_battery["health_state"] == "NOMINAL"
        assert impaired["health_state"] == "IMPAIRED"
        assert impaired["duty_state"] == "AVAILABLE"
        assert never_staged["duty_state"] == "OFFLINE"

    def test_a_battery_of_exactly_thirty_five_rejoins_the_pool(self, api):
        """PRD §3.6: "Every comparison in the filter is inclusive at its boundary,
        so a battery of exactly 35.0 and an index of exactly 70 are both
        eligible."
        PRD §3.6: "The same filter has a read-side face. The robot list endpoint
        accepts `eligible_only`, and when that flag is true the list is narrowed to
        the eligible pool and ordered by `rolling_autonomy_index` descending, then
        `battery_pct` descending, then `created_at` ascending; the `id` is never
        consulted for ordering, even as a last-resort tie-break."

        The filter narrows the reported list and never the stored rows, so the
        unfiltered read still counts all four robots.

        Design: Corner/calculations/eligible_only_listing_applies_the_selector_filter
        """
        ctx = _four_robots_of_which_one_is_eligible()

        set_battery(ctx["r2"], 35.0)

        rows, meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"], "eligible_only": "true"})
        )
        everything, all_meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"]})
        )
        assert meta["total_count"] == 2
        assert [row["id"] for row in rows] == [ctx["r"], ctx["r2"]]
        assert all_meta["total_count"] == 4
        assert len(everything) == 4


class TestZoneEconomicsWithNoDeliveries:
    def test_an_idle_zone_still_reports_a_capacity_and_an_overhead(self, api):
        """PRD §3.9: "The second step multiplies the number of the zone's robots
        whose `duty_state` is not `RETIRED` by a nominal shift of 600 minutes each
        to give the fleet capacity minutes."
        PRD §3.9: "The third step computes utilization as a percentage: active
        minutes divided by capacity minutes, multiplied by 100, capped at 100.0,
        and rounded half up to one decimal place — and it is exactly 0.0 when the
        capacity is zero, since a zone with no unretired robot has no
        denominator."
        PRD §3.9: "The fourth step allocates overhead as a base of 40000 cents
        plus 150 cents for every whole utilization point, the point count being
        the third step's already-rounded percentage with its fractional part
        discarded; that consumption of a rounded value is precisely why the third
        step cannot be folded into this one."
        PRD §3.9: "The fifth step computes variable cost as 9 cents for each whole
        100-metre unit of the total distance travelled, rounding any partial unit
        up, plus 140 cents for each intervention counted, both totalled over the
        same terminal-mission set as the first step, plus the zone's
        `remedy_spent_cents` exactly as it stands."

        Design: Corner/calculations/zone_economics_with_no_deliveries_reports_null_unit_costs
        """
        ctx = setup_available_robot()

        economics = read_economics(ctx["z"])

        assert economics["zone_id"] == ctx["z"]
        assert economics["robot_active_minutes"] == 0
        assert economics["fleet_capacity_minutes"] == 600
        assert economics["utilization_pct"] == 0.0
        assert economics["allocated_overhead_cents"] == 40000
        assert economics["variable_cost_cents"] == 0

    def test_the_two_unit_figures_are_null_while_the_throughput_is_zero(self, api):
        """PRD §3.9: "The sixth step counts the zone's delivered orders — those
        whose `order_state` is `DELIVERED` or `REFUNDED` — and divides the sum of
        allocated overhead and variable cost by that count, rounded half up to
        whole cents, to give the cost per delivery; when the count is zero the cost
        per delivery is null rather than zero."
        PRD §3.9: "contribution per delivery is null whenever the cost per
        delivery is null because both quotients share the same denominator."
        PRD §3.9: "The eighth step computes throughput as the delivered count
        divided by the fleet capacity expressed in hours, that is capacity minutes
        divided by 60, rounded half up to two decimal places, and it is 0.00 when
        the capacity is zero."
        PRD §3.9: "`cost_per_delivery_cents` and `contribution_per_delivery_cents`
        are the only two that may be null."

        Design: Corner/calculations/zone_economics_with_no_deliveries_reports_null_unit_costs
        """
        ctx = setup_available_robot()

        economics = read_economics(ctx["z"])

        assert economics["delivered_count"] == 0
        assert economics["cost_per_delivery_cents"] is None
        assert economics["contribution_per_delivery_cents"] is None
        assert economics["throughput_per_robot_hour"] == 0.00
