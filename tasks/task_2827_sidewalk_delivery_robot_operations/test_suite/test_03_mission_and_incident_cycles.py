"""State machines that are cyclic, parallel or branch-and-join.

The mission machine returns to a state it already left, the robot advances two
dimensions at once, and the incident machine converges two asymmetric branches
on one terminal state.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OFFICER,
    OPERATOR,
    add_segment,
    health_action,
    incident_action,
    file_incident,
    mission_action,
    read_incident,
    read_mission,
    read_order,
    read_plan,
    read_robot,
    read_zone,
    set_clock,
    setup_en_route_mission,
    submit_route_plan,
    validate_and_activate_plan,
    validate_error,
    validate_paginated,
)

ALTERNATE_SEGMENT = {
    "segment_type": "WALKWAY",
    "length_m": 300.0,
    "measured_clearance_cm": 110.0,
    "surface_grade_pct": 3.5,
    "sightline_m": 32.0,
    "pedestrian_flow_per_min": 8.0,
    "curb_ramp_present": True,
}


def _mission_with_alternate_segment() -> dict:
    """En-route mission in a zone that also holds the bypass segment S6, which
    is adjacent to both S2 and S5."""
    ctx = setup_en_route_mission()
    s6 = add_segment(
        ctx["z"],
        "S6",
        [ctx["s2"], ctx["s5"]],
        **ALTERNATE_SEGMENT,
    )
    ctx["segments"]["S6"] = s6
    ctx["s6"] = s6["id"]
    return ctx


def _blocked_mission_with_bypass() -> dict:
    """The mission is stopped on S3 at 09:00 and the clock then stands at
    09:06, six whole minutes into the blockage."""
    ctx = _mission_with_alternate_segment()
    ctx["mission"] = mission_action(
        ctx["mi"], "REPORT_BLOCKAGE", headers=OPERATOR, blocking_segment_id=ctx["s3"]
    )
    set_clock("2026-08-03T09:06:00.000Z")
    return ctx


def _rerouted_mission() -> dict:
    """A validated and activated replacement route around the blockage."""
    ctx = _blocked_mission_with_bypass()
    plan_two = submit_route_plan(
        ctx["mission"], [ctx["s1"], ctx["s2"], ctx["s6"], ctx["s5"]]
    )
    ctx["plan_two"] = validate_and_activate_plan(plan_two["id"])
    ctx["p2"] = plan_two["id"]
    return ctx


class TestMissionRerouteCycle:
    def test_a_reported_blockage_supersedes_the_route_but_not_the_delivery(self, api):
        """PRD §3.7: "The reported segment is stored, `blocked_at_utc` is
        stamped, the active plan moves to `SUPERSEDED` with `rejection_reason`
        `SEGMENT_BLOCKED` and `active_route_plan_id` is cleared to null."
        PRD §3.7: "The order deliberately stays in `IN_TRANSIT`: an
        operator-reported blockage is a rerouting event, not a delivery failure,
        which is the sharpest contrast with the closure cascade of §3.2, where
        the identical mission transition does push the order into `EXCEPTION`."

        Design: Difficulty/non_linear_state_machine/mission_reroute_cycle_returns_to_en_route
        """
        ctx = _mission_with_alternate_segment()

        mission = mission_action(
            ctx["mi"], "REPORT_BLOCKAGE", headers=OPERATOR, blocking_segment_id=ctx["s3"]
        )

        plan_one = read_plan(ctx["p"])
        assert mission["mission_state"] == "BLOCKED"
        assert mission["active_route_plan_id"] is None
        assert plan_one["plan_state"] == "SUPERSEDED"
        assert plan_one["rejection_reason"] == "SEGMENT_BLOCKED"
        assert read_order(ctx["o"])["order_state"] == "IN_TRANSIT"

    def test_the_replacement_plan_is_the_next_revision_of_the_same_mission(self, api):
        """PRD §3.6: "`revision_index` is the one-based ordinal of this plan
        among the plans of the same mission ordered by `created_at` ascending,
        so a mission's first plan carries `revision_index` 1 and its first
        replacement carries 2."
        PRD §3.6: "`total_length_m` is the sum of `length_m` over the sequence
        in the given order, carried to one decimal place."
        PRD §3.6: "`planned_duration_min` converts the haul into whole minutes
        at a derated speed: the robot's `max_speed_cm_s` multiplied by 0.6 gives
        an effective travel rate in metres per minute, since a rate expressed in
        centimetres per second multiplied by 0.6 is the same rate expressed in
        metres per minute, and `total_length_m` divided by that rate is rounded
        up to the next whole minute — always up, even when the division is exact
        to a fraction of a minute."

        Design: Difficulty/non_linear_state_machine/mission_reroute_cycle_returns_to_en_route
        """
        ctx = _rerouted_mission()

        plan_two = read_plan(ctx["p2"])
        assert plan_two["revision_index"] == 2
        assert plan_two["total_length_m"] == 814.0
        assert plan_two["planned_duration_min"] == 10
        assert plan_two["plan_state"] == "ACTIVE"

    def test_resuming_banks_the_blocked_minutes_and_keeps_accumulating_the_haul(self, api):
        """PRD §3.7: "On success `blocking_segment_id` is cleared, the blocked
        time is banked — the whole minutes elapsed from `blocked_at_utc` to the
        current instant, discarding any partial minute, are added to
        `blocked_minutes` — and `blocked_at_utc` is cleared to null."
        PRD §3.7: "The replacement plan's `total_length_m` and `crossing_count`
        are then added to the mission's accumulators on top of what the
        superseded plan already contributed, because the robot really did travel
        both."

        Design: Difficulty/non_linear_state_machine/mission_reroute_cycle_returns_to_en_route
        """
        ctx = _rerouted_mission()

        mission = mission_action(ctx["mi"], "RESUME", headers=OPERATOR)

        assert mission["mission_state"] == "EN_ROUTE"
        assert mission["blocking_segment_id"] is None
        assert mission["active_route_plan_id"] == ctx["p2"]
        assert mission["blocked_minutes"] == 6
        assert mission["traveled_distance_m"] == 1588.0
        assert mission["traversed_crossing_count"] == 2
        assert read_order(ctx["o"])["order_state"] == "IN_TRANSIT"


class TestRobotParallelStateDimensions:
    def test_two_health_transitions_leave_the_duty_dimension_untouched(self, api):
        """PRD §3.4: "Every robot carries two independent state dimensions on
        the same row, and they advance in parallel rather than in sequence."
        PRD §3.4: "Neither dimension is a stage of the other: a robot can be
        `DEGRADED` while `ON_MISSION`, or `NOMINAL` while `RETIRED`."

        Design: Difficulty/non_linear_state_machine/robot_parallel_dimensions_move_independently
        """
        ctx = setup_en_route_mission()

        health_action(ctx["r"], "DOWNGRADE", reason="wheel slip on wet concrete")
        robot = health_action(ctx["r"], "IMPAIR", reason="lidar return degraded")

        assert robot["health_state"] == "IMPAIRED"
        assert robot["duty_state"] == "ON_MISSION"
        assert robot["active_mission_id"] == ctx["mi"]
        assert read_mission(ctx["mi"])["mission_state"] == "EN_ROUTE"

    def test_completion_moves_only_the_duty_dimension_back_to_available(self, api):
        """PRD §3.4: "Only one interaction crosses the two dimensions, the
        quarantine cascade, and it runs in one direction only — a health
        transition can force a duty transition, while a duty transition never
        changes `health_state`."
        PRD §3.7: "Finally the robot returns from `ON_MISSION` to `AVAILABLE`,
        its `active_mission_id` is cleared, the zone's `on_mission_robot_count`
        is decremented, and the robot's history absorbs the mission:
        `lifetime_mission_count` advances by one, `lifetime_intervention_count`
        by the mission's `intervention_count`, `lifetime_escalation_count` by
        its `escalation_count`, and `clean_mission_count` by one only when the
        mission recorded no interventions at all, after which both autonomy
        index variants of §3.5 are recomputed."

        Design: Difficulty/non_linear_state_machine/robot_parallel_dimensions_move_independently
        """
        ctx = setup_en_route_mission()
        health_action(ctx["r"], "DOWNGRADE", reason="wheel slip on wet concrete")
        health_action(ctx["r"], "IMPAIR", reason="lidar return degraded")

        mission_action(ctx["mi"], "ARRIVE")
        mission = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        robot = read_robot(ctx["r"])
        assert robot["duty_state"] == "AVAILABLE"
        assert robot["health_state"] == "IMPAIRED"
        assert robot["active_mission_id"] is None
        assert mission["mission_state"] == "COMPLETED"
        assert read_order(ctx["o"])["order_state"] == "DELIVERED"

    def test_an_impaired_but_available_robot_is_outside_the_eligible_pool(self, api):
        """PRD §3.6: "Its `health_state` must be `NOMINAL` or `DEGRADED`, or the
        dispatch is refused with `ERR_ROBOT_HEALTH_BLOCKED` (HTTP 409)."
        PRD §3.6: "The robot list endpoint accepts `eligible_only`, and when
        that flag is true the list is narrowed to the eligible pool and ordered
        by `rolling_autonomy_index` descending, then `battery_pct` descending,
        then `created_at` ascending; the `id` is never consulted for ordering,
        even as a last-resort tie-break."

        Design: Difficulty/non_linear_state_machine/robot_parallel_dimensions_move_independently
        """
        ctx = setup_en_route_mission()
        health_action(ctx["r"], "DOWNGRADE", reason="wheel slip on wet concrete")
        health_action(ctx["r"], "IMPAIR", reason="lidar return degraded")
        mission_action(ctx["mi"], "ARRIVE")
        mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        rows, _meta = validate_paginated(
            api.list_robots(DISPATCHER, {"zone_id": ctx["z"], "eligible_only": "true"})
        )

        assert rows == []
        assert read_robot(ctx["r"])["duty_state"] == "AVAILABLE"


def _submitted_notifiable_incident() -> dict:
    """A serious incident with 30000 cents of damage, filed by the operator and
    submitted by an officer who is not the filer."""
    ctx = setup_en_route_mission()
    report = file_incident(
        ctx["z"],
        ctx["r"],
        headers=OPERATOR,
        category="PEDESTRIAN_CONTACT",
        severity="SERIOUS",
        narrative="robot clipped a planter and a pedestrian tripped",
        estimated_damage_cents=30000,
    )
    ctx["report"] = incident_action(
        report["id"], "SUBMIT_MUNICIPAL", headers=OFFICER, municipal_case_ref="SF-2026-0801"
    )
    ctx["ir"] = report["id"]
    return ctx


class TestIncidentBranchJoin:
    def test_closing_a_notifiable_report_is_refused_before_the_insurer_leg(self, api):
        """PRD §3.9: "The `CLOSE` action then converges both branches on the
        terminal `CLOSED`: it is always available from `INSURER_NOTIFIED`, and
        it is available from `SUBMITTED_MUNICIPAL` only when
        `insurer_notification_required` is false, so closing a notifiable report
        before the insurer has been told is refused with
        `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.9: "`insurer_notification_required` is true when the `severity`
        is `CRITICAL`, or when `estimated_damage_cents` is at or above the
        zone's `insurer_notify_threshold_cents`; the damage comparison is
        inclusive, so with the default threshold of 25000 cents a damage
        estimate of exactly 25000 does require the insurer branch."
        PRD §3.9: "`municipal_due_by_utc` is the filing deadline and applies
        only to reports that the municipality must see: for a `SERIOUS` or
        `CRITICAL` report it is the report's `created_at` advanced by the fixed
        platform constant of 72 filing hours, and for a `MINOR` report it is
        null."

        Design: Difficulty/non_linear_state_machine/incident_branch_join_requires_insurer_leg
        """
        ctx = _submitted_notifiable_incident()

        validate_error(
            api.incident_transition(ctx["ir"], {"action": "CLOSE"}, OFFICER),
            "ERR_INVALID_STATE_TRANSITION",
        )

        report = read_incident(ctx["ir"])
        assert report["report_state"] == "SUBMITTED_MUNICIPAL"
        assert report["insurer_notification_required"] is True
        assert report["municipal_due_by_utc"] == "2026-08-06T09:00:00.000Z"

    def test_the_insurer_branch_reaches_closed_and_clears_the_zone_counter(self, api):
        """PRD §3.9: "When `insurer_notification_required` is true, the officer
        must take the `NOTIFY_INSURER` action, which requires a non-empty
        `insurer_claim_ref` and carries the report to `INSURER_NOTIFIED`; that
        action on a report whose flag is false is refused with
        `ERR_INVALID_STATE_TRANSITION`, because a report below the insurer gate
        has no such branch."
        PRD §3.9: "Closing decrements the zone's `open_incident_count` by one
        and advances the zone's `version`."
        PRD §3.9: "Submission also latches `reviewed_by_user_id` to the
        submitting user."

        Design: Difficulty/non_linear_state_machine/incident_branch_join_requires_insurer_leg
        """
        ctx = _submitted_notifiable_incident()

        notified = incident_action(
            ctx["ir"], "NOTIFY_INSURER", headers=OFFICER, insurer_claim_ref="CLM-88123"
        )
        closed = incident_action(ctx["ir"], "CLOSE", headers=OFFICER)

        assert notified["report_state"] == "INSURER_NOTIFIED"
        assert notified["insurer_claim_ref"] == "CLM-88123"
        assert closed["report_state"] == "CLOSED"
        assert closed["reviewed_by_user_id"] == OFFICER["X-User-ID"]
        assert read_zone(ctx["z"], ADMIN)["open_incident_count"] == 0
