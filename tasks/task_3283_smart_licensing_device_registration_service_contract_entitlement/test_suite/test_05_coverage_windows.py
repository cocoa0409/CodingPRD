"""Coverage attachment: half-open window, overlap occupancy, and RMA gating."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    get_success_data,
    make_account_with_va,
    make_coverage,
    make_device,
    make_registered_device,
    make_service_contract,
    set_clock,
    setup_covered_device,
    setup_open_rma,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


class TestCoverageWindow:
    def test_attach_at_start_boundary_succeeds(self, api):
        """PRD §3.6: "the contract being `ACTIVE` and the current logical
        clock falling within the half-open window from `start_date` up to but
        not including `end_date` (`ERR_CONTRACT_WINDOW_INVALID`)".

        Design: Difficulty/resource_temporal_overlap/coverage_attach_outside_half_open_window
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        contract = make_service_contract(
            account["id"], start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z")

        coverage = validate_success(api.create_contract_coverage(
            {"service_contract_id": contract["id"], "device_id": device["id"]}, ADMIN),
            expected_status=201)
        assert coverage["status"] == "ACTIVE", "attach at the inclusive start boundary must succeed"

    def test_attach_exactly_at_end_date_rejected(self, api):
        """PRD §3.6: "`start_date` inclusive, `end_date` exclusive, with
        `end_date` required to be strictly after `start_date`". PRD §3.6:
        "the contract being `ACTIVE` and the current logical clock falling
        within the half-open window from `start_date` up to but not including
        `end_date` (`ERR_CONTRACT_WINDOW_INVALID`)".

        Design: Difficulty/resource_temporal_overlap/coverage_attach_outside_half_open_window
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        contract = make_service_contract(
            account["id"], start_date="2026-09-01T00:00:00Z", end_date="2026-10-01T00:00:00Z")
        coverage = make_coverage(contract["id"], device["id"])
        validate_success(api.release_contract_coverage(coverage["id"], ADMIN))

        set_clock("2026-10-01T00:00:00Z")  # exactly at end_date (exclusive)
        resp = api.create_contract_coverage(
            {"service_contract_id": contract["id"], "device_id": device["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_WINDOW_INVALID)


class TestCoveragePointOccupancy:
    def test_second_active_coverage_rejected(self, api):
        """PRD §3.6: "the device having no other `ACTIVE` coverage row — at
        most one active coverage per serial — (`ERR_COVERAGE_OVERLAP`,
        HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/device_active_coverage_point_occupancy
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        c1 = make_service_contract(account["id"], service_level="ADVANCE_NBD")
        c2 = make_service_contract(account["id"], service_level="ADVANCE_4H")
        make_coverage(c1["id"], device["id"])

        resp = api.create_contract_coverage(
            {"service_contract_id": c2["id"], "device_id": device["id"]}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)

    def test_release_frees_the_device_for_new_coverage(self, api):
        """PRD §3.6: "Individual coverages can also be released explicitly
        while `ACTIVE`, provided no RMA case under the coverage is
        non-terminal; release moves the coverage to `RELEASED` and increments
        its `version`."

        Design: Difficulty/resource_temporal_overlap/device_active_coverage_point_occupancy
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        c1 = make_service_contract(account["id"], service_level="ADVANCE_NBD")
        c2 = make_service_contract(account["id"], service_level="ADVANCE_4H")
        cov1 = make_coverage(c1["id"], device["id"])

        released = validate_success(api.release_contract_coverage(cov1["id"], ADMIN))
        assert released["status"] == "RELEASED"

        cov2 = validate_success(api.create_contract_coverage(
            {"service_contract_id": c2["id"], "device_id": device["id"]}, ADMIN),
            expected_status=201)
        assert cov2["status"] == "ACTIVE", "released coverage must free the device"


class TestRmaCoverageGate:
    def test_rma_blocked_after_contract_cancelled(self, api):
        """PRD §3.6: "cancellation transitions the contract from `ACTIVE` to
        `CANCELLED`, voids every `ACTIVE` coverage row under it (each coverage
        moves to `VOIDED`, which blocks future RMA creation on that device)".

        Design: Difficulty/cross_entity_state_dependency/rma_creation_gated_by_coverage_and_contract_window
        """
        account, va, device, contract, coverage = setup_covered_device()
        validate_success(api.cancel_service_contract(contract["id"], ADMIN))

        resp = api.create_rma_case(
            {"contract_coverage_id": coverage["id"], "failure_description": "fan failure"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COVERAGE)

    def test_rma_requires_active_in_window_hardware_capable_contract(self, api):
        """PRD §3.7: "Opening requires, beyond the generic checks, that the
        coverage be `ACTIVE`, that its contract be `ACTIVE` and in-window at
        the current logical clock, and that the contract's `support_tier`
        include hardware — `SOFTWARE_HARDWARE` or `FULL`; a `SOFTWARE_ONLY`
        contract never authorizes an RMA. Failures here are rejected with
        `ERR_NO_ACTIVE_COVERAGE` (HTTP 422)."

        Design: Difficulty/cross_entity_state_dependency/rma_creation_gated_by_coverage_and_contract_window
        """
        account, va = make_account_with_va()
        device = make_registered_device(va["id"])
        contract = make_service_contract(
            account["id"], start_date="2026-09-01T00:00:00Z", end_date="2026-09-05T00:00:00Z")
        coverage = make_coverage(contract["id"], device["id"])

        set_clock("2026-09-10T00:00:00Z")  # outside the window; contract expired
        resp = api.create_rma_case(
            {"contract_coverage_id": coverage["id"], "failure_description": "psu failure"}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_COVERAGE)
