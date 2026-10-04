"""Corner tests for calculation rules: funding fee precision and tiers,
residual-income table lookups, and entitlement feasibility at close."""
from __future__ import annotations

from test_helpers import (
    approve_underwriting,
    close_loan,
    create_loan_payload,
    create_south_appraiser,
    create_veteran_payload,
    get_entitlement_account,
    get_funding_fee_assessment,
    get_loan,
    order_assigned_appraisal,
    setup_approved_loan,
    setup_closed_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    submit_value_issued_report,
    validate_error,
    validate_success,
    ApiErrorId,
)


class TestFundingFeeTruncation:
    def test_funding_fee_truncates_to_whole_dollar(self, api):
        """PRD §3.3: "The assessed fee is the loan amount multiplied by the rate,
        expressed as a percent, and then truncated down to the nearest whole
        dollar — fractional dollars are discarded, never rounded."

        Design: Corner/calculations/funding_fee_truncates_to_whole_dollar
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Trunc"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"],
                    purchase_price_cents=30000100,
                    down_payment_cents=300000,
                ),
            ),
            expected_status=201,
        )
        assert loan["loan_amount_cents"] == 29700100
        fee = get_funding_fee_assessment(loan["id"])
        # 29700100 * 2.15% = 638552.15 exact cents -> truncated down to 638500.
        assert fee["assessed_fee_cents"] == 638500


class TestFundingFeeFlatRates:
    def test_funding_fee_irrrl_flat_rate_ignores_tiers(self, api):
        """PRD §3.3: "An `IRRRL` loan always pays a rate of 0.50."

        Design: Corner/calculations/funding_fee_irrrl_flat_rate_ignores_tiers
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Irr"})
        loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"],
                    purpose="IRRRL",
                    purchase_price_cents=21000000,
                    down_payment_cents=1000000,
                    interest_rate_percent=5.5,
                ),
            ),
            expected_status=201,
        )
        fee = get_funding_fee_assessment(loan["id"])
        assert float(fee["fee_rate"]) == 0.5
        assert fee["assessed_fee_cents"] == 100000

    def test_funding_fee_cash_out_subsequent_flat(self, api):
        """PRD §3.3: "A `CASH_OUT_REFINANCE` pays 2.15 on first use and 3.30 on
        subsequent use, with the down payment not considered."
        PRD §3.3: "The `loan_use` is `FIRST_USE` when the borrower's
        `charged_loan_count` is zero at creation and `SUBSEQUENT_USE` otherwise"

        Design: Corner/calculations/funding_fee_cash_out_subsequent_flat
        """
        ctx = setup_closed_loan(price_cents=20000000)
        second = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"],
                    purpose="CASH_OUT_REFINANCE",
                    purchase_price_cents=22000000,
                    down_payment_cents=2000000,
                    interest_rate_percent=6.25,
                ),
            ),
            expected_status=201,
        )
        assert second["loan_use"] == "SUBSEQUENT_USE"
        fee = get_funding_fee_assessment(second["id"])
        assert float(fee["fee_rate"]) == 3.3
        # loan_amount = 22000000 - 2000000 = 20000000; 3.30% -> 660000.
        assert fee["assessed_fee_cents"] == 660000


class TestResidualIncomeTable:
    def test_residual_income_region_table_lookup(self, api):
        """PRD §3.4: "The `residual_required_cents` comes from a table keyed by
        region and family size. For a family of one through five, the monthly
        requirement in cents is: in the `NORTHEAST`, 45,000 / 75,500 / 90,900 /
        102,500 / 106,200; in the `MIDWEST`, 44,100 / 73,800 / 88,900 / 100,300 /
        103,900; in the `SOUTH`, the same five values as the Midwest; in the
        `WEST`, 49,100 / 82,300 / 99,000 / 111,700 / 115,800."

        Design: Corner/calculations/residual_income_region_table_lookup
        """
        ctx = setup_veteran_with_issued_coe(veteran_overrides={"full_name": "V Reg"})
        decision_payload = {
            "gross_monthly_income_cents": 400000,
            "new_housing_payment_cents": 320000,
            "other_obligations_annual_cents": [],
            "family_size": 2,
        }
        west_loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"], property_region="WEST",
                    purchase_price_cents=20000000,
                ),
            ),
            expected_status=201,
        )
        south_loan = validate_success(
            api.create_loan(
                ctx["veteran"]["id"],
                create_loan_payload(
                    ctx["coe"]["id"], property_region="SOUTH",
                    purchase_price_cents=20000000,
                ),
            ),
            expected_status=201,
        )
        west_decision = validate_success(
            api.create_underwriting_decision(
                west_loan["id"], {**decision_payload, "region": "WEST"},
            ),
            expected_status=201,
        )
        assert west_decision["residual_required_cents"] == 82300
        assert west_decision["residual_income_cents"] == 80000
        assert west_decision["outcome"] == "DENIED"

        south_decision = validate_success(
            api.create_underwriting_decision(
                south_loan["id"], {**decision_payload, "region": "SOUTH"},
            ),
            expected_status=201,
        )
        assert south_decision["residual_required_cents"] == 73800
        assert south_decision["residual_income_cents"] == 80000
        # PRD §3.4: residual >= required alone is not sufficient — with
        # dti 80.00 > 41.00 the residual must also reach 120% of the
        # requirement (88560); 80000 < 88560 -> DENIED.
        assert south_decision["outcome"] == "DENIED"

        assert get_loan(west_loan["id"])["underwriting_status"] == "DENIED"
        assert get_loan(south_loan["id"])["underwriting_status"] == "DENIED"

    def test_residual_equality_boundary_passes(self, api):
        """PRD §3.4: "The decision `outcome` is `APPROVED` when the residual
        income is at least the requirement — equality passes"

        Design: Corner/calculations/residual_equality_boundary_passes
        """
        ctx = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 20000000},
            veteran_overrides={"full_name": "V Eq"},
        )
        # Inputs chosen so residual_income_cents == residual_required_cents
        # (SOUTH, family 4 -> 100300) AND dti_percent <= 41.00, so the
        # PRD's "equality passes" residual gate is the binding boundary.
        # other monthly = 224400/12 = 18700; residual = 169000-50000-18700
        # = 100300; dti = (50000+18700)/169000 = 40.65 <= 41.00.
        decision = validate_success(
            api.create_underwriting_decision(
                ctx["loan"]["id"],
                {
                    "gross_monthly_income_cents": 169000,
                    "new_housing_payment_cents": 50000,
                    "other_obligations_annual_cents": [224400],
                    "family_size": 4,
                    "region": "SOUTH",
                },
            ),
            expected_status=201,
        )
        assert decision["other_obligations_monthly_cents"] == 18700
        assert decision["residual_income_cents"] == 100300
        assert decision["residual_required_cents"] == 100300
        assert decision["outcome"] == "APPROVED"


class TestPartialEntitlementClose:
    def test_partial_entitlement_down_payment_shortfall(self, api):
        """PRD §3.4: "when the `loan_amount_cents` is no more than four times the
        account's `remaining_with_bonus_cents`, no additional down payment is
        required; otherwise the shortfall — the loan amount minus four times the
        remaining with-bonus entitlement, multiplied by 0.25 and rounded half up
        to whole cents — must be covered by the loan's `down_payment_cents`"
        PRD §3.4: "`entitlement_charged_cents` becomes the smaller of one quarter
        of the loan amount (rounded half up to whole cents) and the account's
        `remaining_with_bonus_cents`"

        Design: Corner/calculations/partial_entitlement_down_payment_shortfall
        """
        # First loan: $300,000 closed -> charged 7,500,000; remaining bonus 11,663,750.
        ctx = setup_closed_loan(price_cents=30000000)
        veteran_id = ctx["veteran"]["id"]
        coe_id = ctx["coe"]["id"]

        second = validate_success(
            api.create_loan(
                veteran_id,
                create_loan_payload(
                    coe_id, purchase_price_cents=50000000,
                    down_payment_cents=836250,
                ),
            ),
            expected_status=201,
        )
        # The first appraiser still has free capacity (default 3).
        appraisal = order_assigned_appraisal(second["id"], ctx["appraiser"])
        submit_value_issued_report(appraisal["id"], ctx["appraiser"]["id"], 50000000)
        approve_underwriting(second["id"], decision_overrides={
            "gross_monthly_income_cents": 900000,
            "new_housing_payment_cents": 300000,
        })

        closed = close_loan(second["id"], closing_date="2026-04-10",
                            first_payment_due_date="2026-06-01")
        assert closed["closing_status"] == "CLOSED"
        # charge = min(round_half_up(49163750 * 0.25), 11663750) = 11663750.
        assert closed["entitlement_charged_cents"] == 11663750
        account = get_entitlement_account(veteran_id)
        assert account["total_charged_cents"] == 19163750
        assert account["remaining_with_bonus_cents"] == 0
