"""The delivery fee evaluated twice, and the two autonomy index variants.

Both subjects are one formula read from two different input sets on the same
row, so each test pins the two answers against each other.
"""
from test_helpers import (
    DISPATCHER,
    OPERATOR,
    add_order,
    dispatch_mission,
    intervention_action,
    load_mission,
    mission_action,
    open_intervention,
    read_merchant,
    read_mission,
    read_order,
    read_robot,
    set_clock,
    setup_en_route_mission,
    setup_handoff_ready_mission,
    setup_received_order,
    submit_route_plan,
    validate_and_activate_plan,
)


def _two_mission_history() -> dict:
    """One robot runs two deliveries: the first records two released takeovers,
    the second is clean and completes later on the logical clock."""
    ctx = setup_en_route_mission()

    first = open_intervention(ctx["mi"], 80, trigger_reason="PEDESTRIAN_CONFLICT")
    intervention_action(first["id"], "RELEASE", headers=DISPATCHER)
    second = open_intervention(ctx["mi"], 80, trigger_reason="OBSTACLE")
    intervention_action(second["id"], "RELEASE", headers=DISPATCHER)
    mission_action(ctx["mi"], "ARRIVE")
    ctx["mission"] = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

    order_two = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    mission_two = dispatch_mission(order_two, ctx["r"])
    mission_two = load_mission(mission_two["id"], ctx["m"], 22.0)
    plan_two = submit_route_plan(
        mission_two, [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    )
    validate_and_activate_plan(plan_two["id"])
    mission_action(mission_two["id"], "DEPART")
    set_clock("2026-08-03T10:00:00.000Z")
    mission_action(mission_two["id"], "ARRIVE")
    ctx["mission_two"] = mission_action(
        mission_two["id"], "COMPLETE", lid_access_code=mission_two["lid_access_code"]
    )
    ctx["mi2"] = mission_two["id"]
    ctx["o2"] = order_two["id"]
    return ctx


class TestDeliveryFeeQuoteVersusSettlement:
    def test_intake_quote_is_built_from_the_zone_planning_assumptions(self, api):
        """PRD §3.3: "At intake there is no mission and no route plan, so the
        quote is built entirely from the zone's planning assumptions: the
        distance is the `planning_haul_m` of the zone that owns the dropoff
        segment, the crossing count is that zone's `planning_crossings`, and
        both the intervention count and the blocked minutes are treated as
        zero."
        PRD §3.3: "The distance term first converts distance into whole
        100-metre units, rounding any partial unit up, and charges 22 cents per
        unit."
        PRD §3.3: "To that is added a base fee of 349 cents; the payload-tier
        supplement, which is 0 cents for `SMALL`, 120 cents for `MEDIUM` and
        260 cents for `LARGE`; an urgency surcharge of 180 cents when
        `urgency_flag` is true and nothing when it is false; 35 cents for each
        crossing traversed; and 95 cents for each remote intervention counted
        against the delivery."

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_settlement_diverges
        """
        ctx = setup_received_order()
        order = ctx["order"]

        assert order["quoted_fee_cents"] == 850
        assert order["settled_fee_cents"] is None
        assert order["payload_tier"] == "MEDIUM"
        assert order["urgency_flag"] is True
        assert order["order_state"] == "RECEIVED"

    def test_settlement_replaces_every_forward_looking_input_with_the_actuals(self, api):
        """PRD §3.7: "The order moves from `IN_TRANSIT` to the terminal
        `DELIVERED` and `settled_fee_cents` is written from the settlement
        evaluation of the delivery fee — the same formula as the quote of §3.3,
        but with all four future-dependent inputs replaced by what actually
        happened: the distance is the mission's `traveled_distance_m`, the
        crossing count is its `traversed_crossing_count`, the intervention
        count is its `intervention_count` and the blocked minutes are its
        `blocked_minutes`."
        PRD §3.7: "Departure stamps `departed_at_utc` with the current instant,
        adds the active plan's `total_length_m` to the mission's
        `traveled_distance_m` and its `crossing_count` to
        `traversed_crossing_count`, and carries the order from `DISPATCHED` to
        `IN_TRANSIT`."

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_settlement_diverges
        """
        ctx = setup_handoff_ready_mission()

        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        mission = read_mission(ctx["mi"])
        order = read_order(ctx["o"])
        assert mission["traveled_distance_m"] == 774.0
        assert mission["traversed_crossing_count"] == 1
        assert order["order_state"] == "DELIVERED"
        assert order["quoted_fee_cents"] == 850
        assert order["settled_fee_cents"] == 817

    def test_completion_measures_active_minutes_on_the_logical_clock(self, api):
        """PRD §3.7: "The mission stamps `completed_at_utc` and computes
        `active_minutes` as the whole minutes elapsed from `departed_at_utc` to
        `completed_at_utc`, discarding any partial minute."

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_settlement_diverges
        """
        ctx = setup_handoff_ready_mission()

        mission = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        assert mission["mission_state"] == "COMPLETED"
        assert mission["active_minutes"] == 12

    def test_the_two_money_buckets_move_by_the_quote_and_the_variance_absorbs_the_difference(
        self, api
    ):
        """PRD §3.7: "The merchant's money then moves from escrow into revenue:
        `escrowed_fee_cents` decreases by `quoted_fee_cents`,
        `recognized_fee_cents` increases by the same `quoted_fee_cents`, and
        `settlement_variance_cents` accumulates the signed difference of
        `settled_fee_cents` minus `quoted_fee_cents`, so a reroute that
        lengthened the haul pushes the variance positive while a large blockage
        credit can push it negative."

        Design: Difficulty/dual_variant_calc/delivery_fee_quote_vs_settlement_diverges
        """
        ctx = setup_handoff_ready_mission()

        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        merchant = read_merchant(ctx["m"])
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["recognized_fee_cents"] == 850
        assert merchant["settlement_variance_cents"] == -33


class TestAutonomyIndexVariants:
    def test_rolling_index_weights_the_newest_mission_full_and_the_older_one_less(self, api):
        """PRD §3.5: "The rolling variant, stored in `rolling_autonomy_index`,
        is a recency-weighted window: the robot's terminal missions are ordered
        by `completed_at_utc` descending with ties broken by `created_at`
        ascending, the newest five are kept and the rest ignored, and the
        mission in position zero of that order counts at full weight while each
        subsequent position counts at 0.85 times the weight of the position
        before it."
        PRD §3.5: "Each terminal mission contributes a penalty of 6 points for
        every remote intervention it recorded plus a further 4 points for every
        one of those interventions that was escalated, so a mission with one
        plain intervention costs 6 points while a mission with one escalated
        intervention costs 10."
        PRD §3.5: "Each terminal mission that recorded no intervention at all
        instead contributes a credit of 2 points; a mission with interventions
        earns no credit."

        Design: Difficulty/dual_variant_calc/autonomy_index_rolling_vs_lifetime_diverges
        """
        ctx = _two_mission_history()

        robot = read_robot(ctx["r"])
        assert robot["rolling_autonomy_index"] == 92
        assert read_mission(ctx["mi"])["intervention_count"] == 2
        assert read_mission(ctx["mi2"])["intervention_count"] == 0

    def test_lifetime_index_weights_every_mission_equally_from_the_stored_counters(self, api):
        """PRD §3.5: "The lifetime variant, stored in
        `lifetime_autonomy_index`, weights every terminal mission the robot has
        ever run at exactly 1 and is expressed through the stored counters:
        from the base of 100, subtract 6 points for each unit of
        `lifetime_intervention_count` and 4 more for each unit of
        `lifetime_escalation_count`, then add 2 points for each unit of
        `clean_mission_count`."
        PRD §3.7: "Finally the robot returns from `ON_MISSION` to `AVAILABLE`,
        its `active_mission_id` is cleared, the zone's `on_mission_robot_count`
        is decremented, and the robot's history absorbs the mission:
        `lifetime_mission_count` advances by one, `lifetime_intervention_count`
        by the mission's `intervention_count`, `lifetime_escalation_count` by
        its `escalation_count`, and `clean_mission_count` by one only when the
        mission recorded no interventions at all, after which both autonomy
        index variants of §3.5 are recomputed."

        Design: Difficulty/dual_variant_calc/autonomy_index_rolling_vs_lifetime_diverges
        """
        ctx = _two_mission_history()

        robot = read_robot(ctx["r"])
        assert robot["lifetime_mission_count"] == 2
        assert robot["lifetime_intervention_count"] == 2
        assert robot["lifetime_escalation_count"] == 0
        assert robot["clean_mission_count"] == 1
        assert robot["lifetime_autonomy_index"] == 90
        assert robot["duty_state"] == "AVAILABLE"

    def test_a_waived_takeover_still_counts_against_the_mission(self, api):
        """PRD §3.7: "All three forms advance the mission's
        `intervention_count` by one, so even a waived request counts against
        the robot's autonomy index."

        Design: Difficulty/dual_variant_calc/autonomy_index_rolling_vs_lifetime_diverges
        """
        ctx = setup_en_route_mission()
        event = open_intervention(ctx["mi"], 80, headers=OPERATOR)

        intervention_action(event["id"], "RELEASE", headers=DISPATCHER)

        assert read_mission(ctx["mi"])["intervention_count"] == 1
