"""Dual-variant qualifying-income calculations.

Bank-statement expense-factor variants and the two coverage-ratio rent shapes.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import LOAN_OFFICER, underwriter

INVESTOR = "INV-ATLAS"

# Three adjacent statement months; the third carries an ineligible transfer, so
# its eligible deposits are 12500000 - 277780 = 12222220 cents.
STATEMENT_MONTHS = [
    ("2026-04-01T00:00:00Z", "2026-05-01T00:00:00Z", 12222221, 0),
    ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", 12222221, 0),
    ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 12500000, 277780),
]


def _bank_statement_program(api):
    return fx.create_program(
        api, "BANK_STATEMENT_12MO",
        name="12-Month Bank Statement",
        statement_period_months=12,
        default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00,
        max_ltv_pct=80.00,
        min_fico=660,
        min_reserves_months=6,
        max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False,
    )


def _bank_statement_file(api):
    """A 60000000-cent bank-statement file sitting in UNDERWRITING."""
    program = _bank_statement_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Ana Ruiz", fico_score=720, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=120000,
        verified_liquid_assets_cents=4000000, age_years=47)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    # A submission needs at least one ACTIVE fee item; an ESCROW_TAXES charge is
    # always EXCLUDED from the points-and-fees test, so it perturbs no total.
    fx.attach_escrow_fee(api, loan_file["id"])
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    return loan_file, submitted, uw


def _worksheet_with_months(api, loan_file_id, loan_file_version, uw, **overrides):
    worksheet = fx.create_worksheet(api, loan_file_id, "BANK_STATEMENT",
                                    loan_file_version, uw, **overrides)
    for start, end, deposits, ineligible in STATEMENT_MONTHS:
        fx.attach_statement_month(api, worksheet["id"], start, end, deposits, uw,
                                  ineligible_transfer_cents=ineligible)
    return worksheet


def test_bank_statement_program_default_factor_variant(api):
    """The PROGRAM_DEFAULT variant nets each month before summing.

    PRD 3.4: "The expense factor actually used is stored in
    `expense_factor_pct_applied` and is the program's `default_expense_factor_pct`
    when `expense_factor_source` is `PROGRAM_DEFAULT`, and the worksheet's
    `cpa_expense_factor_pct` when it is `CPA_LETTER`." and "`net_deposit_total_cents`
    is the sum over the included months of each month's `eligible_deposit_cents`
    multiplied by one hundred less the expense factor and divided by one hundred,
    **each month's product rounded half up to the cent before it enters the sum**".

    At 50.00 percent the three months net 6111111 + 6111111 + 6111110 = 18333332,
    and 18333332 / 12 = 1527778 after the pinned rounding.

    Design: Difficulty/dual_variant_calc/bank_statement_expense_factor_variant_divergence
    """
    loan_file, submitted, uw = _bank_statement_file(api)
    worksheet = _worksheet_with_months(api, loan_file["id"], submitted["version"], uw,
                                       expense_factor_source="PROGRAM_DEFAULT")

    calculated = fx.calculate_worksheet(api, worksheet["id"], uw)

    A.assert_money(calculated["eligible_deposit_total_cents"], 36666662,
                   "eligible_deposit_total_cents")
    A.assert_pct_2dp(calculated["expense_factor_pct_applied"], "50.00",
                     "expense_factor_pct_applied")
    A.assert_fields(calculated, {"variant_applied": "PROGRAM_DEFAULT_FACTOR"})
    A.assert_money(calculated["net_deposit_total_cents"], 18333332,
                   "net_deposit_total_cents")
    A.assert_money(calculated["gross_monthly_income_cents"], 3055555,
                   "gross_monthly_income_cents")
    A.assert_money(calculated["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")


def test_bank_statement_cpa_letter_factor_variant_diverges(api):
    """The CPA_LETTER variant on byte-identical deposits yields a different income.

    PRD 3.4: "`variant_applied` records `PROGRAM_DEFAULT_FACTOR` or
    `CPA_LETTER_FACTOR` according to the source, so the identical set of statement
    months yields a different qualifying income under a CPA letter than under the
    program default."

    At 32.50 percent the same three months net 8249999 + 8249999 + 8249999 =
    24749997 and 24749997 / 12 rounds to 2062500 -- 534722 cents above the
    1527778 the program default produces on the same rows.

    Design: Difficulty/dual_variant_calc/bank_statement_expense_factor_variant_divergence
    """
    loan_file, submitted, uw = _bank_statement_file(api)
    worksheet_default = _worksheet_with_months(
        api, loan_file["id"], submitted["version"], uw,
        expense_factor_source="PROGRAM_DEFAULT")
    refreshed = fx.get_loan_file(api, loan_file["id"], uw)
    worksheet_cpa = _worksheet_with_months(
        api, loan_file["id"], refreshed["version"], uw,
        expense_factor_source="CPA_LETTER", cpa_expense_factor_pct=32.50)

    calculated_default = fx.calculate_worksheet(api, worksheet_default["id"], uw)
    calculated_cpa = fx.calculate_worksheet(api, worksheet_cpa["id"], uw)

    A.assert_money(calculated_cpa["eligible_deposit_total_cents"], 36666662,
                   "eligible_deposit_total_cents")
    A.assert_pct_2dp(calculated_cpa["expense_factor_pct_applied"], "32.50",
                     "expense_factor_pct_applied")
    A.assert_fields(calculated_cpa, {"variant_applied": "CPA_LETTER_FACTOR"})
    A.assert_money(calculated_cpa["net_deposit_total_cents"], 24749997,
                   "net_deposit_total_cents")
    A.assert_money(calculated_cpa["monthly_qualifying_income_cents"], 2062500,
                   "monthly_qualifying_income_cents")
    assert (calculated_cpa["monthly_qualifying_income_cents"]
            - calculated_default["monthly_qualifying_income_cents"]) == 534722


def test_worksheet_calculation_publishes_no_income_to_the_loan_file(api):
    """Calculating leaves the loan file's qualifying income untouched.

    PRD 3.4: "Calculation touches nothing on the loan file; the recalculated
    figures stay inside the worksheet until it is accepted."

    Design: Difficulty/dual_variant_calc/bank_statement_expense_factor_variant_divergence
    """
    loan_file, submitted, uw = _bank_statement_file(api)
    worksheet = _worksheet_with_months(api, loan_file["id"], submitted["version"], uw,
                                       expense_factor_source="PROGRAM_DEFAULT")

    calculated = fx.calculate_worksheet(api, worksheet["id"], uw)

    A.assert_money(calculated["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_money(after["qualifying_income_monthly_cents"], 0,
                   "qualifying_income_monthly_cents")


def _dscr_program(api):
    return fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)


def _dscr_file(api, program_id, borrower_id, **overrides):
    payload = dict(
        loan_amount_cents=40000000, purchase_price_cents=60000000,
        property_value_cents=60000000, occupancy="INVESTMENT", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=9.250, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=18000,
        monthly_hoa_cents=15000, gross_market_rent_cents=420000,
    )
    payload.update(overrides)
    return fx.create_loan_file(api, borrower_id, program_id, INVESTOR, **payload)


def test_dscr_lease_in_place_shape_uses_contract_rent_capped_at_market(api):
    """A lease in place drives the coverage ratio off contract rent.

    PRD 3.3: "When `lease_rent_cents` is present and `occupancy` is `INVESTMENT`,
    the qualifying rent is the lesser of the contract rent and 120 percent of
    `gross_market_rent_cents` rounded half up to the cent, and `dscr_ratio` records
    the `LEASE_IN_PLACE` shape".

    Contract rent 480000 is below 120 percent of 420000 (504000), and the
    interest-only payment is 401333, so the ratio is 480000 / 401333 = 1.1960.

    Design: Difficulty/dual_variant_calc/dscr_lease_in_place_versus_market_rent_variant_divergence
    """
    program = _dscr_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Beltran Holdings LLC", fico_score=740,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=3000000,
        age_years=51)
    loan_file = _dscr_file(api, program["id"], borrower["id"],
                           lease_rent_cents=480000)

    selected = fx.select_doc_type(api, loan_file["id"], "DSCR", underwriter("uw-2"))

    A.assert_money(selected["pitia_monthly_cents"], 401333, "pitia_monthly_cents")
    A.assert_ratio_4dp(selected["dscr_ratio"], "1.1960", "dscr_ratio")
    A.assert_money(selected["qualifying_income_monthly_cents"], 0,
                   "qualifying_income_monthly_cents")
    A.assert_is_null(selected, "dti_pct")


def test_dscr_market_rent_shape_applies_the_vacancy_allowance(api):
    """With no lease the same property qualifies on 75 percent of market rent.

    PRD 3.3: "Otherwise the qualifying rent is 75 percent of
    `gross_market_rent_cents` rounded half up to the cent, reflecting a vacancy
    allowance, and the `MARKET_RENT_1007` shape applies" and "materially lower on the
    same property and payment."

    On the identical 40000000-cent interest-only file the ratio is
    315000 / 401333 = 0.7849, so the same property fails the program's min_dscr of
    1.1000 that the lease shape clears at 1.1960.

    Design: Difficulty/dual_variant_calc/dscr_lease_in_place_versus_market_rent_variant_divergence
    """
    program = _dscr_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Beltran Holdings LLC", fico_score=740,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=3000000,
        age_years=51)
    lease_file = _dscr_file(api, program["id"], borrower["id"],
                            lease_rent_cents=480000)
    market_file = _dscr_file(api, program["id"], borrower["id"])
    uw = underwriter("uw-2")

    lease_selected = fx.select_doc_type(api, lease_file["id"], "DSCR", uw)
    market_selected = fx.select_doc_type(api, market_file["id"], "DSCR", uw)

    A.assert_money(market_selected["pitia_monthly_cents"], 401333,
                   "pitia_monthly_cents")
    A.assert_ratio_4dp(market_selected["dscr_ratio"], "0.7849", "dscr_ratio")
    A.assert_ratio_4dp(lease_selected["dscr_ratio"], "1.1960", "dscr_ratio")
    assert A.as_decimal(market_selected["dscr_ratio"]) < A.as_decimal("1.1000")
    assert A.as_decimal(lease_selected["dscr_ratio"]) >= A.as_decimal("1.1000")
