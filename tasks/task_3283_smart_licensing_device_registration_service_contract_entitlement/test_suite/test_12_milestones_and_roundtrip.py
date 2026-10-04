"""Conditional milestone/tier validations and assignment round-trip conservation."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account_with_va,
    make_coverage,
    make_device,
    make_pool,
    make_registered_device,
    make_service_contract,
    setup_covered_device,
    setup_pool_with_assignment,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestEndOfSupportMilestone:
    def test_end_of_support_blocks_coverage_not_activation(self, api):
        """PRD §3.5: "an in-effect `END_OF_SUPPORT` milestone blocks new
        coverage attachment for devices of that family with
        `ERR_PRODUCT_END_OF_SUPPORT` (HTTP 422, §3.6); `END_OF_SALE` is
        informational within this platform and blocks nothing on its own."
        PRD §3.4: "`END_OF_SALE` alone does not block activation, and
        `END_OF_SUPPORT` blocks coverage attachment rather than activation."

        Design: Corner/validations/end_of_support_blocks_coverage_not_activation
        """
        account, va = make_account_with_va()
        get_success_data(api.create_lifecycle_milestone({
            "product_family": "PF-EOST",
            "milestone_type": "END_OF_SUPPORT",
            "effective_date": "2026-09-01T00:00:00Z",
        }, ADMIN))
        device = make_device(va["id"], product_family="PF-EOST")
        activated = validate_success(api.activate_device(device["id"], ADMIN))
        assert activated["registration_state"] == "REGISTERED", (
            "END_OF_SUPPORT must not block device activation")
        contract = make_service_contract(account["id"])

        resp = api.create_contract_coverage(
            {"service_contract_id": contract["id"], "device_id": device["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_END_OF_SUPPORT)


class TestSoftwareOnlyContract:
    def test_software_only_contract_never_authorizes_rma(self, api):
        """PRD §3.7: "the contract's `support_tier` include hardware —
        `SOFTWARE_HARDWARE` or `FULL`; a `SOFTWARE_ONLY` contract never
        authorizes an RMA. Failures here are rejected with
        `ERR_NO_ACTIVE_COVERAGE` (HTTP 422)."

        Design: Corner/validations/software_only_contract_blocks_rma
        """
        account, va, device, contract, coverage = setup_covered_device(
            service_level="DEPOT_RETURN", support_tier="SOFTWARE_ONLY")

        resp = api.create_rma_case(
            {"contract_coverage_id": coverage["id"], "failure_description": "x"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COVERAGE)


class TestAssignmentRoundTrip:
    def test_deregister_releases_all_assignments(self, api):
        """PRD §3.4: "Deregistration moves a `REGISTERED` device to
        `DEREGISTERED`, but only while no RMA case for the device sits in a
        non-terminal state. The transition releases every `ACTIVE` license
        assignment the device holds — each assignment moves to `RELEASED`, and
        each release recomputes the referenced pool's consumption, compliance
        state, and account posture".

        Design: Difficulty/compensating_invariant/deregister_reregister_conserves_assignment_quantity
        """
        account, va, pool, device, asg = setup_pool_with_assignment(
            purchased=10, assign_qty=4)

        validate_success(api.deregister_device(device["id"], ADMIN))
        mid = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert mid["consumed_quantity"] == 0, "deregister must release all assignments"

    def test_reregister_and_reassign_restores_quantity_without_drift(self, api):
        """PRD §3.4: "Activation — which transitions the device from `PENDING`
        to `REGISTERED`, or later from `DEREGISTERED` back to `REGISTERED` in
        a re-registration cycle". PRD §3.2: "A pool's `consumed_quantity` is
        recomputed on every accepted usage report, on every assignment
        creation or release touching the pool, and on every transfer
        execution."

        Design: Difficulty/compensating_invariant/deregister_reregister_conserves_assignment_quantity
        """
        account, va, pool, device, asg = setup_pool_with_assignment(
            purchased=10, assign_qty=4)

        validate_success(api.deregister_device(device["id"], ADMIN))
        validate_success(api.activate_device(device["id"], ADMIN))
        validate_success(api.create_license_assignment(
            {"device_id": device["id"], "license_pool_id": pool["id"], "quantity": 4}, ADMIN),
            expected_status=201)

        final = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert final["consumed_quantity"] == 4, "re-assignment must restore exactly 4"
        assert final["compliance_state"] == "COMPLIANT"
