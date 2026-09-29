"""Requests that violate two rules at once.

Each pair straddles two bands of the rejection ladder, so the test first proves
which finding wins and then removes the winner to prove the loser was really
violated too.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OFFICER,
    add_order,
    add_robot,
    api_client,
    create_delivery_mission_payload,
    create_route_plan_payload,
    dispatch_mission,
    file_incident,
    incident_action,
    make_safety_officer_headers,
    permit_transition_payload,
    read_incident,
    read_mission,
    read_order,
    read_robot,
    set_battery,
    setup_active_merchant,
    setup_available_robot,
    setup_received_order,
    validate_error,
    validate_paginated,
    validate_success,
)


def _restricted_zone_with_flat_battery() -> dict:
    """The zone's permit is restricted and the only robot is below the battery
    floor, so a dispatch violates a state rule and a capacity rule at once."""
    ctx = setup_received_order()
    set_battery(ctx["r"], 30.0)
    validate_success(
        api_client.zone_permit_transition(
            ctx["z"],
            permit_transition_payload(
                "RESTRICT", reason="municipal parade permit pulled for the corridor"
            ),
            ADMIN,
        )
    )
    return ctx


class TestDispatchPermitOutranksEligibility:
    def test_the_restricted_permit_is_reported_and_not_the_empty_pool(self, api):
        """PRD §2.10: "The state band then evaluates, in order: whether the
        requested action is a declared transition out of the target row's
        current state; whether the zone permits operations; whether the
        merchant's integration is active; whether the named robot's duty state
        admits dispatch; whether its health state admits dispatch; whether every
        segment of a plan is approved; whether any segment of a plan is blocked;
        whether the mission is already terminal; whether a reservation is live
        enough for the requested transition; whether an open takeover blocks a
        handoff; whether a remedy has already been issued; and whether the order
        has a latched exception at all."
        PRD §2.10: "The last band covers capacity and money, in the order:
        payload against container capacity; the dispatch eligibility filter and
        the empty-pool case; the lid access code; the zone's concurrent-robot
        cap; bay window exclusivity; hard closure overlap; the zone remedy
        budget; the outstanding-incident condition on clearing a quarantine;
        reservation type against bay type; and finally whether the bay is in
        service at all."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_into_restricted_zone_reports_permit_not_eligibility
        """
        ctx = _restricted_zone_with_flat_battery()

        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], ctx["o_v"]), DISPATCHER
            ),
            "ERR_ZONE_NOT_PERMITTED",
        )

        assert read_order(ctx["o"])["order_state"] == "RECEIVED"

    def test_lifting_the_restriction_surfaces_the_eligibility_failure(self, api):
        """PRD §3.6: "The two remaining clauses share one error: `battery_pct`
        must be at least 35.0 percent and `rolling_autonomy_index` must be at
        least 70, and a failure of either, or a zone in which no robot at all
        satisfies the whole filter, is refused with `ERR_NO_ELIGIBLE_ROBOT`
        (HTTP 422)."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered
        order that is dispatched a second time shows a count of two."

        Design: Difficulty/priority_pair_validation_conflict/dispatch_into_restricted_zone_reports_permit_not_eligibility
        """
        ctx = _restricted_zone_with_flat_battery()
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], ctx["o_v"]), DISPATCHER
            ),
            "ERR_ZONE_NOT_PERMITTED",
        )

        validate_success(
            api.zone_permit_transition(
                ctx["z"], permit_transition_payload("LIFT_RESTRICTION"), ADMIN
            )
        )
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(ctx["o"], ctx["r"], ctx["o_v"]), DISPATCHER
            ),
            "ERR_NO_ELIGIBLE_ROBOT",
        )

        order = read_order(ctx["o"])
        missions, _meta = validate_paginated(
            api.list_delivery_missions(DISPATCHER, {"order_id": ctx["o"]})
        )
        assert order["order_state"] == "RECEIVED"
        assert order["dispatch_attempt_count"] == 0
        assert missions == []
        assert read_robot(ctx["r"])["duty_state"] == "AVAILABLE"


def _two_missions_of_different_widths() -> dict:
    """One wide robot and one narrow robot, each already carrying a planned
    mission for the same dropoff segment."""
    ctx = setup_active_merchant()
    wide = add_robot(ctx["z"], asset_tag="RBT-003", width_cm=81.0)
    narrow = add_robot(ctx["z"], asset_tag="RBT-001", width_cm=78.0)
    order_wide = add_order(ctx["m"], ctx["s5"], customer_ref="C-3")
    order_narrow = add_order(ctx["m"], ctx["s5"], customer_ref="C-1")
    ctx["mission_wide"] = dispatch_mission(order_wide, wide["id"])
    ctx["mission_narrow"] = dispatch_mission(order_narrow, narrow["id"])
    return ctx


class TestRoutePlanSafetyOutranksStructure:
    def test_a_route_that_is_both_too_tight_and_mis_sequenced_reports_clearance(self, api):
        """PRD §2.10: "The safety band evaluates route clearance, then crossing
        risk, then robot speed against the ordinance, then operating-window
        containment, then a segment's measured clearance against the ordinance
        minimum at approval time."
        PRD §2.10: "Accessibility and ordinance findings are deliberately
        reported ahead of the structural band, so a plan that is both too tight
        for its robot and mis-sequenced reports the clearance failure."

        Design: Difficulty/priority_pair_validation_conflict/route_plan_reports_clearance_before_contiguity
        """
        ctx = _two_missions_of_different_widths()
        mission = ctx["mission_wide"]

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    mission["id"], [ctx["s1"], ctx["s3"], ctx["s5"]], mission["version"]
                ),
                DISPATCHER,
            ),
            "ERR_CLEARANCE_INSUFFICIENT",
        )

        plans, _meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": mission["id"]})
        )
        assert plans == []
        assert read_mission(mission["id"])["mission_state"] == "PLANNED"

    def test_the_same_sequence_for_a_narrow_robot_reports_the_contiguity_gap(self, api):
        """PRD §3.6: "The contiguity gate walks each consecutive pair of the
        sequence and requires the successor's identifier to appear in the
        predecessor's `connected_segment_ids`, refusing a gap with
        `ERR_ROUTE_NOT_CONTIGUOUS`."
        PRD §3.6: "Because the margin is computed against the mission's own
        robot, one identical segment sequence can be perfectly legal for a
        narrow robot and illegal for a wider one."

        Design: Difficulty/priority_pair_validation_conflict/route_plan_reports_clearance_before_contiguity
        """
        ctx = _two_missions_of_different_widths()
        mission = ctx["mission_narrow"]

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    mission["id"], [ctx["s1"], ctx["s3"], ctx["s5"]], mission["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ROUTE_NOT_CONTIGUOUS",
        )

        plans, _meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": mission["id"]})
        )
        assert plans == []


def _report_submitted_by_another_officer() -> dict:
    """A minor report filed by one officer and already submitted by a second."""
    ctx = setup_available_robot()
    report = file_incident(
        ctx["z"],
        ctx["r"],
        headers=OFFICER,
        category="RIGHT_OF_WAY_VIOLATION",
        severity="MINOR",
        narrative="robot failed to yield at an unsignalized crossing",
        estimated_damage_cents=0,
    )
    ctx["report"] = incident_action(
        report["id"],
        "SUBMIT_MUNICIPAL",
        headers=make_safety_officer_headers("so-2"),
        municipal_case_ref="SF-2026-0802",
    )
    ctx["ir"] = report["id"]
    return ctx


class TestIncidentDutiesOutrankState:
    def test_the_filers_own_resubmission_reports_segregation_of_duties(self, api):
        """PRD §2.10: "Within the authorisation band the order is: missing or
        empty role header, then role-not-permitted, then merchant ownership,
        then incident segregation of duties, then the recorded-reviewer check on
        a return-for-detail, then the takeover-control check on an escalate or
        operator release."
        PRD §3.9: "It requires a non-empty `municipal_case_ref`, which is
        stored, and it enforces separation of duties: the submitting user must
        not be the user recorded in `filed_by_user_id`, and a self-submission is
        refused with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

        Design: Difficulty/priority_pair_validation_conflict/incident_self_submit_reports_duties_before_state
        """
        ctx = _report_submitted_by_another_officer()

        validate_error(
            api.incident_transition(
                ctx["ir"],
                {"action": "SUBMIT_MUNICIPAL", "municipal_case_ref": "SF-2026-0803"},
                OFFICER,
            ),
            "ERR_SEGREGATION_OF_DUTIES",
        )

        report = read_incident(ctx["ir"])
        assert report["report_state"] == "SUBMITTED_MUNICIPAL"
        assert report["municipal_case_ref"] == "SF-2026-0802"

    def test_a_third_officers_duplicate_submission_reports_the_state_failure(self, api):
        """PRD §2.10: "The state band then evaluates, in order: whether the
        requested action is a declared transition out of the target row's
        current state; whether the zone permits operations; whether the
        merchant's integration is active; whether the named robot's duty state
        admits dispatch; whether its health state admits dispatch; whether every
        segment of a plan is approved; whether any segment of a plan is blocked;
        whether the mission is already terminal; whether a reservation is live
        enough for the requested transition; whether an open takeover blocks a
        handoff; whether a remedy has already been issued; and whether the order
        has a latched exception at all."
        PRD §3.9: "Submission is a `SafetyOfficer` action carrying the report
        from `DRAFT` to `SUBMITTED_MUNICIPAL`."
        PRD §3.9: "Submission also latches `reviewed_by_user_id` to the
        submitting user."

        Design: Difficulty/priority_pair_validation_conflict/incident_self_submit_reports_duties_before_state
        """
        ctx = _report_submitted_by_another_officer()

        validate_error(
            api.incident_transition(
                ctx["ir"],
                {"action": "SUBMIT_MUNICIPAL", "municipal_case_ref": "SF-2026-0804"},
                make_safety_officer_headers("so-3"),
            ),
            "ERR_INVALID_STATE_TRANSITION",
        )

        report = read_incident(ctx["ir"])
        assert report["report_state"] == "SUBMITTED_MUNICIPAL"
        assert report["reviewed_by_user_id"] == "so-2"
