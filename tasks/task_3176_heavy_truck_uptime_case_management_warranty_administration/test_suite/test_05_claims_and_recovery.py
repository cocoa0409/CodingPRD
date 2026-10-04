"""Warranty claims: labor time standard, OCC on submit, parallel
submission/recovery dimensions, and the supplier recovery money chain."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_claim_payload,
    setup_approved_base_warranty_claim,
    setup_case_in_state,
    setup_clock,
    setup_filed_recovery,
    setup_full_environment,
    validate_error,
    validate_paginated,
    validate_success,
)


def _submit_claim(api, env, case_id, claim_id):
    fid, tid = env["fleet"]["id"], env["truck"]["id"]
    case_now = validate_success(api.get_case(fid, tid, case_id, env["uc"]))
    return api.submit_claim(
        fid, tid, case_id, claim_id,
        {"expected_case_version": case_now["version"]}, env["wa"],
    )


class TestLaborTimeStandard:
    def test_extended_coverage_inclusive_boundary_minute_math(self, api):
        """PRD §3.6: "The requested `labor_minutes_claimed` must be no more
        than `labor_hours_allowed` times 60; the comparison is inclusive, so a
        claim equal to exactly that many minutes succeeds while one minute more
        fails with `ERR_LABOR_MINUTES_EXCEED_STANDARD` (HTTP 422).""
        PRD §3.6: "`BASE_WARRANTY` at 1.0, `CAMPAIGN` at 0.9,
        `EXTENDED_COVERAGE` at 1.1, and `GOODWILL` at 0.0"

        Design: Difficulty/combinatorial_formula/labor_time_standard_nested_tier_boundary_minute_math
        """
        setup_clock()
        env = setup_full_environment(
            fleet_name="Boundary Fleet", home_region="PNW", dealer_region="PNW",
            hourly_labor_rate_cents=20000,
        )
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        # EXTENDED_COVERAGE contract so the claim_type is consistent.
        validate_success(
            api.create_coverage_contract(
                fid, tid,
                {
                    "contract_type": "EXTENDED_POWERTRAIN",
                    "starts_on": "2026-01-01T00:00:00Z",
                    "ends_on": "2027-01-01T00:00:00Z",
                    "max_miles": 200000,
                    "premium_cents": 1000000,
                },
                env["fm"],
            ),
            expected_status=201,
        )
        ctx = setup_case_in_state(env, "PENDING_CLOSE", labor_minutes_actual=264)
        case = ctx["case"]

        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="EXTENDED_COVERAGE",
                    labor_minutes_claimed=264,
                    parts_claimed_cents=50000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp = _submit_claim(api, env, case["id"], claim["id"])
        submitted = validate_success(resp)
        assert submitted["submission_status"] == "SUBMITTED"
        assert submitted["labor_hours_allowed"] == pytest.approx(4.40, abs=0.001), (
            f"4.0 base * 1.1 multiplier must allow 4.40 hours, got {submitted['labor_hours_allowed']}"
        )
        assert submitted["labor_amount_allowed_cents"] == 88000, (
            f"4.40 * 20000 = 88000, got {submitted['labor_amount_allowed_cents']}"
        )

        # 265 minutes exceeds 4.40 * 60 = 264 -> must fail.
        claim_over = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="EXTENDED_COVERAGE",
                    labor_minutes_claimed=265,
                    parts_claimed_cents=50000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp_over = _submit_claim(api, env, case["id"], claim_over["id"])
        validate_error(
            resp_over,
            ApiErrorId.ERR_LABOR_MINUTES_EXCEED_STANDARD.value,
            expected_status=422,
        )

    def test_extended_coverage_claim_type_multiplier_applied(self, api):
        """PRD §3.6: "`BASE_WARRANTY` at 1.0, `CAMPAIGN` at 0.9,
        `EXTENDED_COVERAGE` at 1.1, and `GOODWILL` at 0.0"
        PRD §3.6: "`labor_amount_allowed_cents` is `labor_hours_allowed`
        multiplied by the snapshotted `labor_rate_cents_per_hour`, rounded per
        the integer-cent rounding rule."

        Design: Difficulty/combinatorial_formula/labor_time_standard_nested_tier_boundary_minute_math
        """
        setup_clock()
        env = setup_full_environment(
            fleet_name="Boundary4 Fleet", home_region="PNW", dealer_region="PNW",
            hourly_labor_rate_cents=20000,
        )
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        validate_success(
            api.create_coverage_contract(
                fid, tid,
                {
                    "contract_type": "EXTENDED_POWERTRAIN",
                    "starts_on": "2026-01-01T00:00:00Z",
                    "ends_on": "2027-01-01T00:00:00Z",
                    "max_miles": 200000,
                    "premium_cents": 1000000,
                },
                env["fm"],
            ),
            expected_status=201,
        )
        # fault SPN3226_FMI4: base 3.5h * 1.1 = 3.85h -> cap 231 minutes
        ctx = setup_case_in_state(
            env, "PENDING_CLOSE", fault_code="SPN3226_FMI4", labor_minutes_actual=231
        )
        case = ctx["case"]
        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="EXTENDED_COVERAGE",
                    labor_minutes_claimed=231,
                    parts_claimed_cents=10000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        submitted = validate_success(_submit_claim(api, env, case["id"], claim["id"]))
        assert submitted["labor_hours_allowed"] == pytest.approx(3.85, abs=0.001)
        assert submitted["labor_amount_allowed_cents"] == 77000, (
            f"3.85 * 20000 = 77000, got {submitted['labor_amount_allowed_cents']}"
        )

    def test_labor_time_standard_includes_only_declared_fault_codes(self, api):
        """PRD §3.6: "each fault code has a base-hour allowance —
        `SPN3216_FMI4` (aftertreatment doser) allows 4.0 hours, `SPN3226_FMI4`
        (DOC pressure) allows 3.5 hours, `SPN168_FMI4` (battery potential)
        allows 2.0 hours, and any other fault code allows 2.5 hours"

        Design: Corner/calculations/labor_time_standard_includes_only_declared_fault_codes
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Filter Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE", fault_code="SPN9999_FMI1")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY",
                    labor_minutes_claimed=100,
                    parts_claimed_cents=5000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp = _submit_claim(api, env, case["id"], claim["id"])
        submitted = validate_success(resp)
        assert submitted["labor_hours_allowed"] == pytest.approx(2.50, abs=0.001), (
            f"unknown fault code must use the 2.5h default, got {submitted['labor_hours_allowed']}"
        )
        assert submitted["labor_amount_allowed_cents"] == 46250, (
            f"2.50 * 18500 = 46250, got {submitted['labor_amount_allowed_cents']}"
        )


class TestLaborMinutesInclusiveBoundary:
    def test_labor_minutes_inclusive_boundary_on_submit(self, api):
        """PRD §3.6: "The requested `labor_minutes_claimed` must be no more
        than `labor_hours_allowed` times 60; the comparison is inclusive, so a
        claim equal to exactly that many minutes succeeds while one minute more
        fails with `ERR_LABOR_MINUTES_EXCEED_STANDARD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/labor_minutes_inclusive_boundary_on_submit
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Boundary2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE", labor_minutes_actual=240)
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        claim_ok = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=240,
                    parts_claimed_cents=50000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        claim_over = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=241,
                    parts_claimed_cents=50000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )

        resp_ok = _submit_claim(api, env, case["id"], claim_ok["id"])
        submitted = validate_success(resp_ok)
        assert submitted["submission_status"] == "SUBMITTED"
        assert submitted["labor_hours_allowed"] == pytest.approx(4.00, abs=0.001)

        resp_over = _submit_claim(api, env, case["id"], claim_over["id"])
        validate_error(
            resp_over,
            ApiErrorId.ERR_LABOR_MINUTES_EXCEED_STANDARD.value,
            expected_status=422,
        )
        over_after = validate_success(
            api.get_claim(fid, tid, case["id"], claim_over["id"], env["wa"])
        )
        assert over_after["submission_status"] == "DRAFT", (
            "rejected submit must leave the claim in DRAFT"
        )

    def test_one_minute_over_boundary_rejected_independently(self, api):
        """PRD §3.6: "The requested `labor_minutes_claimed` must be no more
        than `labor_hours_allowed` times 60; the comparison is inclusive, so a
        claim equal to exactly that many minutes succeeds while one minute more
        fails with `ERR_LABOR_MINUTES_EXCEED_STANDARD` (HTTP 422)."

        Design: Difficulty/boundary_precision_check/labor_minutes_inclusive_boundary_on_submit
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Boundary3 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim_over = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=241,
                    parts_claimed_cents=1000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp = _submit_claim(api, env, case["id"], claim_over["id"])
        validate_error(
            resp,
            ApiErrorId.ERR_LABOR_MINUTES_EXCEED_STANDARD.value,
            expected_status=422,
        )


class TestOccOnClaimSubmit:
    def test_occ_expected_case_version_must_match(self, api):
        """PRD §2.8: "Submitting a warranty claim requires
        `expected_case_version` equal to the case's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross-cutting complexity layers/occ_expected_case_version_must_match
        """
        setup_clock()
        env = setup_full_environment(fleet_name="OCC Fleet")
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        case = validate_success(
            api.create_case(fid, tid, {"fault_code": "SPN3216_FMI4"}, env["uc"]),
            expected_status=201,
        )
        stale_version = case["version"]
        # drive the case to PENDING_CLOSE (bumps version several times)
        validate_success(api.triage_case(fid, tid, case["id"], env["uc"]))
        truck_now = validate_success(api.get_truck(fid, tid, env["fm"]))
        validate_success(
            api.schedule_case(
                fid, tid, case["id"],
                {
                    "dealer_id": env["dealer"]["id"],
                    "bay_id": env["bay"]["id"],
                    "scheduled_start_at": "2026-09-01T14:00:00Z",
                    "scheduled_end_at": "2026-09-01T17:00:00Z",
                    "expected_truck_version": truck_now["version"],
                },
                env["uc"],
            )
        )
        wos = validate_paginated(api.list_work_orders(fid, tid, case["id"], env["uc"]))[0]
        validate_success(
            api.authorize_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"diagnostic_minutes_authorized": 30}, env["uc"],
            )
        )
        validate_success(api.start_service(fid, tid, case["id"], env["da"]))
        validate_success(
            api.complete_work_order(
                fid, tid, case["id"], wos[0]["id"],
                {"labor_minutes_actual": 100, "repair_outcome": "FIXED"}, env["da"],
            )
        )
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=100,
                    parts_claimed_cents=5000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp = api.submit_claim(
            fid, tid, case["id"], claim["id"],
            {"expected_case_version": stale_version}, env["wa"],
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION.value, expected_status=412)
        after = validate_success(api.get_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert after["submission_status"] == "DRAFT"

    def test_submit_with_fresh_case_version_succeeds(self, api):
        """PRD §2.8: "Submitting a warranty claim requires
        `expected_case_version` equal to the case's current `version`. A
        mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)"

        Design: Corner/cross-cutting complexity layers/occ_expected_case_version_must_match
        """
        setup_clock()
        env = setup_full_environment(fleet_name="OCC2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim = validate_success(
            api.create_claim(
                fid, tid, case["id"],
                create_claim_payload(
                    claim_type="BASE_WARRANTY", labor_minutes_claimed=100,
                    parts_claimed_cents=5000,
                ),
                env["wa"],
            ),
            expected_status=201,
        )
        resp = _submit_claim(api, env, case["id"], claim["id"])
        submitted = validate_success(resp)
        assert submitted["submission_status"] == "SUBMITTED"


class TestParallelDimensions:
    def test_warranty_claim_parallel_submission_x_recovery_dimensions(self, api):
        """PRD §3.6: "**Full approval.** The claim moves to `APPROVED`. If
        `claim_type` is `BASE_WARRANTY` or `CAMPAIGN` and the claim has
        returnable parts, the claim's `recovery_status` moves `NOT_INITIATED` →
        `PART_RETURN_REQUESTED` and a `PartReturn` row is created in
        `REQUESTED` status against the claim, with `part_number` matching an
        installed part order on the case and `return_window_days` snapshotted —
        30 days for `BASE_WARRANTY`, 45 days otherwise."
        PRD §3.7: "A `DealerAdvisor` ships the failed part back: the return
        moves `REQUESTED` → `IN_TRANSIT`, its `shipped_at` is stamped, and the
        parent claim's `recovery_status` moves `PART_RETURN_REQUESTED` →
        `PART_IN_TRANSIT`."

        Design: Difficulty/non_linear_state_machine/warranty_claim_parallel_submission_x_recovery_dimensions
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Parallel Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        claim, part_return = setup_approved_base_warranty_claim(
            env, case["id"],
            claim_type="BASE_WARRANTY",
            labor_minutes_claimed=180,
            parts_claimed_cents=250000,
        )
        assert claim["submission_status"] == "APPROVED"
        assert part_return is not None, "BASE_WARRANTY approval must create a PartReturn"

        shipped = validate_success(
            api.ship_part_return(fid, tid, case["id"], claim["id"], part_return["id"], env["da"])
        )
        assert shipped["part_return_status"] == "IN_TRANSIT"

        claim_now = validate_success(api.get_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert claim_now["submission_status"] == "APPROVED"
        assert claim_now["recovery_status"] == "PART_IN_TRANSIT"
        assert part_return["return_window_days"] == 30, (
            f"BASE_WARRANTY return window is 30 days, got {part_return['return_window_days']}"
        )

    def test_submission_dimension_terminal_while_recovery_still_in_flight(self, api):
        """PRD §3.6: "**Full approval.** The claim moves to `APPROVED`. If
        `claim_type` is `BASE_WARRANTY` or `CAMPAIGN` and the claim has
        returnable parts, the claim's `recovery_status` moves `NOT_INITIATED` →
        `PART_RETURN_REQUESTED` and a `PartReturn` row is created in
        `REQUESTED` status against the claim, with `part_number` matching an
        installed part order on the case and `return_window_days` snapshotted —
        30 days for `BASE_WARRANTY`, 45 days otherwise."

        Design: Difficulty/non_linear_state_machine/warranty_claim_parallel_submission_x_recovery_dimensions
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Parallel2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        claim, part_return = setup_approved_base_warranty_claim(
            env, case["id"],
            claim_type="BASE_WARRANTY",
            labor_minutes_claimed=100,
            parts_claimed_cents=100000,
        )
        claim_now = validate_success(
            api.get_claim(
                env["fleet"]["id"], env["truck"]["id"], case["id"], claim["id"], env["wa"]
            )
        )
        assert claim_now["submission_status"] == "APPROVED"
        assert claim_now["recovery_status"] == "PART_RETURN_REQUESTED", (
            "recovery dimension advances independently of the terminal submission dimension"
        )
        assert claim_now["submission_status"] != claim_now["recovery_status"]


class TestPendingCloseCycle:
    def test_case_pending_close_to_in_service_cycle(self, api):
        """PRD §3.8: "A `PENDING_CLOSE` case can be sent back to `IN_SERVICE`
        by a `UptimeCoordinator` — this is the reopen path used when warranty
        review kicks a case back — and the bay returns to `IN_USE` if it had
        already been released to `AVAILABLE`."

        Design: Difficulty/non_linear_state_machine/case_pending_close_to_in_service_cycle
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cycle Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        # Cycle 1: PENDING_CLOSE -> IN_SERVICE -> PENDING_CLOSE
        reopened = validate_success(api.reopen_service(fid, tid, case["id"], env["uc"]))
        assert reopened["case_status"] == "IN_SERVICE"
        validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        # Cycle 2
        validate_success(api.reopen_service(fid, tid, case["id"], env["uc"]))
        final = validate_success(api.request_close(fid, tid, case["id"], env["da"]))
        assert final["case_status"] == "PENDING_CLOSE"
        assert final["downtime_hours"] == 0.00, "still open — downtime stays 0.00"

        truck = validate_success(api.get_truck(fid, tid, env["fm"]))
        assert truck["open_case_count"] == 1
        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "IN_USE"

    def test_reopen_service_returns_case_to_in_service(self, api):
        """PRD §3.8: "A `PENDING_CLOSE` case can be sent back to `IN_SERVICE`
        by a `UptimeCoordinator` — this is the reopen path used when warranty
        review kicks a case back — and the bay returns to `IN_USE` if it had
        already been released to `AVAILABLE`."

        Design: Difficulty/non_linear_state_machine/case_pending_close_to_in_service_cycle
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Cycle2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]
        reopened = validate_success(api.reopen_service(fid, tid, case["id"], env["uc"]))
        assert reopened["case_status"] == "IN_SERVICE"
        bay = validate_success(api.get_bay_by_id(env["bay"]["id"], env["uc"]))
        assert bay["bay_status"] == "IN_USE"


class TestRecoveryMoneyInvariant:
    def test_claim_approve_then_mark_paid_accumulates_recovery_amount(self, api):
        """PRD §3.7: "The paid amount first offsets the OEM's recorded
        `parts_amount_allowed_cents` on the claim; the claim's
        `recovery_amount_cents` is then incremented by the paid amount, the
        recovery's `paid_amount_cents` is set, the recovery moves to `PAID`,
        and the claim's `recovery_status` advances to `RECOVERY_PAID`."

        Design: Difficulty/compensating_invariant/claim_approve_then_deny_conserves_recovery_amount
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Inv2 Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        claim, part_return, recovery = setup_filed_recovery(
            env, case["id"], claimed_amount_cents=10000, parts_claimed_cents=100000
        )
        paid = validate_success(
            api.mark_paid_recovery(
                fid, tid, case["id"], claim["id"], recovery["id"],
                {"paid_amount_cents": 10000}, env["sm"],
            )
        )
        assert paid["recovery_status"] == "PAID"
        assert paid["paid_amount_cents"] == 10000

        claim_now = validate_success(api.get_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert claim_now["recovery_amount_cents"] == 10000
        assert claim_now["recovery_status"] == "RECOVERY_PAID"

    def test_denied_recovery_contributes_zero_to_recovery_amount(self, api):
        """PRD §3.7: "Alternatively, a recovery in `FILED` or `UNDER_DISPUTE`
        may be denied outright, moving to `DENIED` and pushing the claim's
        `recovery_status` to `RECOVERY_DENIED`."

        Design: Difficulty/compensating_invariant/claim_approve_then_deny_conserves_recovery_amount
        """
        setup_clock()
        env = setup_full_environment(fleet_name="Inv2b Fleet")
        ctx = setup_case_in_state(env, "PENDING_CLOSE")
        case = ctx["case"]
        fid, tid = env["fleet"]["id"], env["truck"]["id"]

        claim, part_return, recovery = setup_filed_recovery(
            env, case["id"], claimed_amount_cents=8000, parts_claimed_cents=100000
        )
        denied = validate_success(
            api.deny_recovery(fid, tid, case["id"], claim["id"], recovery["id"], env["sm"])
        )
        assert denied["recovery_status"] == "DENIED"
        assert denied["paid_amount_cents"] == 0

        claim_now = validate_success(api.get_claim(fid, tid, case["id"], claim["id"], env["wa"]))
        assert claim_now["recovery_amount_cents"] == 0, (
            "a denied recovery contributes zero to the claim's recovery_amount_cents"
        )
        assert claim_now["recovery_status"] == "RECOVERY_DENIED"
