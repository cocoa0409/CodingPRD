"""Transitive cascades: one write, many rows, each link caused by the previous.

Neither trigger names the order, the merchant or the incident it ends up
touching, so the tests walk the chain link by link from the row that was asked
for to the rows that were not.
"""
from test_helpers import (
    ADMIN,
    activate_closure,
    add_closure,
    read_merchant,
    read_mission,
    read_order,
    read_plan,
    read_robot,
    read_segment,
    read_zone,
    setup_en_route_mission,
    setup_quarantined_robot,
    validate_paginated,
)

WEATHER_CLOSURE = {
    "closure_kind": "HARD",
    "cause": "WEATHER",
    "starts_at_utc": "2026-08-03T08:00:00.000Z",
    "ends_at_utc": "2026-08-03T12:00:00.000Z",
}


def _activated_hard_closure_on_the_route() -> dict:
    """A hard weather closure over S3 is activated while the mission is running
    on a plan that contains S3."""
    ctx = setup_en_route_mission()
    closure = add_closure(ctx["s3"], **WEATHER_CLOSURE)
    ctx["closure"] = activate_closure(closure["id"])
    ctx["cl"] = closure["id"]
    return ctx


class TestHardClosureCascade:
    def test_activation_blocks_the_segment_and_supersedes_the_active_plan(self, api):
        """PRD §3.2: "The first link sets the closure's own `state` to `ACTIVE`."
        PRD §3.2: "The second link fires only when `closure_kind` is `HARD`: the
        segment moves from `APPROVED` to `BLOCKED` and its
        `blocked_by_closure_id` is pointed at the activating closure."
        PRD §3.2: "The third link is caused by the second: every route plan
        whose `plan_state` is `ACTIVE` and whose sequence contains the newly
        blocked segment is driven to `SUPERSEDED` with `rejection_reason`
        `SEGMENT_BLOCKED`, processed in `created_at` ascending order, and the
        closure's `reroute_triggered_count` advances by one for each plan it
        superseded."

        Design: Difficulty/transitive_cascade/hard_closure_activation_cascades_five_levels
        """
        ctx = _activated_hard_closure_on_the_route()

        closure = ctx["closure"]
        segment = read_segment(ctx["s3"])
        plan = read_plan(ctx["p"])
        assert closure["state"] == "ACTIVE"
        assert closure["reroute_triggered_count"] == 1
        assert segment["status"] == "BLOCKED"
        assert segment["blocked_by_closure_id"] == ctx["cl"]
        assert plan["plan_state"] == "SUPERSEDED"
        assert plan["rejection_reason"] == "SEGMENT_BLOCKED"

    def test_the_superseded_plan_stops_its_mission_and_stamps_the_instant(self, api):
        """PRD §3.2: "The fourth link is caused by the third: each superseded
        plan's mission, if its `mission_state` is `EN_ROUTE`, moves to
        `BLOCKED`, records the closed segment in `blocking_segment_id`, stamps
        `blocked_at_utc` with the current instant, and has its
        `active_route_plan_id` cleared to null."

        Design: Difficulty/transitive_cascade/hard_closure_activation_cascades_five_levels
        """
        ctx = _activated_hard_closure_on_the_route()

        mission = read_mission(ctx["mi"])
        assert mission["mission_state"] == "BLOCKED"
        assert mission["blocking_segment_id"] == ctx["s3"]
        assert mission["active_route_plan_id"] is None
        assert mission["blocked_at_utc"] == "2026-08-03T09:00:00.000Z"

    def test_the_order_latches_the_closure_cause_and_the_escrow_is_released(self, api):
        """PRD §3.2: "The fifth link is caused by the fourth: each newly blocked
        mission's delivery order, if its `order_state` is `IN_TRANSIT`, moves to
        `EXCEPTION` with `exception_reason` derived from the closure's `cause` —
        a `WEATHER` cause latches `WEATHER`, a `VANDALISM` cause latches
        `VANDALISM`, and both `CONSTRUCTION` and `EVENT` latch `BLOCKED_ROUTE`."
        PRD §3.2: "For each such order the quoted amount leaves the merchant's
        `escrowed_fee_cents` and enters its `released_fee_cents`, and the
        merchant's `exception_count` advances by one."

        Design: Difficulty/transitive_cascade/hard_closure_activation_cascades_five_levels
        """
        ctx = _activated_hard_closure_on_the_route()

        order = read_order(ctx["o"])
        merchant = read_merchant(ctx["m"])
        assert order["order_state"] == "EXCEPTION"
        assert order["exception_reason"] == "WEATHER"
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["released_fee_cents"] == 850
        assert merchant["recognized_fee_cents"] == 0
        assert merchant["exception_count"] == 1

    def test_only_the_closed_segment_of_the_route_is_touched(self, api):
        """PRD §3.2: "An advisory activation stops after the first link, leaving
        the segment's `status` untouched and no further link firing at all."
        PRD §3.2: "The second link fires only when `closure_kind` is `HARD`: the
        segment moves from `APPROVED` to `BLOCKED` and its
        `blocked_by_closure_id` is pointed at the activating closure."

        Design: Difficulty/transitive_cascade/hard_closure_activation_cascades_five_levels
        """
        ctx = _activated_hard_closure_on_the_route()

        assert read_segment(ctx["s1"])["status"] == "APPROVED"
        assert read_segment(ctx["s5"])["status"] == "APPROVED"
        assert read_segment(ctx["s1"])["blocked_by_closure_id"] is None
        assert read_segment(ctx["s5"])["blocked_by_closure_id"] is None


class TestTamperQuarantineCascade:
    def test_a_tamper_frame_quarantines_the_robot_and_parks_it_in_maintenance(self, api):
        """PRD §3.5: "A frame reporting `tamper_flag` true drives the robot to
        `QUARANTINED` from whatever health state it was in and latches
        `tamper_flag` true on the row, with the full cascade below."
        PRD §3.5: "The second link fires only when the robot's `duty_state` is
        `ON_MISSION`: the robot moves from `ON_MISSION` to `MAINTENANCE` rather
        than to `AVAILABLE`, its `active_mission_id` is cleared to null, the
        mission that pointer named is driven to the terminal `ABORTED` with
        `abort_reason` `ROBOT_QUARANTINED`, and the zone's
        `on_mission_robot_count` is decremented by one."

        Design: Difficulty/transitive_cascade/tamper_telemetry_quarantine_cascades_four_levels
        """
        ctx = setup_quarantined_robot()

        robot = read_robot(ctx["r"])
        mission = read_mission(ctx["mi"])
        assert robot["health_state"] == "QUARANTINED"
        assert robot["tamper_flag"] is True
        assert robot["duty_state"] == "MAINTENANCE"
        assert robot["active_mission_id"] is None
        assert mission["mission_state"] == "ABORTED"
        assert mission["abort_reason"] == "ROBOT_QUARANTINED"
        assert read_zone(ctx["z"], ADMIN)["on_mission_robot_count"] == 0

    def test_the_aborted_mission_rejects_its_plan_and_excepts_its_order(self, api):
        """PRD §3.6: "The two system exits are the ones described elsewhere: a
        plan is driven to `SUPERSEDED` with `SEGMENT_BLOCKED` when a hard
        closure covers one of its segments or when an operator reports a
        blockage, and a plan of any non-terminal state is driven to `REJECTED`
        with `OPERATOR_REJECTED` when its mission is aborted."
        PRD §3.5: "The third link is caused by the second and acts on that
        mission's delivery order: `order_state` becomes `EXCEPTION`,
        `exception_reason` becomes `VANDALISM` when the robot's `tamper_flag`
        now stands true and `ROBOT_FAULT` when it stands false, the order's
        quoted amount moves out of the merchant's `escrowed_fee_cents` and into
        its `released_fee_cents`, and the merchant's `exception_count` advances
        by one."

        Design: Difficulty/transitive_cascade/tamper_telemetry_quarantine_cascades_four_levels
        """
        ctx = setup_quarantined_robot()

        plan = read_plan(ctx["p"])
        order = read_order(ctx["o"])
        merchant = read_merchant(ctx["m"])
        assert plan["plan_state"] == "REJECTED"
        assert order["order_state"] == "EXCEPTION"
        assert order["exception_reason"] == "VANDALISM"
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["released_fee_cents"] == 850
        assert merchant["exception_count"] == 1

    def test_the_cascade_files_exactly_one_system_owned_incident_draft(self, api):
        """PRD §3.5: "The same link also files an incident automatically: a new
        `IncidentReport` is created in `report_state` `DRAFT` with `category`
        `VANDALISM`, `severity` `SERIOUS`, `filed_by_user_id` set to the literal
        string `SYSTEM`, `zone_id` copied from the robot, `mission_id` set to
        the aborted mission, `robot_id` set to this robot and
        `estimated_damage_cents` at 0."
        PRD §3.5: "The fourth link is caused by the third and advances the
        zone's `open_incident_count` by one along with the zone's `version`."

        Design: Difficulty/transitive_cascade/tamper_telemetry_quarantine_cascades_four_levels
        """
        ctx = setup_quarantined_robot()

        rows, _meta = validate_paginated(
            api.list_incident_reports(ADMIN, {"robot_id": ctx["r"], "report_state": "DRAFT"})
        )

        assert len(rows) == 1
        assert rows[0]["filed_by_user_id"] == "SYSTEM"
        assert rows[0]["category"] == "VANDALISM"
        assert rows[0]["severity"] == "SERIOUS"
        assert rows[0]["estimated_damage_cents"] == 0
        assert rows[0]["mission_id"] == ctx["mi"]
        assert read_zone(ctx["z"], ADMIN)["open_incident_count"] == 1
