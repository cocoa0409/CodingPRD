"""Show-ready gate: rigging approval + inspection gates on IN_LOAD -> SHOW_READY."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    advance_to_in_load,
    create_safety_inspection,
    set_clock,
    setup_confirmed_engagement,
    setup_rigging_plan,
    validate_error,
    validate_success,
)

PE = TEST_USERS["production_engineer_headers"]
PE_B = TEST_USERS["production_engineer_b_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TM = TEST_USERS["tour_manager_headers"]


class TestShowReadyGate:
    def test_mark_show_ready_without_approved_plan_returns_rigging_not_approved(self):
        """PRD §3.7: "Marking an engagement show-ready advances it `IN_LOAD →
        SHOW_READY` under a `ProductionEngineer`, and enforces both halves of
        the gate: an `APPROVED` rigging plan must exist for the engagement
        (otherwise `ERR_RIGGING_NOT_APPROVED`, HTTP 409), and every safety
        inspection whose kind is required by the tour's act profile must be in
        `PASSED` or `WAIVED` (otherwise `ERR_INSPECTION_OUTSTANDING`,
        HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_show_ready
        """
        ctx = setup_confirmed_engagement()
        create_safety_inspection(
            ctx, inspection_kind="RIGGING", scheduled_at="2026-09-10T12:00:00Z"
        )
        advance_to_in_load(ctx)
        resp = api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        validate_error(resp, ApiErrorId.ERR_RIGGING_NOT_APPROVED)
        eng = validate_success(
            api_client.get_engagement(ctx["tour"]["id"], ctx["engagement"]["id"], TM)
        )
        assert eng["status"] == "IN_LOAD"

    def test_mark_show_ready_with_approved_plan_and_no_inspections_succeeds(self):
        """PRD §3.7: "Marking an engagement show-ready advances it `IN_LOAD →
        SHOW_READY` under a `ProductionEngineer`, and enforces both halves of
        the gate: an `APPROVED` rigging plan must exist for the engagement
        (otherwise `ERR_RIGGING_NOT_APPROVED`, HTTP 409), and every safety
        inspection whose kind is required by the tour's act profile must be in
        `PASSED` or `WAIVED` (otherwise `ERR_INSPECTION_OUTSTANDING`,
        HTTP 409)."

        Design: Difficulty/priority_pair_validation_conflict/business_safety_beats_business_constraint_on_show_ready
        """
        ctx = setup_confirmed_engagement()
        _, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 0}],
            approve=True, approver_headers=PE_B,
        )
        assert plan["status"] == "APPROVED"
        advance_to_in_load(ctx)
        eng = validate_success(
            api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        )
        assert eng["status"] == "SHOW_READY"

    def test_mark_show_ready_blocked_then_unblocked_by_inspection_pass(self):
        """PRD §3.7: "Marking an engagement show-ready advances it `IN_LOAD →
        SHOW_READY` under a `ProductionEngineer`, and enforces both halves of
        the gate: an `APPROVED` rigging plan must exist for the engagement
        (otherwise `ERR_RIGGING_NOT_APPROVED`, HTTP 409), and every safety
        inspection whose kind is required by the tour's act profile must be in
        `PASSED` or `WAIVED` (otherwise `ERR_INSPECTION_OUTSTANDING`,
        HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/mark_show_ready_gated_on_rigging_plan_approved_and_inspections
        """
        ctx = setup_confirmed_engagement()
        _, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 0}],
            approve=True, approver_headers=PE_B,
        )
        assert plan["status"] == "APPROVED"

        insp = create_safety_inspection(
            ctx, inspection_kind="RIGGING", scheduled_at="2026-09-10T12:00:00Z"
        )
        advance_to_in_load(ctx)

        resp = api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        validate_error(resp, ApiErrorId.ERR_INSPECTION_OUTSTANDING)

        set_clock("2026-09-10T13:00:00Z")
        insp = validate_success(
            api_client.pass_safety_inspection(
                ctx["tour"]["id"], ctx["engagement"]["id"], insp["id"],
                {"findings": "ok"}, CO,
            )
        )
        assert insp["status"] == "PASSED"

        eng = validate_success(
            api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        )
        assert eng["status"] == "SHOW_READY"

    def test_mark_show_ready_in_wrong_state_rejected(self):
        """PRD §3.7: "Marking an engagement show-ready advances it `IN_LOAD →
        SHOW_READY` under a `ProductionEngineer`, and enforces both halves of
        the gate: an `APPROVED` rigging plan must exist for the engagement
        (otherwise `ERR_RIGGING_NOT_APPROVED`, HTTP 409), and every safety
        inspection whose kind is required by the tour's act profile must be in
        `PASSED` or `WAIVED` (otherwise `ERR_INSPECTION_OUTSTANDING`,
        HTTP 409)."
        PRD §2.9: "(5) state-machine preconditions on the target resource"

        Design: Difficulty/cross_entity_state_dependency/mark_show_ready_gated_on_rigging_plan_approved_and_inspections
        """
        # A CONFIRMED (not IN_LOAD) engagement cannot be marked show-ready even
        # with an approved plan in place.
        ctx = setup_confirmed_engagement()
        _, plan = setup_rigging_plan(
            ctx, allocations=[{"static_load_kg": 1000, "dynamic_load_kg": 0}],
            approve=True, approver_headers=PE_B,
        )
        assert plan["status"] == "APPROVED"
        resp = api_client.mark_show_ready(ctx["tour"]["id"], ctx["engagement"]["id"], PE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
