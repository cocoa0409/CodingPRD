"""Compliance cascades: grace windows, posture rollup, and account close."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_ts_equal,
    get_success_data,
    make_account_with_va,
    make_coverage,
    make_device,
    make_pool,
    make_registered_device,
    make_service_contract,
    set_clock,
    setup_pool_in_grace,
    setup_pool_with_assignment,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestGraceDeadlineBoundary:
    def test_pool_in_grace_exactly_at_deadline(self, api):
        """PRD §3.2: "While the logical clock remains at or before
        `grace_deadline` the pool stays `IN_GRACE`".

        Design: Difficulty/boundary_precision_check/grace_deadline_exact_second_boundary
        """
        account, va, pool, device, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        mid = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert mid["compliance_state"] == "IN_GRACE"
        assert_ts_equal(mid["grace_deadline"], "2026-11-30T00:00:00Z",
            "grace deadline must be overage + 90 days")

        set_clock("2026-11-30T00:00:00Z")
        at_deadline = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert at_deadline["compliance_state"] == "IN_GRACE", (
            f"at the deadline the pool must remain IN_GRACE, got {at_deadline['compliance_state']}")

    def test_pool_out_of_compliance_one_second_past_deadline(self, api):
        """PRD §3.2: "once the clock is strictly past the deadline and
        consumption still exceeds entitlement, the pool moves to
        `OUT_OF_COMPLIANCE`, appending a `GRACE_EXPIRED` event and pushing the
        account posture to `NON_COMPLIANT`."

        Design: Difficulty/boundary_precision_check/grace_deadline_exact_second_boundary
        """
        account, va, pool, device, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        set_clock("2026-11-30T00:00:01Z")
        past = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert past["compliance_state"] == "OUT_OF_COMPLIANCE"

        posture = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert posture["compliance_posture"] == "NON_COMPLIANT"


class TestAssignmentReleaseCascade:
    def test_release_recomputes_pool_and_posture(self, api):
        """PRD §3.4: "Releasing an individual assignment directly (without
        deregistering the device) follows the same recompute cascade and
        increments the assignment's `version`."

        Design: Difficulty/transitive_cascade/assignment_release_cascades_pool_to_account_posture
        """
        account, va, pool, device, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        posture = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert posture["compliance_posture"] == "GRACE"

        validate_success(api.release_license_assignment(asg["id"], ADMIN))

        pool_after = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert pool_after["consumed_quantity"] == 0
        assert pool_after["compliance_state"] == "COMPLIANT"

        posture_after = validate_success(api.get_smart_account(account["id"], ADMIN))
        assert posture_after["compliance_posture"] == "COMPLIANT"

    def test_release_clears_overage_fields(self, api):
        """PRD §3.2: "the pool returns to `COMPLIANT`, `overage_detected_at`
        and `grace_deadline` are cleared, a `RESTORED_TO_COMPLIANCE` event is
        appended, and the account posture is recomputed."

        Design: Difficulty/transitive_cascade/assignment_release_cascades_pool_to_account_posture
        """
        account, va, pool, device, asg = setup_pool_in_grace(purchased=1, assign_qty=2)
        validate_success(api.release_license_assignment(asg["id"], ADMIN))

        pool_after = validate_success(api.get_license_pool(pool["id"], ADMIN))
        assert pool_after["grace_deadline"] is None, "cure must clear grace_deadline"
        assert pool_after["overage_detected_at"] is None, "cure must clear overage_detected_at"

        events, meta = validate_paginated(api.list_compliance_events(pool["id"], ADMIN))
        event_types = [e["event_type"] for e in events]
        assert "RESTORED_TO_COMPLIANCE" in event_types, (
            f"expected RESTORED_TO_COMPLIANCE event, got {event_types}")


class TestAccountCloseCascade:
    def test_close_cancels_contract_and_voids_coverage(self, api):
        """PRD §3.1: "When closure proceeds it cascades: every virtual account
        under the account transitions `ACTIVE` to `ARCHIVED`; every `ACTIVE`
        service contract under the account transitions to `CANCELLED`, which
        in turn voids each of that contract's `ACTIVE` coverage rows".

        Design: Difficulty/transitive_cascade/account_close_cascades_contract_voids_coverage
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        validate_success(api.deregister_device(device["id"], ADMIN))  # quiet the account
        contract = make_service_contract(account["id"])
        coverage = make_coverage(contract["id"], device["id"])

        closed = validate_success(api.close_smart_account(account["id"], ADMIN))
        assert closed["status"] == "CLOSED"

        contract_after = validate_success(api.get_service_contract(contract["id"], ADMIN))
        assert contract_after["status"] == "CANCELLED"

        coverage_after = validate_success(api.get_contract_coverage(coverage["id"], ADMIN))
        assert coverage_after["status"] == "VOIDED"

    def test_close_archives_virtual_accounts(self, api):
        """PRD §3.1: "every virtual account under the account transitions
        `ACTIVE` to `ARCHIVED`".

        Design: Difficulty/transitive_cascade/account_close_cascades_contract_voids_coverage
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        validate_success(api.deregister_device(device["id"], ADMIN))
        contract = make_service_contract(account["id"])
        make_coverage(contract["id"], device["id"])

        validate_success(api.close_smart_account(account["id"], ADMIN))
        va_after = validate_success(api.get_virtual_account(va["id"], ADMIN))
        assert va_after["status"] == "ARCHIVED"
