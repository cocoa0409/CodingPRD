"""One-cent straddles of two named boundaries.

The HOEPA cap tier is selected from `total_loan_amount_cents`, so two loans one
cent apart in note amount land on opposite sides of the 2486600-cent boundary and
get caps that differ by more than the difference in their fees. The appraisal
variance tolerance is a two-decimal percentage produced by division, so a
one-cent move in the second appraised value is enough to cross 10.00 after
rounding.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import APPRAISAL_REVIEWER, LOAN_OFFICER, underwriter

INVESTOR = "INV-ATLAS"


def _fee_items_by_code(api, loan_file_id):
    rows = validate_success(api.list_fee_items(loan_file_id, LOAN_OFFICER))
    return {row["fee_code"]: row for row in rows}


def _two_loans_one_cent_apart(api):
    """Two files with an identical fee schedule, 2586600 and 2586500 cents.

    The 100000-cent origination charge is a financed prepaid finance charge, so
    each file's `total_loan_amount_cents` is its note amount less 100000: exactly
    the tier boundary for the first and one cent below it for the second.
    """
    program = fx.create_program(
        api, "BANK_STATEMENT_12MO", name="12-Month Bank Statement",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Kestrel Aoyama", fico_score=705, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=500000, age_years=44)
    uw = underwriter("uw-11")
    files = {}
    for label, amount in (("high", 2586600), ("low", 2586500)):
        loan_file = fx.create_loan_file(
            api, borrower["id"], program["id"], INVESTOR,
            loan_amount_cents=amount, property_value_cents=3600000,
            occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
            note_rate_pct=9.500, apor_pct=6.100, term_months=360,
            amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=8000,
            monthly_insurance_cents=2500, monthly_hoa_cents=0)
        fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
        # PRD 3.6 accepts fee items in every status except `DENIED`, and PRD 3.3
        # requires at least one before submission, so the schedule is built first.
        fx.create_fee_item(api, loan_file["id"], "ORIG-1PT", "ORIGINATION_POINTS",
                           100000, LOAN_OFFICER, prepaid_finance_charge_flag=True)
        fx.create_fee_item(api, loan_file["id"], "TITLE-AFF", "AFFILIATE_TITLE",
                           24330, LOAN_OFFICER)
        fx.create_fee_item(api, loan_file["id"], "ESCROW-TAX", "ESCROW_TAXES",
                           180000, LOAN_OFFICER, prepaid_finance_charge_flag=True)
        fx.submit_to_underwriting(api, loan_file["id"])
        files[label] = loan_file
    return files, uw


def test_a_total_loan_amount_exactly_on_the_tier_boundary_takes_the_five_percent_cap(api):
    """2486600 cents is inclusive on the large-loan side, and total == cap passes.

    PRD 3.6: "The tier boundary is inclusive on the large-loan side: a total loan amount
    of exactly 24,866 dollars uses the 5.00 percent cap, and one cent less falls into the
    small-loan branch." and "Step five compares strictly: `points_and_fees_test_result`
    becomes `FAIL` when `points_and_fees_total_cents` is greater than
    `points_and_fees_cap_cents`, and `PASS` otherwise".

    Design: Difficulty/boundary_precision_check/hoepa_tier_boundary_and_exact_cap_equality_at_one_cent
    """
    files, uw = _two_loans_one_cent_apart(api)

    tested = fx.run_points_and_fees_test(api, files["high"]["id"], uw)

    A.assert_money(tested["points_and_fees_total_cents"], 124330,
                   "points_and_fees_total_cents")
    A.assert_money(tested["total_loan_amount_cents"], 2486600,
                   "total_loan_amount_cents")
    # 5.00 percent of the step-three figure, never of the 2586600-cent note amount,
    # which would have produced 129330.
    A.assert_money(tested["points_and_fees_cap_cents"], 124330,
                   "points_and_fees_cap_cents")
    assert tested["points_and_fees_cap_cents"] != 129330
    A.assert_fields(tested, {"points_and_fees_test_result": "PASS"})
    A.assert_money(tested["pitia_monthly_cents"], 32250, "pitia_monthly_cents")
    A.assert_pct_2dp(tested["ltv_pct"], "71.85", "ltv_pct")
    A.assert_decimal_equals(tested["documented_reserves_months"], "15.50", 2,
                            "documented_reserves_months")

    # The prepaid escrow charge is excluded by category, so it moves neither sum.
    items = _fee_items_by_code(api, files["high"]["id"])
    A.assert_fields(items["ORIG-1PT"], {"inclusion_in_test": "INCLUDED"})
    A.assert_fields(items["TITLE-AFF"], {"inclusion_in_test": "INCLUDED"})
    A.assert_fields(items["ESCROW-TAX"], {"inclusion_in_test": "EXCLUDED"})


def test_one_cent_below_the_boundary_falls_to_the_flat_small_loan_cap(api):
    """The small-loan branch takes the lesser of 8.00 percent and the flat ceiling.

    PRD 3.6: "below that boundary, the cap is the lesser of 8.00 percent of
    `total_loan_amount_cents`, rounded half up to the cent, and a flat ceiling of 1,243
    dollars." and "Every other charge is `EXCLUDED`, and `ESCROW_TAXES` is always
    `EXCLUDED`."

    Design: Difficulty/boundary_precision_check/hoepa_tier_boundary_and_exact_cap_equality_at_one_cent
    """
    files, uw = _two_loans_one_cent_apart(api)

    tested = fx.run_points_and_fees_test(api, files["low"]["id"], uw)

    A.assert_money(tested["points_and_fees_total_cents"], 124330,
                   "points_and_fees_total_cents")
    A.assert_money(tested["total_loan_amount_cents"], 2486500,
                   "total_loan_amount_cents")
    # The flat 124300-cent ceiling beats the 198920-cent percentage figure.
    A.assert_money(tested["points_and_fees_cap_cents"], 124300,
                   "points_and_fees_cap_cents")
    A.assert_fields(tested, {"points_and_fees_test_result": "FAIL"})
    A.assert_money(tested["pitia_monthly_cents"], 32249, "pitia_monthly_cents")
    A.assert_pct_2dp(tested["ltv_pct"], "71.85", "ltv_pct")
    A.assert_decimal_equals(tested["documented_reserves_months"], "15.50", 2,
                            "documented_reserves_months")

    items = _fee_items_by_code(api, files["low"]["id"])
    A.assert_fields(items["ESCROW-TAX"], {"inclusion_in_test": "EXCLUDED"})


def _file_awaiting_its_second_decision(api, second_value_cents):
    """A 40000000-cent file with a 55000000 primary accepted and a second received."""
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=30000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Lorne Basin Capital LLC", fico_score=752,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=3000000,
        age_years=51)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=40000000, property_value_cents=55000000,
        occupancy="INVESTMENT", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=9.250, apor_pct=6.100, term_months=360,
        amortization_type="INTEREST_ONLY", monthly_taxes_cents=60000,
        monthly_insurance_cents=18000, monthly_hoa_cents=15000,
        gross_market_rent_cents=420000, lease_rent_cents=480000)
    uw = underwriter("uw-12")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 55000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    second = fx.order_valuation(api, loan_file["id"], "SECOND_APPRAISAL",
                                "2026-06-01T00:00:00Z", APPRAISAL_REVIEWER,
                                vendor_code="VND-BETA")
    fx.receive_valuation(api, second["id"], second_value_cents, APPRAISAL_REVIEWER)
    return loan_file, second, uw


def test_a_variance_of_exactly_ten_percent_clears_and_keeps_the_primary_value(api):
    """49997728 cents against 55000000 rounds to 10.00, which does not escalate.

    PRD 3.5: "a variance of exactly 10.00 percent clears" and "`reconciled_value_cents`
    becomes `primary_value_cents` and the primary dimension moves
    `PRIMARY_PENDING_REVIEW → PRIMARY_CLEARED`."

    Design: Difficulty/boundary_precision_check/appraisal_variance_escalation_boundary_at_one_cent
    """
    loan_file, second, uw = _file_awaiting_its_second_decision(api, 49997728)

    fx.accept_valuation(api, second["id"], APPRAISAL_REVIEWER)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_pct_2dp(review["variance_pct"], "10.00", "variance_pct")
    A.assert_fields(review, {"primary_review_status": "PRIMARY_CLEARED",
                             "second_valuation_status": "SECOND_RECONCILED"})
    A.assert_is_null(review, "escalation_reason")
    A.assert_money(review["reconciled_value_cents"], 55000000,
                   "reconciled_value_cents")
    A.assert_money(review["second_value_cents"], 49997728, "second_value_cents")

    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_pct_2dp(after["ltv_pct"], "72.73", "ltv_pct")
    A.assert_money(after["pitia_monthly_cents"], 401333, "pitia_monthly_cents")
    A.assert_ratio_4dp(after["dscr_ratio"], "1.1960", "dscr_ratio")


def test_one_cent_lower_on_the_second_value_escalates_and_rebases_ltv(api):
    """49997727 cents rounds to 10.01, which is strictly above the tolerance.

    PRD 3.5: "If `variance_pct` is strictly above 10.00 percent, the file is underwritten
    conservatively: `reconciled_value_cents` becomes the lower of the two values, the
    primary dimension moves `PRIMARY_PENDING_REVIEW → PRIMARY_ESCALATED`, and
    `escalation_reason` records `VARIANCE_ABOVE_TOLERANCE`."

    Design: Difficulty/boundary_precision_check/appraisal_variance_escalation_boundary_at_one_cent
    """
    loan_file, second, uw = _file_awaiting_its_second_decision(api, 49997727)

    fx.accept_valuation(api, second["id"], APPRAISAL_REVIEWER)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_pct_2dp(review["variance_pct"], "10.01", "variance_pct")
    A.assert_fields(review, {"primary_review_status": "PRIMARY_ESCALATED",
                             "second_valuation_status": "SECOND_RECONCILED",
                             "escalation_reason": "VARIANCE_ABOVE_TOLERANCE"})
    A.assert_money(review["reconciled_value_cents"], 49997727,
                   "reconciled_value_cents")

    # Only the value dimension moved: the payment and coverage ratio are untouched.
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_pct_2dp(after["ltv_pct"], "80.00", "ltv_pct")
    A.assert_money(after["pitia_monthly_cents"], 401333, "pitia_monthly_cents")
    A.assert_ratio_4dp(after["dscr_ratio"], "1.1960", "dscr_ratio")
