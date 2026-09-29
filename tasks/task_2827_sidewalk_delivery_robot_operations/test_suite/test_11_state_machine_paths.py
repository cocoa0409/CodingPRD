"""Declared edges, refused edges and the side effects an accepted edge carries.

Every refusal here is paired with the same call succeeding one step later, so a
409 can never be explained by an unimplemented action; and every acceptance
checks the rows the transition is declared to touch as well as the row it was
aimed at.
"""
from test_helpers import (
    ADMIN,
    BASE_CLOCK_UTC,
    DISPATCHER,
    OPERATOR,
    SUPPORT,
    abort_mission,
    add_order,
    add_robot,
    add_segment,
    approve_segment,
    create_robot_payload,
    create_segment_closure_payload,
    create_service_zone_payload,
    dispatch_mission,
    duty_action,
    duty_transition_payload,
    file_incident,
    integration_transition_payload,
    mission_transition_payload,
    open_intervention,
    permit_transition_payload,
    plan_transition_payload,
    read_bay,
    read_merchant,
    read_mission,
    read_order,
    read_plan,
    read_reservation,
    read_robot,
    read_segment,
    read_zone,
    remedy_payload,
    reservation_action,
    reservation_transition_payload,
    segment_transition_payload,
    set_clock,
    setup_active_merchant,
    setup_active_route_plan,
    setup_approved_segment,
    setup_available_robot,
    setup_charge_bay_reservation,
    setup_completed_delivery,
    setup_en_route_mission,
    setup_mapped_segment,
    setup_permitted_zone,
    setup_planned_mission,
    submit_route_plan,
    survey_segment,
    validate_error,
    validate_paginated,
    validate_plan,
    validate_success,
)

CHARGE_WINDOW = {
    "window_start_utc": "2026-08-03T10:00:00.000Z",
    "window_end_utc": "2026-08-03T11:00:00.000Z",
}
WINDOW_OPEN_CLOCK_UTC = "2026-08-03T10:00:00.000Z"
S6 = {
    "segment_type": "WALKWAY",
    "length_m": 300.0,
    "measured_clearance_cm": 110.0,
    "surface_grade_pct": 3.5,
    "sightline_m": 32.0,
    "pedestrian_flow_per_min": 8.0,
    "curb_ramp_present": True,
}


class TestZonePermitMachine:
    def test_activate_permit_is_the_declared_edge_out_of_provisioned(self, api):
        """PRD §3.1: "The `ACTIVATE_PERMIT` step carries the zone from
        `PROVISIONED` to `PERMITTED`, and it requires that at least one segment in
        the zone has already reached `APPROVED` — a zone whose network has been
        mapped but never approved cannot be permitted, and the attempt is refused
        with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.1: "Activation also clears `restriction_reason` back to null."
        PRD §3.1: "Each of these three steps advances the zone's `version` by
        one."

        Design: Corner/state_machines/zone_activate_permit_is_the_declared_valid_transition
        """
        ctx = setup_approved_segment()
        assert read_zone(ctx["z"])["permit_state"] == "PROVISIONED"

        permitted = validate_success(
            api.zone_permit_transition(
                ctx["z"], permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
            )
        )

        assert permitted["permit_state"] == "PERMITTED"
        assert permitted["restriction_reason"] is None
        assert permitted["version"] == 2
        assert permitted["remedy_spent_cents"] == 0
        assert permitted["reserved_bay_minutes"] == 0
        assert permitted["on_mission_robot_count"] == 0
        assert permitted["lid_code_sequence"] == 0

        _zones, meta = validate_paginated(
            api.list_service_zones(ADMIN, {"permit_state": "PERMITTED"})
        )
        assert meta["total_count"] == 1

    def test_the_permit_needs_one_approved_segment_not_merely_a_surveyed_one(self, api):
        """PRD §3.1: "The `ACTIVATE_PERMIT` step carries the zone from
        `PROVISIONED` to `PERMITTED`, and it requires that at least one segment in
        the zone has already reached `APPROVED` — a zone whose network has been
        mapped but never approved cannot be permitted, and the attempt is refused
        with `ERR_INVALID_STATE_TRANSITION`."
        PRD §3.1: "Approval is the gate that admits a segment to routing, moving
        `status` from `SURVEYED` to `APPROVED`, and it enforces exactly two
        compliance findings."

        Design: Corner/state_machines/zone_permit_requires_at_least_one_approved_segment
        """
        ctx = setup_mapped_segment()
        survey_segment(ctx["s1"])

        validate_error(
            api.zone_permit_transition(
                ctx["z"], permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        refused_zone = read_zone(ctx["z"])
        assert refused_zone["permit_state"] == "PROVISIONED"
        assert refused_zone["version"] == 1

        approved = approve_segment(ctx["s1"])
        permitted = validate_success(
            api.zone_permit_transition(
                ctx["z"], permit_transition_payload("ACTIVATE_PERMIT"), ADMIN
            )
        )

        assert approved["status"] == "APPROVED"
        assert permitted["permit_state"] == "PERMITTED"
        assert permitted["version"] == 2


class TestRefusedEdgesOnConfigurationMachines:
    def test_retire_and_approve_out_of_mapped_are_both_refused(self, api):
        """PRD §3.1: "Surveying is the act that turns a mapped element into a
        scored one, moving `status` from `MAPPED` to `SURVEYED`."
        PRD §3.1: "Retirement removes an element from service permanently and is
        available from either `SURVEYED` or `APPROVED`."
        PRD §2.10: "The state band then evaluates, in order: whether the requested
        action is a declared transition out of the target row's current state;
        whether the zone permits operations; whether the merchant's integration is
        active; whether the named robot's duty state admits dispatch; whether its
        health state admits dispatch; whether every segment of a plan is approved;
        whether any segment of a plan is blocked; whether the mission is already
        terminal; whether a reservation is live enough for the requested
        transition; whether an open takeover blocks a handoff; whether a remedy has
        already been issued; and whether the order has a latched exception at all."

        Design: Corner/state_machines/segment_retire_and_approve_from_mapped_are_invalid
        """
        ctx = setup_mapped_segment()

        validate_error(
            api.segment_transition(ctx["s1"], segment_transition_payload("RETIRE"), ADMIN),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        validate_error(
            api.segment_transition(ctx["s1"], segment_transition_payload("APPROVE"), ADMIN),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        refused = read_segment(ctx["s1"])
        assert refused["status"] == "MAPPED"
        assert refused["version"] == 1

        surveyed = survey_segment(ctx["s1"])
        retired = validate_success(
            api.segment_transition(ctx["s1"], segment_transition_payload("RETIRE"), ADMIN)
        )

        assert surveyed["status"] == "SURVEYED"
        assert retired["status"] == "RETIRED"
        assert retired["version"] == 3

    def test_the_duty_cycle_admits_no_shortcut_and_no_replay(self, api):
        """PRD §3.4: "The duty cycle begins when a dispatcher stages an `OFFLINE`
        robot with the `STAGE` action, which carries it to `STAGING`."
        PRD §3.4: "The `MAKE_AVAILABLE` action then carries the robot from
        `STAGING` to `AVAILABLE`, and here the health gate tightens: `health_state`
        must be `NOMINAL` or `DEGRADED`, so an `IMPAIRED` robot may be staged but
        may not be made available, and `battery_pct` must be at least 35.0 percent,
        inclusive at that boundary."
        PRD §3.4: "Only one interaction crosses the two dimensions, the quarantine
        cascade, and it runs in one direction only — a health transition can force
        a duty transition, while a duty transition never changes `health_state`."

        Design: Corner/state_machines/duty_make_available_from_offline_is_invalid
        """
        ctx = setup_permitted_zone()
        robot = add_robot(ctx["z"], asset_tag="RBT-001", stage=False, make_available=False)
        assert robot["duty_state"] == "OFFLINE"

        validate_error(
            api.robot_duty_transition(
                robot["id"], duty_transition_payload("MAKE_AVAILABLE"), DISPATCHER
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        assert read_robot(robot["id"])["duty_state"] == "OFFLINE"

        staged = duty_action(robot["id"], "STAGE")
        available = duty_action(robot["id"], "MAKE_AVAILABLE")
        validate_error(
            api.robot_duty_transition(
                robot["id"], duty_transition_payload("STAGE"), DISPATCHER
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        final = read_robot(robot["id"])
        assert staged["duty_state"] == "STAGING"
        assert available["duty_state"] == "AVAILABLE"
        assert final["duty_state"] == "AVAILABLE"
        assert final["health_state"] == "NOMINAL"
        assert final["version"] == 3

    def test_a_replayed_activate_is_refused_while_reinstate_is_the_way_back(self, api):
        """PRD §3.3: "Activation carries the merchant from `PENDING` to `ACTIVE`
        and requires the merchant's zone to be in `permit_state` `PERMITTED`; a
        merchant in a `PROVISIONED`, `RESTRICTED` or `REVOKED` zone cannot be
        activated and the attempt is refused with `ERR_ZONE_NOT_PERMITTED`."
        PRD §3.3: "Suspension carries the merchant from `ACTIVE` to `SUSPENDED`; it
        has no effect on orders that already exist, and only new order intake is
        refused, with `ERR_MERCHANT_NOT_ACTIVE`."
        PRD §3.3: "Reinstatement carries the merchant from `SUSPENDED` back to
        `ACTIVE` and, like activation, requires the zone to be `PERMITTED`."
        PRD §3.3: "Each transition advances the merchant's `version` by one."

        Design: Corner/state_machines/merchant_activate_replayed_is_refused_not_absorbed
        """
        ctx = setup_active_merchant()
        assert read_merchant(ctx["m"])["version"] == 2

        validate_error(
            api.merchant_integration_transition(
                ctx["m"], integration_transition_payload("ACTIVATE"), ADMIN
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        after_replay = read_merchant(ctx["m"])
        assert after_replay["integration_state"] == "ACTIVE"
        assert after_replay["version"] == 2

        suspended = validate_success(
            api.merchant_integration_transition(
                ctx["m"],
                integration_transition_payload("SUSPEND", reason="annual audit"),
                ADMIN,
            )
        )
        assert suspended["integration_state"] == "SUSPENDED"
        assert suspended["version"] == 3

        validate_error(
            api.merchant_integration_transition(
                ctx["m"], integration_transition_payload("ACTIVATE"), ADMIN
            ),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )
        reinstated = validate_success(
            api.merchant_integration_transition(
                ctx["m"], integration_transition_payload("REINSTATE"), ADMIN
            )
        )

        assert reinstated["integration_state"] == "ACTIVE"
        assert reinstated["version"] == 4
        assert reinstated["escrowed_fee_cents"] == 0
        assert reinstated["exception_count"] == 0


class TestTerminalMissionLock:
    def test_abort_on_a_completed_mission_reports_the_terminal_lock(self, api):
        """PRD §3.7: "Aborting is the other way out. A `FleetDispatcher` may abort
        from `PLANNED`, `LOADED`, `EN_ROUTE` or `BLOCKED` with a `reason_code` of
        either `DISPATCH_CANCELLED` or `UNRECOVERABLE_BLOCKAGE`; an already terminal
        mission is refused with `ERR_MISSION_ALREADY_TERMINAL` (HTTP 409)."
        PRD §3.7: "The mission stamps `completed_at_utc` and computes
        `active_minutes` as the whole minutes elapsed from `departed_at_utc` to
        `completed_at_utc`, discarding any partial minute."
        PRD §3.7: "Finally the robot returns from `ON_MISSION` to `AVAILABLE`, its
        `active_mission_id` is cleared, the zone's `on_mission_robot_count` is
        decremented, and the robot's history absorbs the mission:
        `lifetime_mission_count` advances by one, `lifetime_intervention_count` by
        the mission's `intervention_count`, `lifetime_escalation_count` by its
        `escalation_count`, and `clean_mission_count` by one only when the mission
        recorded no interventions at all, after which both autonomy index variants
        of §3.5 are recomputed."

        Design: Corner/state_machines/mission_actions_after_completed_hit_the_terminal_lock
        """
        ctx = setup_completed_delivery()
        settled_at_completion = ctx["order"]["settled_fee_cents"]
        assert ctx["mission"]["mission_state"] == "COMPLETED"
        assert settled_at_completion is not None

        validate_error(
            api.mission_transition(
                ctx["mi"],
                mission_transition_payload("ABORT", reason_code="DISPATCH_CANCELLED"),
                DISPATCHER,
            ),
            "ERR_MISSION_ALREADY_TERMINAL",
            409,
        )

        mission = read_mission(ctx["mi"])
        order = read_order(ctx["o"])
        robot = read_robot(ctx["r"])
        assert mission["mission_state"] == "COMPLETED"
        assert mission["abort_reason"] is None
        assert mission["active_minutes"] == 12
        assert mission["blocking_segment_id"] is None
        assert order["order_state"] == "DELIVERED"
        assert order["settled_fee_cents"] == settled_at_completion
        assert robot["duty_state"] == "AVAILABLE"
        assert robot["lifetime_mission_count"] == 1
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 0


class TestDeclaredInitialStates:
    def test_every_configuration_machine_stamps_its_own_first_state(self, api):
        """PRD §3.1: "A `PlatformAdmin` provisions the zone first, with the
        ordinance terms and planning assumptions described in §2.7; the zone lands
        in `permit_state` `PROVISIONED`, every derived ledger at zero,
        `remedy_budget_remaining_cents` equal to the authorised
        `remedy_budget_cents`, `lid_code_sequence` at zero and `restriction_reason`
        null."
        PRD §3.1: "A newly mapped element sits in `status` `MAPPED` with
        `crossing_risk_score` still null and `blocked_by_closure_id` null."
        PRD §3.2: "A new closure lands in `state` `SCHEDULED` with
        `reroute_triggered_count` at zero."
        PRD §3.3: "A new merchant lands in `integration_state` `PENDING` with
        `escrowed_fee_cents`, `recognized_fee_cents`, `released_fee_cents`,
        `settlement_variance_cents` and `exception_count` all at zero, and it cannot
        receive orders in that state."
        PRD §3.4: "A newly registered robot has `duty_state` `OFFLINE`,
        `health_state` `NOMINAL`, `battery_pct` 100.0, `odometer_m` 0.0,
        `yield_event_count` 0, `tamper_flag` false, `lifetime_mission_count`,
        `lifetime_intervention_count`, `lifetime_escalation_count` and
        `clean_mission_count` all zero, both `rolling_autonomy_index` and
        `lifetime_autonomy_index` at 100, and `active_mission_id` and
        `current_bay_reservation_id` both null."
        PRD §3.4: "Depot bays are provisioned separately by a `PlatformAdmin`, who
        supplies the `zone_id` of the zone whose fleet the bay serves, a `bay_code`
        that must be unique within that zone, the `bay_type` of `CHARGE`, `STAGE` or
        `SERVICE`, an optional charger output `power_kw` that must be zero or
        greater and defaults to 0.0, and an optional `state` of `OPEN` or
        `OUT_OF_SERVICE` defaulting to `OPEN`."
        PRD §3.4: "A new bay starts with `committed_minutes` at zero."
        PRD §3.2: "The distinction between the two kinds is total: a `HARD` closure
        blocks the segment and forces reroutes, while an `ADVISORY` closure is
        purely informational and never changes a segment's status."

        Design: Corner/state_machines/configuration_layer_rows_start_in_their_declared_initial_states
        """
        set_clock(BASE_CLOCK_UTC)
        zone = validate_success(
            api.create_service_zone(create_service_zone_payload(), ADMIN), 201
        )
        segment = validate_success(
            api.create_sidewalk_segment(
                {
                    "zone_id": zone["id"],
                    "segment_code": "S1",
                    "segment_type": "WALKWAY",
                    "length_m": 320.0,
                    "measured_clearance_cm": 118.0,
                    "surface_grade_pct": 3.0,
                },
                ADMIN,
            ),
            201,
        )
        closure = validate_success(
            api.create_segment_closure(
                create_segment_closure_payload(
                    segment["id"],
                    closure_kind="ADVISORY",
                    cause="EVENT",
                    starts_at_utc="2026-08-03T08:00:00.000Z",
                    ends_at_utc="2026-08-03T12:00:00.000Z",
                ),
                ADMIN,
            ),
            201,
        )
        merchant = validate_success(
            api.create_merchant({"zone_id": zone["id"], "name": "Corner Bakery"}, ADMIN), 201
        )
        robot = validate_success(
            api.create_robot(create_robot_payload(zone["id"]), ADMIN), 201
        )
        bay = validate_success(
            api.create_depot_bay(
                {"zone_id": zone["id"], "bay_code": "B1", "bay_type": "CHARGE"}, ADMIN
            ),
            201,
        )

        assert zone["permit_state"] == "PROVISIONED"
        assert zone["version"] == 1
        assert segment["status"] == "MAPPED"
        assert segment["version"] == 1
        assert closure["state"] == "SCHEDULED"
        assert closure["reroute_triggered_count"] == 0
        assert merchant["integration_state"] == "PENDING"
        assert merchant["handoff_sla_seconds"] == 300
        assert merchant["merchant_grade"] == "STANDARD"
        assert robot["duty_state"] == "OFFLINE"
        assert robot["health_state"] == "NOMINAL"
        assert bay["state"] == "OPEN"
        assert bay["power_kw"] == 0.0
        assert bay["committed_minutes"] == 0
        assert read_segment(segment["id"])["status"] == "MAPPED"
        assert read_bay(bay["id"])["state"] == "OPEN"

    def test_every_delivery_machine_starts_one_step_past_its_create(self, api):
        """PRD §3.3: "The order itself lands in `order_state` `RECEIVED`, with
        `settled_fee_cents`, `exception_reason`, `remedy_kind`, `remedy_reason_code`
        and `remedy_amount_cents` all null and `dispatch_attempt_count` at zero."
        PRD §3.6: "A successful dispatch writes four rows. The new mission is
        created in `mission_state` `PLANNED` with `traveled_distance_m`,
        `traversed_crossing_count`, `blocked_minutes`, `intervention_count`,
        `escalation_count` and `active_minutes` all at zero and `lid_access_code`,
        `actual_payload_liters`, `active_route_plan_id`, `blocking_segment_id`,
        `departed_at_utc`, `blocked_at_utc`, `completed_at_utc` and `abort_reason`
        all null, with `handoff_late` false."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order
        that is dispatched a second time shows a count of two."
        PRD §3.6: "Creation is where all the geometry is derived and all the geometry
        gates run; the plan then lands in `plan_state` `DRAFT` and must still be
        validated and activated before the robot may move."
        PRD §3.6: "`revision_index` is the one-based ordinal of this plan among the
        plans of the same mission ordered by `created_at` ascending, so a mission's
        first plan carries `revision_index` 1 and its first replacement carries 2."
        PRD §3.6: "On success the mission's previously `ACTIVE` plan, if there was
        one, moves to `SUPERSEDED` with `rejection_reason` `REPLACED_BY_NEWER`, the
        new plan's `supersedes_plan_id` is pointed at that older plan, and the
        mission's `active_route_plan_id` is repointed at the new plan."
        PRD §3.7: "The event is created in `takeover_state` `REQUESTED`, and one
        value is frozen at that instant: `mandatory` is true when
        `autonomy_confidence_pct` is at or below the zone's
        `takeover_confidence_threshold_pct` and false otherwise."
        PRD §3.9: "`municipal_due_by_utc` is the filing deadline and applies only to
        reports that the municipality must see: for a `SERIOUS` or `CRITICAL` report
        it is the report's `created_at` advanced by the fixed platform constant of
        72 filing hours, and for a `MINOR` report it is null."
        PRD §3.9: "`insurer_notification_required` is true when the `severity` is
        `CRITICAL`, or when `estimated_damage_cents` is at or above the zone's
        `insurer_notify_threshold_cents`; the damage comparison is inclusive, so
        with the default threshold of 25000 cents a damage estimate of exactly 25000
        does require the insurer branch."

        Design: Corner/state_machines/delivery_layer_rows_start_in_their_declared_initial_states
        """
        ctx = setup_available_robot()
        order = add_order(ctx["m"], ctx["s5"])
        assert order["order_state"] == "RECEIVED"
        assert order["dispatch_attempt_count"] == 0

        mission = dispatch_mission(order, ctx["r"])
        plan = submit_route_plan(mission, [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]])
        event = open_intervention(mission["id"], 80, trigger_reason="OBSTACLE")
        report = file_incident(
            ctx["z"],
            ctx["r"],
            category="OBSTRUCTION",
            severity="MINOR",
            narrative="wheelie bin left across the walkway",
        )

        assert mission["mission_state"] == "PLANNED"
        assert mission["lid_access_code"] is None
        assert mission["actual_payload_liters"] is None
        assert mission["handoff_late"] is False
        assert mission["active_route_plan_id"] is None

        dispatched = read_order(order["id"])
        assert dispatched["order_state"] == "DISPATCHED"
        assert dispatched["dispatch_attempt_count"] == 1

        assert plan["plan_state"] == "DRAFT"
        assert plan["revision_index"] == 1
        assert plan["supersedes_plan_id"] is None

        assert event["takeover_state"] == "REQUESTED"
        assert event["mandatory"] is False
        assert event["operator_user_id"] is None
        assert event["control_seconds"] == 0
        assert event["assumed_at_utc"] is None

        assert report["report_state"] == "DRAFT"
        assert report["insurer_notification_required"] is False
        assert report["municipal_due_by_utc"] is None
        assert report["reviewed_by_user_id"] is None
        assert report["filed_by_user_id"] == OPERATOR["X-User-ID"]
        assert read_zone(ctx["z"])["open_incident_count"] == 1


class TestPermitRevocationCascade:
    def test_revocation_aborts_the_live_mission_and_rejects_its_plan(self, api):
        """PRD §3.1: "It requires a `reason`, sets `permit_state` to the terminal
        `REVOKED`, records the reason in `restriction_reason`, and then fans out
        across the zone."
        PRD §3.1: "Every mission whose robot is homed to the zone and whose
        `mission_state` is `PLANNED`, `LOADED`, `EN_ROUTE` or `BLOCKED` is driven to
        `ABORTED` with `abort_reason` `ZONE_REVOKED`, processed in `created_at`
        ascending order."
        PRD §3.7: "The mission moves to the terminal `ABORTED`, `abort_reason`
        records the supplied code, `completed_at_utc` is stamped, and
        `active_minutes` is computed the same way as on completion except that it is
        0 when `departed_at_utc` is null, which is the case for a mission aborted
        before it ever departed."
        PRD §3.7: "The mission stamps `completed_at_utc` and computes
        `active_minutes` as the whole minutes elapsed from `departed_at_utc` to
        `completed_at_utc`, discarding any partial minute."
        PRD §3.7: "Every route plan of that mission whose `plan_state` is `DRAFT`,
        `VALIDATED` or `ACTIVE` moves to `REJECTED` with `rejection_reason`
        `OPERATOR_REJECTED`, processed in `created_at` ascending order."
        PRD §3.7: "The two system-driven aborts described in §3.1 and §3.5 take this
        same path with `abort_reason` `ZONE_REVOKED` or `ROBOT_QUARANTINED`
        respectively, the only difference being that a quarantine parks the robot in
        `MAINTENANCE` instead of returning it to `AVAILABLE`."

        Design: Corner/state_machines/zone_revoke_cascades_into_missions_orders_plans_and_robots
        """
        ctx = setup_en_route_mission()
        assert read_mission(ctx["mi"])["departed_at_utc"] == BASE_CLOCK_UTC

        revoked = validate_success(
            api.zone_permit_transition(
                ctx["z"],
                permit_transition_payload("REVOKE", reason="municipal permit suspended"),
                ADMIN,
            )
        )

        mission = read_mission(ctx["mi"])
        plan = read_plan(ctx["p"])
        assert revoked["permit_state"] == "REVOKED"
        assert revoked["restriction_reason"] == "municipal permit suspended"
        assert mission["mission_state"] == "ABORTED"
        assert mission["abort_reason"] == "ZONE_REVOKED"
        assert mission["completed_at_utc"] == BASE_CLOCK_UTC
        assert mission["active_minutes"] == 0
        assert plan["plan_state"] == "REJECTED"
        assert plan["rejection_reason"] == "OPERATOR_REJECTED"

    def test_revocation_releases_the_escrow_and_hands_the_robot_back(self, api):
        """PRD §3.1: "For each such mission the delivery order moves to `EXCEPTION`
        with `exception_reason` `BLOCKED_ROUTE`, the order's quoted amount leaves the
        merchant's `escrowed_fee_cents` and enters its `released_fee_cents`, and the
        merchant's `exception_count` advances by one."
        PRD §3.1: "Each affected robot then follows its ordinary route out of
        `ON_MISSION` to `AVAILABLE` because its mission reached a terminal state, its
        `active_mission_id` is cleared to null, and the zone's
        `on_mission_robot_count` is decremented once per robot."
        PRD §3.7: "The robot returns from `ON_MISSION` to `AVAILABLE` with exactly
        the same counter and index recomputation as on completion, because an aborted
        mission is a terminal mission and counts against the fleet just as a
        completed one does."
        PRD §3.7: "Finally the robot returns from `ON_MISSION` to `AVAILABLE`, its
        `active_mission_id` is cleared, the zone's `on_mission_robot_count` is
        decremented, and the robot's history absorbs the mission:
        `lifetime_mission_count` advances by one, `lifetime_intervention_count` by
        the mission's `intervention_count`, `lifetime_escalation_count` by its
        `escalation_count`, and `clean_mission_count` by one only when the mission
        recorded no interventions at all, after which both autonomy index variants
        of §3.5 are recomputed."
        PRD §3.5: "Each terminal mission that recorded no intervention at all
        instead contributes a credit of 2 points; a mission with interventions earns
        no credit."
        PRD §3.5: "Both variants start from a base of 100, apply their
        contributions, then clamp the result into the range 40 to 100 and round half
        up to a whole number, with the clamp and the rounding applied only once at
        the end."

        Design: Corner/state_machines/zone_revoke_cascades_into_missions_orders_plans_and_robots
        """
        ctx = setup_en_route_mission()
        quote = ctx["order"]["quoted_fee_cents"]
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == quote
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 1

        validate_success(
            api.zone_permit_transition(
                ctx["z"],
                permit_transition_payload("REVOKE", reason="municipal permit suspended"),
                ADMIN,
            )
        )

        order = read_order(ctx["o"])
        merchant = read_merchant(ctx["m"])
        robot = read_robot(ctx["r"])
        assert order["order_state"] == "EXCEPTION"
        assert order["exception_reason"] == "BLOCKED_ROUTE"
        assert merchant["escrowed_fee_cents"] == 0
        assert merchant["released_fee_cents"] == quote
        assert merchant["recognized_fee_cents"] == 0
        assert merchant["exception_count"] == 1
        assert robot["duty_state"] == "AVAILABLE"
        assert robot["active_mission_id"] is None
        assert robot["health_state"] == "NOMINAL"
        assert robot["lifetime_mission_count"] == 1
        assert robot["clean_mission_count"] == 1
        assert robot["rolling_autonomy_index"] == 100
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 0


class TestPlanSupersession:
    def test_the_replacement_plan_recomputes_its_own_geometry(self, api):
        """PRD §3.6: "`total_length_m` is the sum of `length_m` over the sequence in
        the given order, carried to one decimal place."
        PRD §3.6: "`crossing_count` is the number of elements whose `segment_type` is
        `CROSSING`."
        PRD §3.6: "`clearance_margin_cm` is the accessibility slack of the tightest
        segment for this particular robot: for each segment in the sequence, subtract
        the robot's `width_cm` and then a further ordinance buffer of 12 centimetres
        from that segment's `measured_clearance_cm`, and take the smallest of those
        results, rounded to one decimal place."
        PRD §3.6: "`planned_duration_min` converts the haul into whole minutes at a
        derated speed: the robot's `max_speed_cm_s` multiplied by 0.6 gives an
        effective travel rate in metres per minute, since a rate expressed in
        centimetres per second multiplied by 0.6 is the same rate expressed in metres
        per minute, and `total_length_m` divided by that rate is rounded up to the
        next whole minute — always up, even when the division is exact to a fraction
        of a minute."
        PRD §3.6: "`revision_index` is the one-based ordinal of this plan among the
        plans of the same mission ordered by `created_at` ascending, so a mission's
        first plan carries `revision_index` 1 and its first replacement carries 2."

        Design: Corner/state_machines/plan_activation_supersedes_the_prior_active_plan
        """
        ctx = setup_active_route_plan()
        s6 = add_segment(ctx["z"], "S6", [ctx["s2"], ctx["s5"]], **S6)
        assert ctx["plan"]["revision_index"] == 1

        replacement = submit_route_plan(
            read_mission(ctx["mi"]), [ctx["s1"], ctx["s2"], s6["id"], ctx["s5"]]
        )

        assert replacement["plan_state"] == "DRAFT"
        assert replacement["revision_index"] == 2
        assert replacement["total_length_m"] == 814.0
        assert replacement["crossing_count"] == 1
        assert replacement["planned_duration_min"] == 10
        assert replacement["clearance_margin_cm"] == 2.0
        assert replacement["supersedes_plan_id"] is None

    def test_activating_it_supersedes_the_incumbent_and_repoints_the_mission(self, api):
        """PRD §3.6: "`ACTIVATE` carries a plan from `VALIDATED` to `ACTIVE` and
        requires the mission to be in `PLANNED`, `LOADED` or `BLOCKED` — never
        `EN_ROUTE`, so a route cannot be swapped under a moving robot — and re-checks
        that no segment in the sequence is `BLOCKED`, since a closure may have
        activated between validation and activation."
        PRD §3.6: "On success the mission's previously `ACTIVE` plan, if there was
        one, moves to `SUPERSEDED` with `rejection_reason` `REPLACED_BY_NEWER`, the
        new plan's `supersedes_plan_id` is pointed at that older plan, and the
        mission's `active_route_plan_id` is repointed at the new plan."
        PRD §3.6: "Both `SUPERSEDED` and `REJECTED` are terminal, and route plan
        lists are returned in `revision_index` ascending order so a mission's
        replanning history reads chronologically."
        PRD §3.7: "Departure stamps `departed_at_utc` with the current instant, adds
        the active plan's `total_length_m` to the mission's `traveled_distance_m` and
        its `crossing_count` to `traversed_crossing_count`, and carries the order
        from `DISPATCHED` to `IN_TRANSIT`."

        Design: Corner/state_machines/plan_activation_supersedes_the_prior_active_plan
        """
        ctx = setup_active_route_plan()
        s6 = add_segment(ctx["z"], "S6", [ctx["s2"], ctx["s5"]], **S6)
        replacement = submit_route_plan(
            read_mission(ctx["mi"]), [ctx["s1"], ctx["s2"], s6["id"], ctx["s5"]]
        )
        validate_plan(replacement["id"])

        activated = validate_success(
            api.route_plan_transition(
                replacement["id"], plan_transition_payload("ACTIVATE"), DISPATCHER
            )
        )

        incumbent = read_plan(ctx["p"])
        mission = read_mission(ctx["mi"])
        _rows, meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"], "plan_state": "ACTIVE"})
        )
        assert activated["plan_state"] == "ACTIVE"
        assert activated["supersedes_plan_id"] == ctx["p"]
        assert incumbent["plan_state"] == "SUPERSEDED"
        assert incumbent["rejection_reason"] == "REPLACED_BY_NEWER"
        assert mission["active_route_plan_id"] == replacement["id"]
        assert mission["mission_state"] == "LOADED"
        assert mission["traveled_distance_m"] == 0.0
        assert meta["total_count"] == 1


class TestDepotOccupationMachine:
    def test_begin_charge_waits_for_the_reservation_to_go_active(self, api):
        """PRD §3.4: "The `BEGIN_CHARGE` action carries an `AVAILABLE` robot to
        `CHARGING` and requires a `bay_reservation_id` in the request body naming a
        reservation that exists, is in `state` `ACTIVE`, has `reservation_type`
        `CHARGE` and has a `robot_id` equal to this robot; any of those four
        conditions failing is refused with `ERR_RESERVATION_NOT_ACTIVE` (HTTP 409)."
        PRD §3.4: "On success the robot's `current_bay_reservation_id` is pointed at
        that reservation."
        PRD §3.4: "`ACTIVATE` carries a reservation from `HELD` to `ACTIVE` and
        requires the logical clock to be inside the half-open window — the current
        instant at or after `window_start_utc` and strictly before `window_end_utc` —
        and the bay's `state` to still be `OPEN`, or the activation is refused with
        `ERR_BAY_OUT_OF_SERVICE`."
        PRD §3.4: "Activation deliberately changes neither ledger, because `HELD` and
        `ACTIVE` are both live occupation states and the minutes were already booked
        at create time."

        Design: Corner/state_machines/begin_charge_requires_an_active_charge_reservation
        """
        ctx = setup_charge_bay_reservation(**CHARGE_WINDOW)
        assert ctx["reservation"]["state"] == "HELD"
        assert ctx["reservation"]["window_minutes"] == 60

        validate_error(
            api.robot_duty_transition(
                ctx["r"],
                duty_transition_payload("BEGIN_CHARGE", bay_reservation_id=ctx["res"]),
                DISPATCHER,
            ),
            "ERR_RESERVATION_NOT_ACTIVE",
            409,
        )

        refused = read_robot(ctx["r"])
        assert refused["duty_state"] == "AVAILABLE"
        assert refused["current_bay_reservation_id"] is None

        set_clock(WINDOW_OPEN_CLOCK_UTC)
        activated = reservation_action(ctx["res"], "ACTIVATE")
        assert activated["state"] == "ACTIVE"
        assert read_bay(ctx["b"])["committed_minutes"] == 60
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 60

        charging = validate_success(
            api.robot_duty_transition(
                ctx["r"],
                duty_transition_payload("BEGIN_CHARGE", bay_reservation_id=ctx["res"]),
                DISPATCHER,
            )
        )
        assert charging["duty_state"] == "CHARGING"
        assert charging["current_bay_reservation_id"] == ctx["res"]

    def test_leaving_charge_releases_the_reservation_and_both_ledgers(self, api):
        """PRD §3.4: "Coming back out of either state uses the same `MAKE_AVAILABLE`
        action with the same two gates — `health_state` in `NOMINAL` or `DEGRADED`
        and `battery_pct` at least 35.0 percent — and releases the depot resource:
        the reservation named by `current_bay_reservation_id` moves to `RELEASED`,
        the bay's `committed_minutes` and the zone's `reserved_bay_minutes` each
        decrease by that reservation's `window_minutes`, and
        `current_bay_reservation_id` is cleared to null."
        PRD §3.4: "A `RELEASE` aimed at a reservation that is not `ACTIVE` is refused
        with `ERR_RESERVATION_NOT_ACTIVE`."
        PRD §3.4: "Because `RELEASED` and `CANCELLED` are both terminal, the
        subtraction can never be applied twice, which is what makes both round trips
        exact: create-then-cancel and create-activate-release each return both
        ledgers to their precise pre-create values with no drift."
        PRD §3.4: "At every instant a bay's `committed_minutes` equals the sum of
        `window_minutes` over that bay's reservations whose `state` is `HELD` or
        `ACTIVE`, and a zone's `reserved_bay_minutes` equals the sum of
        `committed_minutes` over that zone's bays, which is the same as the sum of
        `window_minutes` over every live reservation anywhere in the zone."

        Design: Corner/state_machines/charging_to_available_releases_the_reservation_and_both_ledgers
        """
        ctx = setup_charge_bay_reservation(**CHARGE_WINDOW)
        set_clock(WINDOW_OPEN_CLOCK_UTC)
        reservation_action(ctx["res"], "ACTIVATE")
        charging = validate_success(
            api.robot_duty_transition(
                ctx["r"],
                duty_transition_payload("BEGIN_CHARGE", bay_reservation_id=ctx["res"]),
                DISPATCHER,
            )
        )
        assert charging["duty_state"] == "CHARGING"

        released = duty_action(ctx["r"], "MAKE_AVAILABLE")

        reservation = read_reservation(ctx["res"])
        assert released["duty_state"] == "AVAILABLE"
        assert released["current_bay_reservation_id"] is None
        assert reservation["state"] == "RELEASED"
        assert reservation["window_minutes"] == 60
        assert read_bay(ctx["b"])["committed_minutes"] == 0
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 0

        _held, held_meta = validate_paginated(
            api.list_bay_reservations(DISPATCHER, {"bay_id": ctx["b"], "state": "HELD"})
        )
        _active, active_meta = validate_paginated(
            api.list_bay_reservations(DISPATCHER, {"bay_id": ctx["b"], "state": "ACTIVE"})
        )
        assert held_meta["total_count"] == 0
        assert active_meta["total_count"] == 0

        validate_error(
            api.bay_reservation_transition(
                ctx["res"], reservation_transition_payload("RELEASE"), DISPATCHER
            ),
            "ERR_RESERVATION_NOT_ACTIVE",
            409,
        )
        assert read_bay(ctx["b"])["committed_minutes"] == 0
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 0


class TestRedeliveryCompensation:
    def test_redeliver_returns_the_order_to_the_pipeline_and_the_money_to_escrow(self, api):
        """PRD §3.8: "A `REDELIVER` charges nothing at all, records a
        `remedy_amount_cents` of 0, and is the only kind that puts the order back
        into the pipeline: it is permitted only from `EXCEPTION` and carries the
        order back to `RECEIVED`, clearing `exception_reason` to null so a later
        failure of the same order may latch a different reason."
        PRD §3.8: "It also reverses the money movement of the original exception,
        moving `quoted_fee_cents` out of the merchant's `released_fee_cents` and back
        into its `escrowed_fee_cents`, which is the compensating direction of the
        merchant fee invariant, and it consumes no zone budget whatsoever."
        PRD §3.8: "Every remedy records three fields on the order regardless of kind:
        `remedy_kind` as requested, `remedy_reason_code` set to the `exception_reason`
        that selected the policy — captured before a redelivery clears it, so the
        reason survives on the order even after the field it came from is null — and
        `remedy_amount_cents` as computed."
        PRD §3.8: "A `REDELIVER` touches neither `remedy_spent_cents` nor the
        remaining budget and therefore can never be refused for budget reasons."
        PRD §3.7: "`ZONE_REVOKED` maps to `BLOCKED_ROUTE`, `DISPATCH_CANCELLED` maps
        to `ROBOT_FAULT`, and `UNRECOVERABLE_BLOCKAGE` maps to `BLOCKED_ROUTE`."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order
        that is dispatched a second time shows a count of two."

        Design: Corner/state_machines/redeliver_remedy_compensates_the_exception_in_both_directions
        """
        ctx = setup_planned_mission()
        quote = ctx["order"]["quoted_fee_cents"]
        abort_mission(ctx["mi"], "DISPATCH_CANCELLED")

        excepted = read_order(ctx["o"])
        assert excepted["order_state"] == "EXCEPTION"
        assert excepted["exception_reason"] == "ROBOT_FAULT"
        assert read_merchant(ctx["m"])["released_fee_cents"] == quote

        remedied = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REDELIVER"), SUPPORT)
        )

        zone = read_zone(ctx["z"])
        merchant = read_merchant(ctx["m"])
        assert remedied["order_state"] == "RECEIVED"
        assert remedied["exception_reason"] is None
        assert remedied["remedy_kind"] == "REDELIVER"
        assert remedied["remedy_reason_code"] == "ROBOT_FAULT"
        assert remedied["remedy_amount_cents"] == 0
        assert zone["remedy_spent_cents"] == 0
        assert zone["remedy_budget_remaining_cents"] == zone["remedy_budget_cents"]
        assert merchant["escrowed_fee_cents"] == quote
        assert merchant["released_fee_cents"] == 0
        assert merchant["recognized_fee_cents"] == 0
        assert merchant["exception_count"] == 1
        assert read_order(ctx["o"])["dispatch_attempt_count"] == 1
        assert read_mission(ctx["mi"])["mission_state"] == "ABORTED"
