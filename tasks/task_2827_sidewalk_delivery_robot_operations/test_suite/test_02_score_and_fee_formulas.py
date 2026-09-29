"""Formulas that compose several independently-shaped terms.

The crossing risk score, the remedy waterfall and the zone economics pipeline
each combine tiers, caps, hinges, clamps and per-step rounding, so the tests
pick inputs on which a fused or reordered evaluation gives a different answer.
"""
import pytest

from test_helpers import (
    BASE_CLOCK_UTC,
    DISPATCHER,
    SUPPORT,
    abort_mission,
    add_order,
    dispatch_mission,
    map_segment,
    mission_action,
    provision_zone,
    read_economics,
    read_order,
    read_segment,
    read_zone,
    remedy_payload,
    set_clock,
    setup_available_robot,
    setup_handoff_ready_mission,
    survey_segment,
    validate_success,
)

S3_FIELDS = {
    "segment_type": "WALKWAY",
    "length_m": 260.0,
    "measured_clearance_cm": 104.0,
    "surface_grade_pct": 4.0,
    "sightline_m": 25.0,
    "pedestrian_flow_per_min": 12.0,
    "curb_ramp_present": False,
}
S9_FIELDS = {
    "segment_type": "CROSSING",
    "crossing_control": "MIDBLOCK",
    "length_m": 10.0,
    "measured_clearance_cm": 100.0,
    "surface_grade_pct": 2.0,
    "sightline_m": 5.0,
    "pedestrian_flow_per_min": 40.0,
    "curb_ramp_present": False,
}
S2_FIELDS = {
    "segment_type": "CROSSING",
    "crossing_control": "SIGNALIZED",
    "length_m": 14.0,
    "measured_clearance_cm": 150.0,
    "surface_grade_pct": 1.5,
    "sightline_m": 35.0,
    "pedestrian_flow_per_min": 10.0,
    "curb_ramp_present": True,
}


class TestCrossingRiskScoreComposition:
    def test_sightline_tier_and_uncapped_flow_add_up_on_a_walkway(self, api):
        """PRD §3.1: "The sightline term is a step function of `sightline_m`: it
        contributes 0 when the sightline is at least 30 metres, 8 when it is at
        least 20 but less than 30, 18 when it is at least 10 but less than 20,
        and 30 when it is below 10 — so a sightline of 30.0 and a sightline of
        39.9 both contribute 0 while 29.9 contributes 8."
        PRD §3.1: "The grade term is the amount by which `surface_grade_pct`
        exceeds 5.0 percent, multiplied by 3.0, and it is exactly 0 for any
        grade up to and including 5.0 percent because the excess is treated as
        zero when the grade does not exceed the hinge."

        Design: Difficulty/combinatorial_formula/crossing_risk_score_tiered_plus_capped_plus_hinge
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        segment = map_segment(zone["id"], "S3", None, **S3_FIELDS)

        surveyed = survey_segment(segment["id"])

        assert surveyed["crossing_risk_score"] == pytest.approx(24.8)

    def test_flow_term_is_capped_before_the_midblock_penalty_is_added(self, api):
        """PRD §3.1: "The pedestrian-flow term is `pedestrian_flow_per_min`
        multiplied by 1.4, but never more than 28; whichever of the two is
        smaller is the term."
        PRD §3.1: "The control term is read from `crossing_control`: `NONE`
        contributes 0, `SIGNALIZED` contributes negative 12, `UNSIGNALIZED`
        contributes positive 10 and `MIDBLOCK` contributes positive 22."

        Design: Difficulty/combinatorial_formula/crossing_risk_score_tiered_plus_capped_plus_hinge
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        segment = map_segment(zone["id"], "S9", None, **S9_FIELDS)

        surveyed = survey_segment(segment["id"])

        assert surveyed["crossing_risk_score"] == pytest.approx(80.0)

    def test_a_negative_total_is_clamped_to_zero_before_rounding(self, api):
        """PRD §3.1: "The ramp term is negative 6 when `curb_ramp_present` is
        true and 0 otherwise."
        PRD §3.1: "Those five terms are added together, the total is then
        clamped into the range 0.0 through 100.0, and only after clamping is it
        rounded half up to one decimal place — which is why a raw total of
        negative 6.0 stores as 0.0 rather than as a negative score."

        Design: Difficulty/combinatorial_formula/crossing_risk_score_tiered_plus_capped_plus_hinge
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()
        segment = map_segment(zone["id"], "S2", None, **S2_FIELDS)

        surveyed = survey_segment(segment["id"])

        assert surveyed["crossing_risk_score"] == pytest.approx(0.0)
        assert surveyed["status"] == "SURVEYED"

    def test_a_mapped_segment_carries_no_score_until_it_is_surveyed(self, api):
        """PRD §3.1: "A newly mapped element sits in `status` `MAPPED` with
        `crossing_risk_score` still null and `blocked_by_closure_id` null."
        PRD §3.1: "From the resulting values the server computes and freezes
        `crossing_risk_score`, and the element's `version` advances by one."

        Design: Difficulty/combinatorial_formula/crossing_risk_score_tiered_plus_capped_plus_hinge
        """
        set_clock(BASE_CLOCK_UTC)
        zone = provision_zone()

        segment = map_segment(zone["id"], "S2", None, **S2_FIELDS)

        assert segment["status"] == "MAPPED"
        assert segment["crossing_risk_score"] is None
        assert read_segment(segment["id"])["crossing_risk_score"] is None


def _aborted_large_order() -> dict:
    """A 40 litre order whose mission is aborted before it ever loads, so the
    remedy basis falls back to the quote."""
    ctx = setup_available_robot()
    order = add_order(
        ctx["m"],
        ctx["s5"],
        customer_ref="C-9",
        payload_liters=40.0,
        declared_value_cents=9004,
        promised_by_utc="2026-08-03T11:00:00.000Z",
    )
    mission = dispatch_mission(order, ctx["r"])
    abort_mission(mission["id"], "DISPATCH_CANCELLED")
    ctx["order"] = read_order(order["id"])
    ctx["o"] = order["id"]
    ctx["mi"] = mission["id"]
    return ctx


class TestRemedyWaterfallRounding:
    def test_each_bucket_is_rounded_on_its_own_before_the_three_are_summed(self, api):
        """PRD §3.8: "The first bucket is the fee refund: the fee basis is the
        order's `settled_fee_cents` when that field is not null and its
        `quoted_fee_cents` otherwise, since a mission that never completed has
        no settlement, and the basis multiplied by the policy's fee fraction is
        rounded half up to whole cents."
        PRD §3.8: "The second bucket is the declared-value compensation: the
        order's `declared_value_cents` is first capped at 15000 cents,
        whichever of the two is smaller being the compensable value, that value
        is multiplied by the policy's declared-value fraction, and the product
        is rounded half up to whole cents on its own."
        PRD §3.8: "The remedy amount is the sum of the three rounded buckets."
        PRD §3.8: "Each bucket is filled and rounded before the next is
        considered, and the buckets are reported in that order; summing the
        three unrounded buckets and rounding the total once is a different and
        incorrect answer whenever two buckets each round down and their
        discarded fractions together reach half a cent."

        Design: Difficulty/combinatorial_formula/remedy_waterfall_rounds_each_bucket_before_summing
        """
        ctx = _aborted_large_order()
        assert ctx["order"]["quoted_fee_cents"] == 812
        assert ctx["order"]["settled_fee_cents"] is None
        assert ctx["order"]["exception_reason"] == "ROBOT_FAULT"

        order = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        assert order["remedy_amount_cents"] == 5936
        assert order["remedy_reason_code"] == "ROBOT_FAULT"

    def test_the_refund_charges_the_zone_budget_and_terminates_the_order(self, api):
        """PRD §3.8: "A `REFUND` charges all three buckets and carries the order
        to the terminal `REFUNDED`, from either `EXCEPTION` or `DELIVERED`."
        PRD §3.8: "On success the zone's `remedy_spent_cents` increases by the
        amount and `remedy_budget_remaining_cents` is recomputed as
        `remedy_budget_cents` minus `remedy_spent_cents`, with the zone's
        `version` advancing by one."

        Design: Difficulty/combinatorial_formula/remedy_waterfall_rounds_each_bucket_before_summing
        """
        ctx = _aborted_large_order()

        order = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        zone = read_zone(ctx["z"])
        assert order["order_state"] == "REFUNDED"
        assert zone["remedy_spent_cents"] == 5936
        assert zone["remedy_budget_remaining_cents"] == 44064


class TestZoneEconomicsPipeline:
    def test_overhead_allocation_consumes_the_already_rounded_utilization(self, api):
        """PRD §3.9: "The third step computes utilization as a percentage:
        active minutes divided by capacity minutes, multiplied by 100, capped at
        100.0, and rounded half up to one decimal place — and it is exactly 0.0
        when the capacity is zero, since a zone with no unretired robot has no
        denominator."
        PRD §3.9: "The fourth step allocates overhead as a base of 40000 cents
        plus 150 cents for every whole utilization point, the point count being
        the third step's already-rounded percentage with its fractional part
        discarded; that consumption of a rounded value is precisely why the
        third step cannot be folded into this one."

        Design: Difficulty/combinatorial_formula/zone_economics_pipeline_consumes_rounded_utilization
        """
        ctx = setup_handoff_ready_mission()
        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        economics = read_economics(ctx["z"], DISPATCHER)

        assert economics["robot_active_minutes"] == 12
        assert economics["fleet_capacity_minutes"] == 600
        assert economics["utilization_pct"] == pytest.approx(2.0)
        assert economics["allocated_overhead_cents"] == 40300

    def test_variable_cost_rounds_hectometres_up_and_contribution_subtracts_integers(
        self, api
    ):
        """PRD §3.9: "The fifth step computes variable cost as 9 cents for each
        whole 100-metre unit of the total distance travelled, rounding any
        partial unit up, plus 140 cents for each intervention counted, both
        totalled over the same terminal-mission set as the first step, plus the
        zone's `remedy_spent_cents` exactly as it stands."
        PRD §3.9: "The seventh step computes contribution per delivery as the
        recognised revenue divided by the same delivered count, rounded half up
        to whole cents, minus the already-rounded cost per delivery, the
        subtraction therefore happening between two integers; recognised revenue
        is the sum of `settled_fee_cents` over those orders less the sum of
        `remedy_amount_cents` over them, and contribution per delivery is null
        whenever the cost per delivery is null because both quotients share the
        same denominator."
        PRD §3.9: "The eighth step computes throughput as the delivered count
        divided by the fleet capacity expressed in hours, that is capacity
        minutes divided by 60, rounded half up to two decimal places, and it is
        0.00 when the capacity is zero."

        Design: Difficulty/combinatorial_formula/zone_economics_pipeline_consumes_rounded_utilization
        """
        ctx = setup_handoff_ready_mission()
        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        economics = read_economics(ctx["z"], DISPATCHER)

        assert economics["variable_cost_cents"] == 72
        assert economics["delivered_count"] == 1
        assert economics["cost_per_delivery_cents"] == 40372
        assert economics["contribution_per_delivery_cents"] == -39555
        assert economics["throughput_per_robot_hour"] == pytest.approx(0.10)
