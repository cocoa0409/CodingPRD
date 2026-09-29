"""Inclusive boundaries, tested one unit either side of the threshold.

Each pair differs only in the metric under test, so an implementation that
flips a comparison operator fails exactly one test of the pair.
"""
import pytest

from test_helpers import (
    ADMIN,
    DISPATCHER,
    OPERATOR,
    add_order,
    add_robot,
    approve_segment,
    dispatch_mission,
    intervention_action,
    map_segment,
    open_intervention,
    provision_zone,
    read_intervention,
    read_mission,
    read_segment,
    set_clock,
    setup_active_merchant,
    setup_en_route_mission,
    survey_segment,
    validate_error,
    validate_paginated,
    validate_success,
    BASE_CLOCK_UTC,
    create_route_plan_payload,
)

MIDBLOCK_CROSSING = {
    "segment_type": "CROSSING",
    "crossing_control": "MIDBLOCK",
    "length_m": 16.0,
    "measured_clearance_cm": 98.0,
    "surface_grade_pct": 3.0,
    "sightline_m": 20.0,
    "curb_ramp_present": True,
}


def _missions_for_two_robot_widths() -> dict:
    """Two planned missions on the same route, one robot exactly as wide as the
    tightest segment allows and one a centimetre wider."""
    ctx = setup_active_merchant()
    exact = add_robot(ctx["z"], asset_tag="RBT-002", width_cm=80.0)
    wide = add_robot(ctx["z"], asset_tag="RBT-003", width_cm=81.0)
    order_exact = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    order_wide = add_order(ctx["m"], ctx["s5"], customer_ref="C-3")
    ctx["mission_exact"] = dispatch_mission(order_exact, exact["id"])
    ctx["mission_wide"] = dispatch_mission(order_wide, wide["id"])
    ctx["route"] = [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]]
    return ctx


class TestRouteClearanceMarginBoundary:
    def test_a_margin_of_exactly_zero_is_accepted(self, api):
        """PRD §3.6: "`clearance_margin_cm` is the accessibility slack of the
        tightest segment for this particular robot: for each segment in the
        sequence, subtract the robot's `width_cm` and then a further ordinance
        buffer of 12 centimetres from that segment's `measured_clearance_cm`,
        and take the smallest of those results, rounded to one decimal place."
        PRD §3.6: "The clearance gate is inclusive: a `clearance_margin_cm` of
        exactly 0.0 passes and any negative margin is refused with
        `ERR_CLEARANCE_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_margin_zero_accepted_negative_rejected
        """
        ctx = _missions_for_two_robot_widths()
        mission = ctx["mission_exact"]

        plan = validate_success(
            api.create_route_plan(
                create_route_plan_payload(mission["id"], ctx["route"], mission["version"]),
                DISPATCHER,
            ),
            201,
        )

        assert plan["clearance_margin_cm"] == pytest.approx(0.0)
        assert plan["plan_state"] == "DRAFT"
        assert plan["total_length_m"] == 774.0
        assert plan["crossing_count"] == 1
        assert plan["planned_duration_min"] == 9
        assert plan["revision_index"] == 1

    def test_a_margin_of_one_centimetre_below_zero_is_refused(self, api):
        """PRD §3.6: "The clearance gate is inclusive: a `clearance_margin_cm`
        of exactly 0.0 passes and any negative margin is refused with
        `ERR_CLEARANCE_INSUFFICIENT` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/clearance_margin_zero_accepted_negative_rejected
        """
        ctx = _missions_for_two_robot_widths()
        mission = ctx["mission_wide"]

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(mission["id"], ctx["route"], mission["version"]),
                DISPATCHER,
            ),
            "ERR_CLEARANCE_INSUFFICIENT",
        )

        plans, _meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": mission["id"]})
        )
        assert plans == []


class TestTakeoverConfidenceBoundary:
    def test_confidence_exactly_at_the_threshold_is_mandatory_and_unwaivable(self, api):
        """PRD §3.7: "The event is created in `takeover_state` `REQUESTED`, and
        one value is frozen at that instant: `mandatory` is true when
        `autonomy_confidence_pct` is at or below the zone's
        `takeover_confidence_threshold_pct` and false otherwise."
        PRD §3.7: "The comparison is inclusive, so against the default threshold
        of 35 a confidence of 35 is mandatory while a confidence of 36 is not,
        and because the zone is reached through the mission's robot, two events
        with identical confidence in differently configured zones classify
        differently."
        PRD §3.7: "The third form is a release straight out of `REQUESTED` by a
        `FleetDispatcher`, for a low-severity request the robot recovered from on
        its own; it is permitted only when `mandatory` is false, since waiving a
        mandatory takeover without an operator ever assuming control is refused
        with `ERR_TAKEOVER_REQUIRED`, and it records `control_seconds` as 0 and
        leaves `assumed_at_utc` null."

        Design: Difficulty/boundary_precision_check/takeover_threshold_inclusive_at_35_exclusive_at_36
        """
        ctx = setup_en_route_mission()
        event = open_intervention(ctx["mi"], 35, headers=OPERATOR)
        assert event["mandatory"] is True

        validate_error(
            api.intervention_transition(event["id"], {"action": "RELEASE"}, DISPATCHER),
            "ERR_TAKEOVER_REQUIRED",
        )

        assert read_intervention(event["id"])["takeover_state"] == "REQUESTED"

    def test_confidence_one_point_above_the_threshold_may_be_waived(self, api):
        """PRD §3.7: "The comparison is inclusive, so against the default
        threshold of 35 a confidence of 35 is mandatory while a confidence of 36
        is not, and because the zone is reached through the mission's robot, two
        events with identical confidence in differently configured zones classify
        differently."
        PRD §3.7: "All three forms advance the mission's `intervention_count` by
        one, so even a waived request counts against the robot's autonomy index."

        Design: Difficulty/boundary_precision_check/takeover_threshold_inclusive_at_35_exclusive_at_36
        """
        ctx = setup_en_route_mission()
        event = open_intervention(ctx["mi"], 36, headers=OPERATOR)
        assert event["mandatory"] is False

        released = intervention_action(event["id"], "RELEASE", headers=DISPATCHER)

        assert released["takeover_state"] == "RELEASED"
        assert released["control_seconds"] == 0
        assert released["assumed_at_utc"] is None
        assert read_mission(ctx["mi"])["intervention_count"] == 1


def _two_scored_crossings() -> dict:
    """Two midblock crossings that differ only in pedestrian flow, scored at the
    zone's risk ceiling and just above it."""
    set_clock(BASE_CLOCK_UTC)
    zone = provision_zone()
    at_ceiling = map_segment(zone["id"], "S7", None, pedestrian_flow_per_min=15.0, **MIDBLOCK_CROSSING)
    above = map_segment(zone["id"], "S8", None, pedestrian_flow_per_min=15.5, **MIDBLOCK_CROSSING)
    return {
        "z": zone["id"],
        "s7": survey_segment(at_ceiling["id"])["id"],
        "s8": survey_segment(above["id"])["id"],
    }


class TestCrossingRiskCeilingBoundary:
    def test_a_score_exactly_on_the_ceiling_is_approved(self, api):
        """PRD §3.1: "If the frozen `crossing_risk_score` is above the zone's
        `max_crossing_risk` the approval is refused with
        `ERR_CROSSING_RISK_EXCEEDED`; that comparison is inclusive too, so a
        score exactly equal to the ceiling passes."

        Design: Difficulty/boundary_precision_check/crossing_risk_ceiling_45_accepted_46_rejected
        """
        ctx = _two_scored_crossings()
        assert read_segment(ctx["s7"])["crossing_risk_score"] == pytest.approx(45.0)

        approved = approve_segment(ctx["s7"])

        assert approved["status"] == "APPROVED"

    def test_a_score_seven_tenths_above_the_ceiling_is_refused(self, api):
        """PRD §3.1: "If the frozen `crossing_risk_score` is above the zone's
        `max_crossing_risk` the approval is refused with
        `ERR_CROSSING_RISK_EXCEEDED`; that comparison is inclusive too, so a
        score exactly equal to the ceiling passes."
        PRD §3.1: "Both findings carry HTTP 422."

        Design: Difficulty/boundary_precision_check/crossing_risk_ceiling_45_accepted_46_rejected
        """
        ctx = _two_scored_crossings()
        assert read_segment(ctx["s8"])["crossing_risk_score"] == pytest.approx(45.7)

        validate_error(
            api.segment_transition(ctx["s8"], {"action": "APPROVE"}, ADMIN),
            "ERR_CROSSING_RISK_EXCEEDED",
        )

        assert read_segment(ctx["s8"])["status"] == "SURVEYED"
