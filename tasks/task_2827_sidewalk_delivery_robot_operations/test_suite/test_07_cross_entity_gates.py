"""Writes on one row that are admissible only because of another row's state.

Each pair issues the identical request twice: once while the foreign row sits in
the blocking state, then again after that row alone has moved, so the request
itself is proved innocent.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OFFICER,
    activate_closure,
    add_closure,
    api_client,
    create_delivery_order_payload,
    health_action,
    health_transition_payload,
    incident_action,
    integration_transition_payload,
    lift_closure,
    read_closure,
    read_incident,
    read_merchant,
    read_mission,
    read_plan,
    read_robot,
    read_segment,
    setup_available_robot,
    setup_draft_route_plan,
    setup_quarantined_robot,
    validate_error,
    validate_paginated,
    validate_success,
)

CONSTRUCTION_CLOSURE = {
    "closure_kind": "HARD",
    "cause": "CONSTRUCTION",
    "starts_at_utc": "2026-08-03T08:00:00.000Z",
    "ends_at_utc": "2026-08-03T12:00:00.000Z",
}
CLEAR_REASON = "inspection found no tampering"


def _suspended_merchant() -> dict:
    """A permitted zone whose merchant has been suspended after activation, with
    the robot present so nothing but the integration gate is in play."""
    ctx = setup_available_robot()
    ctx["merchant"] = validate_success(
        api_client.merchant_integration_transition(
            ctx["m"],
            integration_transition_payload("SUSPEND", reason="failed handoff audit"),
            ADMIN,
        )
    )
    return ctx


class TestOrderIntakeGatedByMerchantState:
    def test_intake_is_refused_while_the_merchants_integration_is_suspended(self, api):
        """PRD §3.3: "Suspension carries the merchant from `ACTIVE` to
        `SUSPENDED`; it has no effect on orders that already exist, and only new
        order intake is refused, with `ERR_MERCHANT_NOT_ACTIVE`."
        PRD §3.3: "The merchant must be `ACTIVE`, or the intake is refused with
        `ERR_MERCHANT_NOT_ACTIVE`; and the dropoff segment must sit in the
        merchant's own zone, or the intake is refused with `ERR_ZONE_MISMATCH`."

        Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_merchant_integration_state
        """
        ctx = _suspended_merchant()
        assert ctx["merchant"]["integration_state"] == "SUSPENDED"

        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(ctx["m"], ctx["s5"]), ctx["merchant_headers"]
            ),
            "ERR_MERCHANT_NOT_ACTIVE",
        )

        orders, _meta = validate_paginated(
            api.list_delivery_orders(ADMIN, {"merchant_id": ctx["m"]})
        )
        assert orders == []

    def test_reinstatement_admits_the_identical_payload_and_escrows_the_quote(self, api):
        """PRD §3.3: "Reinstatement carries the merchant from `SUSPENDED` back to
        `ACTIVE` and, like activation, requires the zone to be `PERMITTED`."
        PRD §3.3: "The order itself lands in `order_state` `RECEIVED`, with
        `settled_fee_cents`, `exception_reason`, `remedy_kind`,
        `remedy_reason_code` and `remedy_amount_cents` all null and
        `dispatch_attempt_count` at zero."
        PRD §3.3: "Immediately afterwards the quoted amount is escrowed: the
        merchant's `escrowed_fee_cents` increases by `quoted_fee_cents` and the
        merchant's `version` advances by one."

        Design: Difficulty/cross_entity_state_dependency/order_creation_gated_by_merchant_integration_state
        """
        ctx = _suspended_merchant()
        payload = create_delivery_order_payload(ctx["m"], ctx["s5"])
        validate_error(
            api.create_delivery_order(payload, ctx["merchant_headers"]),
            "ERR_MERCHANT_NOT_ACTIVE",
        )

        reinstated = validate_success(
            api.merchant_integration_transition(
                ctx["m"], integration_transition_payload("REINSTATE"), ADMIN
            )
        )
        order = validate_success(
            api.create_delivery_order(payload, ctx["merchant_headers"]), 201
        )

        assert reinstated["integration_state"] == "ACTIVE"
        assert order["quoted_fee_cents"] == 850
        assert order["order_state"] == "RECEIVED"
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == 850


def _draft_plan_over_a_blocked_segment() -> dict:
    """A draft plan naming S3, which a hard construction closure has just driven
    to BLOCKED. The plan was never activated, so no cascade reaches it."""
    ctx = setup_draft_route_plan()
    closure = add_closure(ctx["s3"], **CONSTRUCTION_CLOSURE)
    ctx["closure"] = activate_closure(closure["id"])
    ctx["cl"] = closure["id"]
    return ctx


class TestPlanValidationGatedBySegmentStatus:
    def test_validation_is_refused_while_a_named_segment_stands_blocked(self, api):
        """PRD §3.6: "`VALIDATE` carries a plan from `DRAFT` to `VALIDATED` and
        re-examines segment status rather than geometry: every segment in the
        sequence must have `status` `APPROVED` or `BLOCKED`, so a `MAPPED`,
        `SURVEYED` or `RETIRED` segment is refused with
        `ERR_SEGMENT_NOT_APPROVED`, and then no segment may actually be
        `BLOCKED`, which is refused with `ERR_SEGMENT_BLOCKED`."
        PRD §3.2: "The third link is caused by the second: every route plan whose
        `plan_state` is `ACTIVE` and whose sequence contains the newly blocked
        segment is driven to `SUPERSEDED` with `rejection_reason`
        `SEGMENT_BLOCKED`, processed in `created_at` ascending order, and the
        closure's `reroute_triggered_count` advances by one for each plan it
        superseded."

        Design: Difficulty/cross_entity_state_dependency/plan_validation_gated_by_segment_status
        """
        ctx = _draft_plan_over_a_blocked_segment()
        assert read_segment(ctx["s3"])["status"] == "BLOCKED"

        validate_error(
            api.route_plan_transition(ctx["p"], {"action": "VALIDATE"}, DISPATCHER),
            "ERR_SEGMENT_BLOCKED",
        )

        assert read_plan(ctx["p"])["plan_state"] == "DRAFT"
        assert read_mission(ctx["mi"])["mission_state"] == "LOADED"

    def test_lifting_the_closure_lets_the_very_same_draft_row_validate(self, api):
        """PRD §3.2: "Lifting an `ACTIVE` closure sets `state` to the terminal
        `LIFTED`; then, when the lifted closure was `HARD` and no other closure
        on the same segment is both `HARD` and `ACTIVE`, the segment returns from
        `BLOCKED` to `APPROVED` and its `blocked_by_closure_id` is cleared to
        null."
        PRD §3.6: "The geometry gates are deliberately not re-evaluated at
        validation, having already run at creation."

        Design: Difficulty/cross_entity_state_dependency/plan_validation_gated_by_segment_status
        """
        ctx = _draft_plan_over_a_blocked_segment()
        validate_error(
            api.route_plan_transition(ctx["p"], {"action": "VALIDATE"}, DISPATCHER),
            "ERR_SEGMENT_BLOCKED",
        )

        lift_closure(ctx["cl"])
        validated = validate_success(
            api.route_plan_transition(ctx["p"], {"action": "VALIDATE"}, DISPATCHER)
        )

        segment = read_segment(ctx["s3"])
        assert read_closure(ctx["cl"])["state"] == "LIFTED"
        assert segment["status"] == "APPROVED"
        assert segment["blocked_by_closure_id"] is None
        assert validated["plan_state"] == "VALIDATED"
        assert read_mission(ctx["mi"])["mission_state"] == "LOADED"


def _quarantined_robot_with_the_system_report() -> dict:
    """The tamper cascade has quarantined the robot and filed its own DRAFT
    report, which the officer must find by listing rather than by id."""
    ctx = setup_quarantined_robot()
    rows, _meta = validate_paginated(
        api_client.list_incident_reports(
            OFFICER, {"robot_id": ctx["r"], "report_state": "DRAFT"}
        )
    )
    ctx["ir"] = rows[0]["id"]
    return ctx


class TestQuarantineClearGatedByIncidentState:
    def test_the_clear_is_refused_while_the_cascade_report_sits_in_draft(self, api):
        """PRD §3.5: "Beyond requiring `health_state` to be `QUARANTINED`, the
        `CLEAR` action requires that the robot is not `ON_MISSION` and that no
        `IncidentReport` naming this robot is still sitting in `report_state`
        `DRAFT`; an unfiled report blocks the clear with
        `ERR_MANDATORY_INCIDENT_UNFILED` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/quarantine_clear_gated_by_incident_report_state
        """
        ctx = _quarantined_robot_with_the_system_report()

        validate_error(
            api.robot_health_transition(
                ctx["r"], health_transition_payload("CLEAR", reason=CLEAR_REASON), OFFICER
            ),
            "ERR_MANDATORY_INCIDENT_UNFILED",
        )

        robot = read_robot(ctx["r"])
        assert robot["health_state"] == "QUARANTINED"
        assert robot["tamper_flag"] is True
        assert read_incident(ctx["ir"])["report_state"] == "DRAFT"

    def test_submitting_the_system_filed_report_unblocks_the_same_clear(self, api):
        """PRD §3.5: "Since the quarantine cascade itself files a `DRAFT` report,
        the normal recovery path is necessarily two-sided: a `SafetyOfficer` must
        submit the incident before the same officer can return the robot to
        `NOMINAL`."
        PRD §3.9: "A draft created automatically by the quarantine cascade
        carries the literal `SYSTEM` in `filed_by_user_id` and therefore never
        trips that check, which is what allows any officer to file a
        machine-generated report."
        PRD §3.5: "Clearing does not restore duty either — a robot the cascade
        parked in `MAINTENANCE` stays in `MAINTENANCE` until a dispatcher
        explicitly makes it available again."

        Design: Difficulty/cross_entity_state_dependency/quarantine_clear_gated_by_incident_report_state
        """
        ctx = _quarantined_robot_with_the_system_report()
        validate_error(
            api.robot_health_transition(
                ctx["r"], health_transition_payload("CLEAR", reason=CLEAR_REASON), OFFICER
            ),
            "ERR_MANDATORY_INCIDENT_UNFILED",
        )

        submitted = incident_action(
            ctx["ir"],
            "SUBMIT_MUNICIPAL",
            headers=OFFICER,
            municipal_case_ref="SF-2026-0810",
        )
        cleared = health_action(ctx["r"], "CLEAR", headers=OFFICER, reason=CLEAR_REASON)

        assert submitted["report_state"] == "SUBMITTED_MUNICIPAL"
        assert cleared["health_state"] == "NOMINAL"
        assert cleared["tamper_flag"] is False
        assert cleared["duty_state"] == "MAINTENANCE"
