"""Difficulty tests: boundary precision on numeric thresholds."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    create_appraiser_payload,
    create_coe_request_payload,
    create_loan_payload,
    create_veteran_payload,
    get_funding_fee_assessment,
    setup_closed_loan,
    setup_closed_loan_with_refinance,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_error,
    validate_success,
)


class TestFundingFeeTenPercentBoundary:
    def test_funding_fee_down_payment_ten_pct_boundary_at_ten(self, api):
        """PRD §3.3: "on first use, 2.15 when the percentage is below 5.0000,
        1.50 when it is at least 5.0000 but below 10.0000, and 1.25 at 10.0000
        or more"

        Design: Difficulty/boundary_precision_check/funding_fee_down_payment_ten_pct_boundary
        """
        ctx = setup_veteran_with_issued_coe()
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=3000000),
            ),
            expected_status=201,
        )
        assert float(loan["down_payment_pct"]) == 10.0000
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 1.25
        # loan amount 27000000 * 1.25% = 337500.
        assert fee["assessed_fee_cents"] == 337500

    def test_funding_fee_down_payment_ten_pct_boundary_just_below(self, api):
        """PRD §3.3: "on first use, 2.15 when the percentage is below 5.0000,
        1.50 when it is at least 5.0000 but below 10.0000, and 1.25 at 10.0000
        or more"
        PRD §3.3: "The `down_payment_pct` is the down payment divided by the
        purchase price, expressed as a percentage rounded half up to four
        decimal places."

        Design: Difficulty/boundary_precision_check/funding_fee_down_payment_ten_pct_boundary
        """
        ctx = setup_veteran_with_issued_coe()
        # 2,999,900 / 30,000,000 = 9.9996666... -> rounds to 9.9997 (< 10.0000).
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=2999900),
            ),
            expected_status=201,
        )
        assert float(loan["down_payment_pct"]) == 9.9997
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 1.5
        # loan amount 27000100 * 1.50% = 405001.5 -> truncated to 405000.
        assert fee["assessed_fee_cents"] == 405000


class TestDtiRoundingBoundary:
    def test_dti_rounding_half_up_boundary(self, api):
        """PRD §3.4: "The conventional-style benchmark, `dti_only_pass`, is true
        when `dti_percent` is at most 41.00 — 41.00 exactly passes and 41.01
        fails"
        PRD §3.4: "The decision `outcome` is `APPROVED` when the residual income
        is at least the requirement — equality passes — and additionally either
        the `dti_percent` is at most 41.00 or the residual income reaches at
        least 120 percent of the requirement (the requirement multiplied by 1.2,
        rounded half up to whole cents)"

        Design: Difficulty/boundary_precision_check/dti_rounding_half_up_boundary
        """
        ctx = setup_veteran_with_issued_coe()
        loan_a = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        loan_b = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        # 41.00 exactly: monthly debts 246000 = 150000 + 96000 (1152000/12).
        decision_a = validate_success(
            api.create_underwriting_decision(loan_a["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [1152000],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert float(decision_a["dti_percent"]) == 41.00
        assert decision_a["outcome"] == "APPROVED"

        # 41.0050 -> round_half_up to 41.01; residual compensating factor saves it.
        decision_b = validate_success(
            api.create_underwriting_decision(loan_b["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [1152360],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert float(decision_b["dti_percent"]) == 41.01
        assert decision_b["residual_income_cents"] == 353970
        assert decision_b["residual_required_cents"] == 100300
        assert decision_b["outcome"] == "APPROVED"

    def test_dti_above_limit_without_compensating_residual_denies(self, api):
        """PRD §3.4: "The decision `outcome` is `APPROVED` when the residual
        income is at least the requirement — equality passes — and additionally
        either the `dti_percent` is at most 41.00 or the residual income reaches
        at least 120 percent of the requirement (the requirement multiplied by
        1.2, rounded half up to whole cents); otherwise the outcome is `DENIED`."

        Design: Difficulty/boundary_precision_check/dti_rounding_half_up_boundary
        """
        ctx = setup_veteran_with_issued_coe()
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        # income 200000, housing 82500 -> dti 41.25 (> 41.00), residual 117500
        # >= WEST family-5 requirement 115800 but < 1.2x = 138960 -> DENIED.
        decision = validate_success(
            api.create_underwriting_decision(loan["id"], {
                "gross_monthly_income_cents": 200000,
                "new_housing_payment_cents": 82500,
                "other_obligations_annual_cents": [],
                "family_size": 5,
                "region": "WEST",
            }),
            expected_status=201,
        )
        assert float(decision["dti_percent"]) == 41.25
        assert decision["dti_only_pass"] is False
        assert decision["residual_income_cents"] == 117500
        assert decision["residual_required_cents"] == 115800
        assert decision["outcome"] == "DENIED"


class TestRefinanceSeasoningBoundary:
    def test_refinance_seasoning_exactly_210_days(self, api):
        """PRD §3.8: "Seasoning of at least 210 days is required — 210 exactly
        passes — and a shortfall is rejected with `ERR_SEASONING_NOT_MET`
        (HTTP 422)."
        PRD §3.8: "The `seasoning_days` measured at evaluation time is the
        smaller of two intervals: the days from the loan's `closing_date` to the
        current logical clock reading, and the days from the loan's
        `first_payment_due_date` to the clock."

        Design: Difficulty/boundary_precision_check/refinance_seasoning_exactly_210_days
        """
        ctx = setup_closed_loan_with_refinance(
            clock_iso="2026-09-26T00:00:00Z",
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 5.5,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        # 209 days from first payment 2026-03-01 to 2026-09-26: short by one.
        validate_error(
            api.evaluate_refinance(ctx["refinance"]["id"]),
            ApiErrorId.ERR_SEASONING_NOT_MET, expected_status=422,
        )
        # Advance one day: exactly 210.
        validate_success(api.set_clock("2026-09-27T00:00:00Z"))
        evaluated = validate_success(
            api.evaluate_refinance(ctx["refinance"]["id"]))
        assert evaluated["seasoning_days"] == 210
        assert evaluated["status"] == "APPROVED"
        assert evaluated["recoupment_months"] == 22


class TestAppraisalEmptyPool:
    def test_appraisal_empty_pool_queues_not_errors(self, api):
        """PRD §3.5: "When the candidate set is empty, the appraisal simply stays
        `REQUESTED` — queued, unassigned — and this is not an error."
        PRD §3.5: "The candidate set is the active appraisers whose region equals
        the loan's `property_region` and whose `open_assignment_count` is below
        their `max_open_assignments`."

        Design: Difficulty/boundary_precision_check/appraisal_empty_pool_queues_not_errors
        """
        appraiser = validate_success(
            api.create_appraiser(create_appraiser_payload(
                name="App Q", region="SOUTH", max_open_assignments=1)),
            expected_status=201,
        )
        ctx_a = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Q1"})
        loan_a = validate_success(
            api.create_loan(
                ctx_a["veteran"]["id"],
                create_loan_payload(ctx_a["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        first = validate_success(
            api.create_appraisal_request(loan_a["id"]), expected_status=201)
        assert first["status"] == "ASSIGNED"

        ctx_b = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Q2"})
        loan_b = validate_success(
            api.create_loan(
                ctx_b["veteran"]["id"],
                create_loan_payload(ctx_b["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        second = validate_success(
            api.create_appraisal_request(loan_b["id"]), expected_status=201)
        assert second["status"] == "REQUESTED"
        assert second["appraiser_id"] is None

    def test_refinance_seasoning_below_210_rejected(self, api):
        """PRD §3.8: "Seasoning of at least 210 days is required — 210 exactly
        passes — and a shortfall is rejected with `ERR_SEASONING_NOT_MET`
        (HTTP 422)."

        Design: Difficulty/boundary_precision_check/refinance_seasoning_exactly_210_days
        """
        # One day short: 209 days from the first payment due date.
        ctx = setup_closed_loan_with_refinance(
            clock_iso="2026-09-26T00:00:00Z",
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 5.5,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        resp = api.evaluate_refinance(ctx["refinance"]["id"])
        validate_error(resp, ApiErrorId.ERR_SEASONING_NOT_MET,
                       expected_status=422)

    def test_appraisal_empty_pool_with_zero_appraisers_queues(self, api):
        """PRD §3.5: "When the candidate set is empty, the appraisal simply stays
        `REQUESTED` — queued, unassigned — and this is not an error."

        Design: Difficulty/boundary_precision_check/appraisal_empty_pool_queues_not_errors
        """
        # No appraisers registered at all: the candidate set is empty.
        ctx = setup_veteran_with_issued_coe(
            veteran_overrides={"full_name": "V Q0"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=20000000),
            ),
            expected_status=201,
        )
        appraisal = validate_success(
            api.create_appraisal_request(loan["id"]), expected_status=201)
        assert appraisal["status"] == "REQUESTED"
        assert appraisal["appraiser_id"] is None
