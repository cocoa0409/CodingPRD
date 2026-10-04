"""Corner tests for validation rules: conditional service gates, referential
integrity, OCC, and business-constraint violations."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_standard_service_period,
    approve_underwriting,
    close_loan,
    create_coe_request_payload,
    create_loan_payload,
    create_service_period_payload,
    create_veteran_payload,
    get_funding_fee_assessment,
    get_loan,
    make_underwriter_headers,
    setup_closed_loan,
    setup_loan_with_repairs_required,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoeServiceGate:
    def test_guard_category_requires_180_days(self, api):
        """PRD §3.2: "the veteran's `total_qualifying_service_days` must reach at
        least 90 days when the `service_category` is `REGULAR_MILITARY` and at
        least 180 days when it is `RESERVES_NATIONAL_GUARD`, else the request is
        rejected with `ERR_INSUFFICIENT_SERVICE` (HTTP 422)"

        Design: Corner/validations/guard_category_requires_180_days
        """
        # 122 qualifying days: 2019-03-01 .. 2019-06-30 inclusive.
        guard = validate_success(
            api.create_veteran(create_veteran_payload(
                full_name="V Guard",
                service_category="RESERVES_NATIONAL_GUARD",
            )),
            expected_status=201,
        )
        api.create_service_period(
            guard["id"],
            create_service_period_payload(
                start_date="2019-03-01", end_date="2019-06-30",
            ),
        )
        guard_coe = validate_success(
            api.create_coe_request(guard["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_error(api.issue_coe(guard_coe["id"]),
                       ApiErrorId.ERR_INSUFFICIENT_SERVICE, expected_status=422)

        regular = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V Reg")),
            expected_status=201,
        )
        api.create_service_period(
            regular["id"],
            create_service_period_payload(
                start_date="2019-03-01", end_date="2019-06-30",
            ),
        )
        regular_coe = validate_success(
            api.create_coe_request(regular["id"], create_coe_request_payload()),
            expected_status=201,
        )
        issued = validate_success(api.issue_coe(regular_coe["id"]))
        assert issued["status"] == "ISSUED"

    def test_surviving_spouse_waives_service_minimum(self, api):
        """PRD §3.2: "this gate is waived entirely when the veteran
        `is_surviving_spouse`"
        PRD §3.2: "`has_issued_coe` is true exactly when the veteran holds a
        certificate in `ISSUED` status"

        Design: Corner/validations/surviving_spouse_waives_service_minimum
        """
        spouse = validate_success(
            api.create_veteran(create_veteran_payload(
                full_name="V Spouse", is_surviving_spouse=True,
            )),
            expected_status=201,
        )
        coe = validate_success(
            api.create_coe_request(
                spouse["id"],
                create_coe_request_payload(
                    entitlement_code="UNREIMBURSED_SURVIVING_SPOUSE"),
            ),
            expected_status=201,
        )
        issued = validate_success(api.issue_coe(coe["id"]))
        assert issued["status"] == "ISSUED"
        readback = validate_success(api.get_veteran(spouse["id"]))
        assert readback["has_issued_coe"] is True


class TestLoanCoeReferential:
    def test_loan_create_coe_veteran_mismatch_referential(self, api):
        """PRD §3.3: "The cited certificate must belong to the path veteran — a
        mismatch is rejected with `ERR_SERVICE_PERIOD_MISMATCH`"

        Design: Corner/validations/loan_create_coe_veteran_mismatch_referential
        """
        veteran_a = validate_success(
            api.create_veteran(create_veteran_payload(full_name="V A")),
            expected_status=201,
        )
        ctx_b = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V B"})
        resp = api.create_loan(
            veteran_a["id"],
            create_loan_payload(ctx_b["coe"]["id"],
                                purchase_price_cents=20000000),
        )
        validate_error(resp, ApiErrorId.ERR_SERVICE_PERIOD_MISMATCH,
                       expected_status=422)


class TestRefinanceOcc:
    def test_refinance_occ_stale_version_rejected(self, api):
        """PRD §2.9: "If another writer has advanced the loan's version since
        that observation — for example by closing the loan, recording a payoff,
        or creating an earlier refinance request that the client never saw — the
        create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.8: "Filing a new request on a loan that already has a `SUBMITTED`
        request supersedes the older one — it becomes `SUPERSEDED` at the moment
        the new request is created — and creating the request increments the
        loan's `version` by one."

        Design: Corner/validations/refinance_occ_stale_version_rejected
        """
        ctx = setup_closed_loan(
            price_cents=20000000,
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
        )
        loan = get_loan(ctx["loan"]["id"])
        observed_version = loan["version"]

        refi_a = validate_success(
            api.create_refinance_request(loan["id"], {
                "refinance_type": "IRRRL",
                "new_rate_percent": 5.5,
                "new_rate_type": "FIXED",
                "flat_costs_cents": 150000,
                "expected_loan_version": observed_version,
            }),
            expected_status=201,
        )

        # Stale: still carrying the pre-A version.
        validate_error(
            api.create_refinance_request(loan["id"], {
                "refinance_type": "IRRRL",
                "new_rate_percent": 5.25,
                "new_rate_type": "FIXED",
                "flat_costs_cents": 150000,
                "expected_loan_version": observed_version,
            }),
            ApiErrorId.ERR_STALE_VERSION, expected_status=412,
        )

        fresh_version = get_loan(loan["id"])["version"]
        assert fresh_version == observed_version + 1, (
            "exactly one successful create so far must have bumped the version by one"
        )
        refi_b = validate_success(
            api.create_refinance_request(loan["id"], {
                "refinance_type": "IRRRL",
                "new_rate_percent": 5.25,
                "new_rate_type": "FIXED",
                "flat_costs_cents": 150000,
                "expected_loan_version": fresh_version,
            }),
            expected_status=201,
        )
        assert refi_b["status"] == "SUBMITTED"

        requests, _meta = validate_paginated(api.list_refinance_requests(loan["id"]))
        by_id = {r["id"]: r for r in requests}
        assert by_id[refi_a["id"]]["status"] == "SUPERSEDED"
        assert get_loan(loan["id"])["version"] == observed_version + 2


class TestFundingFeeRefundGate:
    def test_funding_fee_refund_requires_collected_state(self, api):
        """PRD §3.4: "Refunding requires the assessment to be in `COLLECTED` —
        any other status, including an already-refunded assessment, is rejected
        with `ERR_FEE_NOT_REFUNDABLE` (HTTP 409)."

        Design: Corner/validations/funding_fee_refund_requires_collected_state
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 20000000},
            veteran_overrides={"full_name": "V Ref"},
        )
        fee = get_funding_fee_assessment(ctx["loan"]["id"])
        assert fee["status"] == "ASSESSED"
        validate_error(
            api.refund_funding_fee(fee["id"], disability_evidence=True),
            ApiErrorId.ERR_FEE_NOT_REFUNDABLE, expected_status=409,
        )
        after = get_funding_fee_assessment(ctx["loan"]["id"])
        assert after["status"] == "ASSESSED"
        assert after["refunded_cents"] == 0


class TestCloseRepairGate:
    def test_close_blocked_by_open_clearance_repairs(self, api):
        """PRD §3.4: "No repair requirement flagged `required_for_clearance` on
        any of the loan's appraisals may still sit in `OPEN` or `COMPLETED` —
        such repairs must be `VERIFIED` or `WAIVED` before close, else
        `ERR_REPAIRS_OUTSTANDING` (HTTP 409)."

        Design: Corner/validations/close_blocked_by_open_clearance_repairs
        """
        ctx = setup_loan_with_repairs_required(
            repairs=[{"description": "Handrail", "required_for_clearance": True}],
        )
        approve_underwriting(ctx["loan"]["id"])
        validate_error(
            api.close_loan(ctx["loan"]["id"], {
                "closing_date": "2026-03-10",
                "first_payment_due_date": "2026-05-01",
            }),
            ApiErrorId.ERR_REPAIRS_OUTSTANDING, expected_status=409,
        )
        assert get_loan(ctx["loan"]["id"])["closing_status"] == "NOT_CLOSED"


class TestDownPaymentBounds:
    def test_down_payment_above_price_rejected(self, api):
        """PRD §3.3: "The down payment must be at least zero and no greater than
        the purchase price, else `ERR_INVALID_DOWN_PAYMENT` (HTTP 422)."

        Design: Corner/validations/down_payment_above_price_rejected
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Dp"})
        validate_error(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"],
                    purchase_price_cents=20000000,
                    down_payment_cents=20000001,
                ),
            ),
            ApiErrorId.ERR_INVALID_DOWN_PAYMENT, expected_status=422,
        )
        loans, meta = validate_paginated(
            api.list_veteran_loans(ctx["veteran"]["id"]))
        assert loans == [] and meta["total_count"] == 0
