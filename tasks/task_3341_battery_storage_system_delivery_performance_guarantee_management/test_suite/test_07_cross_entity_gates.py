"""Cross-entity state dependency tests: ESA execute gated by the three safety
permits; spare-part install gated by the linked warranty claim."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    approve_all_permits,
    create_claim_under_review,
    create_esa,
    create_order,
    create_project,
    get_success_data,
    setup_active_ltsa,
    setup_executed_project,
    submit_permit,
    validate_error,
    validate_success,
)

DEV = TEST_USERS["project_developer_headers"]
SAFETY = TEST_USERS["safety_authority_headers"]
SVC_ENG = TEST_USERS["service_engineer_headers"]
SVC_MGR = TEST_USERS["service_manager_headers"]
WARRANTY = TEST_USERS["warranty_admin_headers"]


class TestEsaExecutePermitGate:
    def test_two_of_three_permits_approved_still_blocks_execute(self, api):
        """PRD §3.2: "Execution of an agreement is blocked until all three
        permit types exist for the project in `APPROVED` status; the block
        surfaces as `ERR_PERMIT_MISSING_OR_UNAPPROVED`."

        Design: Difficulty/cross_entity_state_dependency/esa_execute_gated_by_three_permit_approvals
        """
        project = create_project(api=api)
        esa = create_esa(project["id"], api=api)
        # Approve two of three; LOCAL_APPROVAL stays SUBMITTED.
        for ptype in ("THERMAL_RUNAWAY_PLAN", "FIRE_CODE"):
            permit = submit_permit(project["id"], ptype, api=api)
            validate_success(api.decide_permit(permit["id"], {"decision": "APPROVED"}, SAFETY))
        pending = submit_permit(project["id"], "LOCAL_APPROVAL", api=api)

        current = get_success_data(api.get_project(project["id"], DEV))
        resp = api.execute_esa(
            esa["id"], {"expected_project_version": current["version"]}, DEV
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_MISSING_OR_UNAPPROVED)
        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["status"] == "DRAFT"

        # Gate lifts once the third permit is approved.
        validate_success(api.decide_permit(pending["id"], {"decision": "APPROVED"}, SAFETY))
        current = get_success_data(api.get_project(project["id"], DEV))
        executed = validate_success(
            api.execute_esa(
                esa["id"], {"expected_project_version": current["version"]}, DEV
            )
        )
        assert executed["status"] == "EXECUTED"

    def test_missing_permit_type_also_blocks_execute(self, api):
        """PRD §3.2: "Execution of an agreement is blocked until all three
        permit types exist for the project in `APPROVED` status; the block
        surfaces as `ERR_PERMIT_MISSING_OR_UNAPPROVED`."

        Design: Difficulty/cross_entity_state_dependency/esa_execute_gated_by_three_permit_approvals
        """
        project = create_project(api=api)
        esa = create_esa(project["id"], api=api)
        # Only one permit type exists at all.
        permit = submit_permit(project["id"], "FIRE_CODE", api=api)
        validate_success(api.decide_permit(permit["id"], {"decision": "APPROVED"}, SAFETY))

        current = get_success_data(api.get_project(project["id"], DEV))
        resp = api.execute_esa(
            esa["id"], {"expected_project_version": current["version"]}, DEV
        )
        validate_error(resp, ApiErrorId.ERR_PERMIT_MISSING_OR_UNAPPROVED)
        esa_after = get_success_data(api.get_esa(esa["id"], DEV))
        assert esa_after["status"] == "DRAFT"


class TestInstallGatedByClaimApproved:
    def _setup(self, api):
        project, esa = setup_executed_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api)
        claim = create_claim_under_review(esa["id"], api=api)
        order = create_order(
            ltsa["id"], api=api, role_headers=SVC_ENG,
            warranty_claim_id=claim["id"],
            part_description="Replacement cells",
            part_cost_cents=100000,
        )
        validate_success(api.ship_order(order["id"], SVC_ENG))
        validate_success(api.deliver_order(order["id"], SVC_ENG))
        return project, esa, ltsa, claim, order

    def test_install_blocked_until_claim_approved_then_fulfills(self, api):
        """PRD §3.7: "Installation has one cross-entity dependency: when the
        order's `warranty_claim_id` is set, the linked claim must be
        `APPROVED`, else `ERR_CLAIM_NOT_FULFILLABLE`, and a successful
        installation drives that claim from `APPROVED` to `FULFILLED`."

        Design: Difficulty/cross_entity_state_dependency/install_gated_by_warranty_claim_approved
        """
        _, esa, _, claim, order = self._setup(api)

        # Claim is UNDER_REVIEW -> install refused.
        resp = api.install_order(order["id"], SVC_ENG)
        validate_error(resp, ApiErrorId.ERR_CLAIM_NOT_FULFILLABLE)

        approved = validate_success(
            api.decide_claim(
                claim["id"],
                {"decision": "APPROVED", "credit_variant": "STRAIGHT_LINE"},
                WARRANTY,
            )
        )
        assert approved["credit_amount_cents"] == 15000, (
            f"ceil(0.05 * 300000) == 15000, got {approved['credit_amount_cents']}"
        )
        installed = validate_success(api.install_order(order["id"], SVC_ENG))
        assert installed["status"] == "INSTALLED"
        claim_after = get_success_data(api.get_warranty_claim(claim["id"], WARRANTY))
        assert claim_after["status"] == "FULFILLED"

    def test_install_without_linked_claim_needs_no_gate(self, api):
        """PRD §3.7: "Installation has one cross-entity dependency: when the
        order's `warranty_claim_id` is set, the linked claim must be
        `APPROVED`, else `ERR_CLAIM_NOT_FULFILLABLE`, and a successful
        installation drives that claim from `APPROVED` to `FULFILLED`."
        PRD §3.7: "The order lifecycle walks `ORDERED` to `SHIPPED` to
        `DELIVERED` to `INSTALLED`"

        Design: Difficulty/cross_entity_state_dependency/install_gated_by_warranty_claim_approved
        """
        project, esa = setup_executed_project(api=api)
        ltsa = setup_active_ltsa(project["id"], api=api)
        order = create_order(
            ltsa["id"], api=api, role_headers=SVC_ENG,
            part_description="Coolant pump", part_cost_cents=50000,
        )
        validate_success(api.ship_order(order["id"], SVC_ENG))
        validate_success(api.deliver_order(order["id"], SVC_ENG))
        installed = validate_success(api.install_order(order["id"], SVC_ENG))
        assert installed["status"] == "INSTALLED"
