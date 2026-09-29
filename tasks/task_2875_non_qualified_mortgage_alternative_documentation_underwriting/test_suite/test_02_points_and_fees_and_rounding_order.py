"""Combinatorial formulas whose step order is observable.

The points-and-fees cap tier keyed off the figure step three produces, and the
per-month rounding placement inside bank-statement income.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import underwriter

INVESTOR = "INV-ATLAS"

STATEMENT_MONTHS = [
    ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", 12222221, 0),
    ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", 12222221, 0),
    ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 12500000, 277780),
]


def _bank_statement_program(api):
    return fx.create_program(
        api, "BANK_STATEMENT_12MO", name="12-Month Bank Statement",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)


def _small_loan_with_two_charges(api):
    """A 2586600-cent file in UNDERWRITING carrying the two pinned charges.

    The charges are attached before the submission because PRD 3.3 accepts a
    submission only once at least one ACTIVE fee item exists on the file, and
    PRD 3.6 allows a fee item to be added "in every loan-file status except
    `DENIED`".
    """
    program = _bank_statement_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Cyril Odom", fico_score=700, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=40000,
        verified_liquid_assets_cents=300000, age_years=44)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=2586600, property_value_cents=3600000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=3000,
        monthly_insurance_cents=1000, monthly_hoa_cents=0)
    uw = underwriter("uw-3")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    origination = fx.create_fee_item(
        api, loan_file["id"], "ORIG-1", "ORIGINATION_POINTS", 100000,
        paid_to_affiliate_flag=False, prepaid_finance_charge_flag=True,
        bona_fide_discount_flag=False)
    title = fx.create_fee_item(
        api, loan_file["id"], "TITLE-1", "AFFILIATE_TITLE", 24330,
        paid_to_affiliate_flag=True, prepaid_finance_charge_flag=False,
        bona_fide_discount_flag=False)
    fx.submit_to_underwriting(api, loan_file["id"])
    return loan_file, origination, title, uw


def _fee_items_by_code(api, loan_file_id, headers):
    rows = fx.validate_success(api.list_fee_items(loan_file_id, headers))
    return {row["fee_code"]: row for row in rows}


def test_points_and_fees_cap_tier_is_keyed_off_the_step_three_figure(api):
    """The cap comes from total_loan_amount_cents, not from loan_amount_cents.

    PRD 3.6: "Step three sums `amount_cents` over the included charges that also
    carry `prepaid_finance_charge_flag`, and sets `total_loan_amount_cents` to
    `loan_amount_cents` less that financed-prepaid sum. Step four selects the cap
    tier from the figure step three just produced: when `total_loan_amount_cents`
    is at or above 24,866 dollars, `points_and_fees_cap_cents` is 5.00 percent of
    `total_loan_amount_cents`, rounded half up to the cent".

    2586600 less the 100000 financed prepaid charge is 2486600, whose 5.00 percent
    is 124330 -- not the 129330 that keying the cap off loan_amount_cents produces.

    Design: Difficulty/combinatorial_formula/points_and_fees_cap_tier_circular_evaluation_order
    """
    loan_file, origination, title, uw = _small_loan_with_two_charges(api)

    tested = fx.run_points_and_fees_test(api, loan_file["id"], uw)

    A.assert_money(tested["points_and_fees_total_cents"], 124330,
                   "points_and_fees_total_cents")
    A.assert_money(tested["total_loan_amount_cents"], 2486600,
                   "total_loan_amount_cents")
    A.assert_money(tested["points_and_fees_cap_cents"], 124330,
                   "points_and_fees_cap_cents")
    assert tested["points_and_fees_cap_cents"] != 129330
    A.assert_fields(tested, {"points_and_fees_test_result": "PASS"})
    items = _fee_items_by_code(api, loan_file["id"], uw)
    A.assert_fields(items["ORIG-1"], {"inclusion_in_test": "INCLUDED"})
    A.assert_fields(items["TITLE-1"], {"inclusion_in_test": "INCLUDED"})


def test_voiding_the_prepaid_charge_moves_the_cap_with_the_step_three_figure(api):
    """Removing the financed prepaid charge raises both the base and the cap.

    PRD 3.6: "Voiding a charge requires a `void_reason`, moves it
    `ACTIVE → VOIDED`, and removes it from every aggregate" and "the cap tier and
    the pass-or-fail verdict of steps four and five are recomputed only once a test
    has already been run on the file".

    With the 100000-cent prepaid origination charge voided, no included charge is
    prepaid, so total_loan_amount_cents returns to the full 2586600 and the cap
    becomes 5.00 percent of that, 129330, over a remaining base of 24330.

    Design: Difficulty/combinatorial_formula/points_and_fees_cap_tier_circular_evaluation_order
    """
    loan_file, origination, title, uw = _small_loan_with_two_charges(api)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)

    fx.void_fee_item(api, origination["id"], uw, "Origination credit applied")

    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_money(after["points_and_fees_total_cents"], 24330,
                   "points_and_fees_total_cents")
    A.assert_money(after["total_loan_amount_cents"], 2586600,
                   "total_loan_amount_cents")
    A.assert_money(after["points_and_fees_cap_cents"], 129330,
                   "points_and_fees_cap_cents")
    A.assert_fields(after, {"points_and_fees_test_result": "PASS"})


def _calculated_worksheet(api):
    """One bank-statement worksheet with the three pinned months, calculated once."""
    program = _bank_statement_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Dara Whitfield", fico_score=720, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=120000,
        verified_liquid_assets_cents=4000000, age_years=47)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-4")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    worksheet = fx.create_worksheet(api, loan_file["id"], "BANK_STATEMENT",
                                    submitted["version"], uw,
                                    expense_factor_source="PROGRAM_DEFAULT")
    months = []
    for start, end, deposits, ineligible in STATEMENT_MONTHS:
        months.append(fx.attach_statement_month(
            api, worksheet["id"], start, end, deposits, uw,
            ineligible_transfer_cents=ineligible))
    calculated = fx.calculate_worksheet(api, worksheet["id"], uw)
    return calculated, months, uw


def test_net_deposit_total_rounds_each_month_before_summing(api):
    """Per-month rounding beats sum-then-round by exactly one cent.

    PRD 3.4: "`net_deposit_total_cents` is the sum over the included months of each
    month's `eligible_deposit_cents` multiplied by one hundred less the expense
    factor and divided by one hundred, **each month's product rounded half up to the
    cent before it enters the sum**" and "Applying the expense factor to the
    aggregate and rounding once at the end produces a different net deposit total
    and is explicitly not the rule".

    The three months net 6111111 + 6111111 + 6111110 = 18333332, where applying
    50.00 percent to the 36666662 aggregate once would yield 18333331.

    Design: Difficulty/combinatorial_formula/bank_statement_per_month_rounding_before_summation
    """
    calculated, months, uw = _calculated_worksheet(api)

    A.assert_money(months[2]["eligible_deposit_cents"], 12222220,
                   "eligible_deposit_cents")
    A.assert_money(calculated["eligible_deposit_total_cents"], 36666662,
                   "eligible_deposit_total_cents")
    A.assert_fields(calculated, {"included_month_count": 3})
    A.assert_money(calculated["net_deposit_total_cents"], 18333332,
                   "net_deposit_total_cents")
    assert calculated["net_deposit_total_cents"] != 18333331
    A.assert_fields(calculated, {"calculation_count": 1})


def test_gross_monthly_income_uses_the_fixed_program_divisor(api):
    """Three included months still divide by the program's twelve.

    PRD 3.4: "The divisor is the program's `statement_period_months` and is fixed:
    it does not shrink when months are excluded, and a month whose deposits were
    zero still consumes a slot. `gross_monthly_income_cents` is the eligible deposit
    total divided by that fixed divisor, rounded half up to the cent."

    36666662 over 12 is 3055555 after rounding, and the pinned net total over the
    same divisor gives monthly_qualifying_income_cents 1527778.

    Design: Difficulty/combinatorial_formula/bank_statement_per_month_rounding_before_summation
    """
    calculated, months, uw = _calculated_worksheet(api)

    A.assert_money(calculated["gross_monthly_income_cents"], 3055555,
                   "gross_monthly_income_cents")
    A.assert_money(calculated["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
