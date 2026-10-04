"""Difficulty tests: combinatorial formulas — tier selection, nested rounding
order, and the pinned refinance evaluation order."""
from __future__ import annotations

from test_helpers import (
    create_loan_payload,
    get_funding_fee_assessment,
    get_loan,
    setup_closed_loan,
    setup_closed_loan_with_refinance,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    validate_success,
)


class TestFundingFeeTierSelection:
    def test_funding_fee_tiered_mode_a_at_five_percent(self, api):
        """PRD §3.3: "A `PURCHASE` loan tiers by the down-payment percentage: on
        first use, 2.15 when the percentage is below 5.0000, 1.50 when it is at
        least 5.0000 but below 10.0000, and 1.25 at 10.0000 or more"

        Design: Difficulty/combinatorial_formula/funding_fee_tiered_mode_a
        """
        ctx = setup_veteran_with_issued_coe()
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=1500000),
            ),
            expected_status=201,
        )
        # dp_pct = 1500000 * 100 / 30000000 = 5.0000 exactly -> 1.50 tier.
        assert float(loan["down_payment_pct"]) == 5.0000
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 1.5
        # loan amount 28500000 * 1.50% = 427500.
        assert fee["assessed_fee_cents"] == 427500

    def test_funding_fee_tiered_mode_a_just_below_five_percent(self, api):
        """PRD §3.3: "on first use, 2.15 when the percentage is below 5.0000,
        1.50 when it is at least 5.0000 but below 10.0000, and 1.25 at 10.0000
        or more"

        Design: Difficulty/combinatorial_formula/funding_fee_tiered_mode_a
        """
        ctx = setup_veteran_with_issued_coe()
        # To stay strictly below the 5.0000 boundary use 1,499,900:
        # 1499900*100/30000000 = 4.9996666... -> rounds to 4.9997 (< 5.0000).
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(ctx["coe"]["id"],
                                    purchase_price_cents=30000000,
                                    down_payment_cents=1499900),
            ),
            expected_status=201,
        )
        assert float(loan["down_payment_pct"]) == 4.9997
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 2.15
        # 28500100 * 2.15% = 612752.15 -> truncated to 612700.
        assert fee["assessed_fee_cents"] == 612700


class TestDtiPerItemRounding:
    def test_dti_per_item_rounding_mode_b(self, api):
        """PRD §3.4: "each annual obligation in `other_obligations_annual_cents`
        is first converted to a monthly figure by dividing by twelve and rounding
        that item half up to whole cents, and only then are the per-item monthly
        figures summed into `other_obligations_monthly_cents`. Summing the
        annual items first and dividing once yields a different total and is not
        the rule."

        Design: Difficulty/combinatorial_formula/dti_per_item_rounding_mode_b
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 20000000})
        decision = validate_success(
            api.create_underwriting_decision(ctx["loan"]["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [12500, 12500, 12500],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        # Per-item: round_half_up(12500/12) = 1042; 3 * 1042 = 3126
        # (sum-then-divide would give 3125).
        assert decision["other_obligations_monthly_cents"] == 3126
        # dti = 100 * (150000 + 3126) / 600000 = 25.521 -> 25.52.
        assert float(decision["dti_percent"]) == 25.52

    def test_dti_per_item_rounding_single_item(self, api):
        """PRD §3.4: "each annual obligation in `other_obligations_annual_cents`
        is first converted to a monthly figure by dividing by twelve and rounding
        that item half up to whole cents, and only then are the per-item monthly
        figures summed into `other_obligations_monthly_cents`."
        PRD §3.4: "The `dti_percent` is then the sum of
        `new_housing_payment_cents` and `other_obligations_monthly_cents`,
        divided by `gross_monthly_income_cents`, expressed as a percentage and
        rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/dti_per_item_rounding_mode_b
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 20000000})
        decision = validate_success(
            api.create_underwriting_decision(ctx["loan"]["id"], {
                "gross_monthly_income_cents": 600000,
                "new_housing_payment_cents": 150000,
                "other_obligations_annual_cents": [12500],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert decision["other_obligations_monthly_cents"] == 1042
        # dti = 100 * 151042 / 600000 = 25.173666... -> 25.17.
        assert float(decision["dti_percent"]) == 25.17


class TestRefinanceEvaluationOrder:
    def test_refinance_recoupment_evaluation_order_mode_c(self, api):
        """PRD §3.8: "The NTB computation follows a pinned evaluation order,
        because the funding fee depends on the new base, the costs include the
        fee, and the new payment depends on the costs."
        PRD §3.8: "The `seasoning_days` measured at evaluation time is the
        smaller of two intervals: the days from the loan's `closing_date` to the
        current logical clock reading, and the days from the loan's
        `first_payment_due_date` to the clock."
        PRD §3.8: "refinancing `FIXED` into `FIXED` requires a rate reduction of
        at least 0.50 percentage points"
        PRD §3.8: "For an `IRRRL`, `ntb_satisfied` requires the rate leg and a
        recoupment of no more than 36 months"

        Design: Difficulty/combinatorial_formula/refinance_recoupment_evaluation_order_mode_c
        """
        ctx = setup_closed_loan_with_refinance(
            clock_iso="2026-10-01T00:00:00Z",
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 5.5,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        evaluated = validate_success(
            api.evaluate_refinance(ctx["refinance"]["id"]))
        # seasoning = min(259, 214) = 214 days from first payment 2026-03-01.
        assert evaluated["seasoning_days"] == 214
        assert evaluated["ntb_rate_satisfied"] is True
        # fee = 100000; costs = 250000; new principal 20250000.
        # old payment ~126414; new payment ~114977; savings 11437; ceil(250000/11437) = 22.
        assert evaluated["recoupment_months"] == 22
        assert evaluated["ntb_satisfied"] is True
        assert evaluated["status"] == "APPROVED"

    def test_refinance_recoupment_over_limit_rejects(self, api):
        """PRD §3.8: "For an `IRRRL`, `ntb_satisfied` requires the rate leg and a
        recoupment of no more than 36 months; for a `CASH_OUT`, the rate leg
        alone decides."
        PRD §3.8: "its outcome is a state transition, never an error: a request
        whose NTB fails becomes `REJECTED` (persisted), while one whose NTB
        holds becomes `APPROVED`."

        Design: Difficulty/combinatorial_formula/refinance_recoupment_evaluation_order_mode_c
        """
        ctx = setup_closed_loan_with_refinance(
            clock_iso="2026-10-01T00:00:00Z",
            closing_date="2026-01-15", first_payment_due_date="2026-03-01",
            refinance_overrides={
                "refinance_type": "IRRRL", "new_rate_percent": 5.9,
                "new_rate_type": "FIXED", "flat_costs_cents": 150000,
            },
            price_cents=20000000,
        )
        evaluated = validate_success(
            api.evaluate_refinance(ctx["refinance"]["id"]))
        # Same costs (250000) but savings only 6304 -> ceil(250000/6304) = 40 > 36.
        assert evaluated["ntb_rate_satisfied"] is True
        assert evaluated["recoupment_months"] == 40
        assert evaluated["ntb_satisfied"] is False
        assert evaluated["status"] == "REJECTED"
