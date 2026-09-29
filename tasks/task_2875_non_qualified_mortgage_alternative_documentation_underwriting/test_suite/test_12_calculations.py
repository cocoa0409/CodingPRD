"""Calculation corners: the depletion waterfall, the two P and L roundings, the
points-and-fees classification matrix, the lien-dependent higher-priced
thresholds, the second-valuation comparators, the audit weight table and the
propagation of overlay resolution into the delivery gate.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    credit_committee,
)

INVESTOR = "INV-ALPHA"


def _depletion_program(api, **overrides):
    payload = dict(
        name="Asset Depletion 84", depletion_horizon_months=84, max_ltv_pct=80.00,
        min_fico=660, min_reserves_months=6, max_dti_pct=60.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    payload.update(overrides)
    return fx.create_program(api, "ASSET_DEPLETION", **payload)


def _pnl_program(api, **overrides):
    payload = dict(
        name="CPA P and L", statement_period_months=12,
        default_expense_factor_pct=50.00, min_expense_factor_pct=25.00,
        max_ltv_pct=80.00, min_fico=660, min_reserves_months=3,
        max_dti_pct=55.00, min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    payload.update(overrides)
    return fx.create_program(api, "PROFIT_AND_LOSS", **payload)


def _dscr_program(api, **overrides):
    payload = dict(
        name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    payload.update(overrides)
    return fx.create_program(api, "DSCR", **payload)


def _thirty_million_file(api, borrower_id, program_id, **overrides):
    """The 30000000-cent fully-amortizing purchase whose PITIA is 274764."""
    payload = dict(
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    payload.update(overrides)
    return fx.create_loan_file(api, borrower_id, program_id, INVESTOR, **payload)


def _sixty_million_pnl_file(api, borrower_id, program_id, **overrides):
    """The 60000000-cent interest-only purchase whose PITIA is 750000."""
    payload = dict(
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=13.000, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=78000, monthly_insurance_cents=22000)
    payload.update(overrides)
    return fx.create_loan_file(api, borrower_id, program_id, INVESTOR, **payload)


def _dscr_investment_file(api, borrower_id, program_id, **overrides):
    """The 60000000-cent interest-only DSCR purchase whose PITIA is 517500."""
    payload = dict(
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=8.750, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000)
    payload.update(overrides)
    return fx.create_loan_file(api, borrower_id, program_id, INVESTOR, **payload)


def _submit(api, loan_file_id, doc_type, **fee):
    """Select the documentation type, attach one fee item, and submit."""
    fx.select_doc_type(api, loan_file_id, doc_type, UNDERWRITER)
    if fee:
        fx.create_fee_item(api, loan_file_id, fee["fee_code"],
                           fee["fee_category"], fee["amount_cents"], LOAN_OFFICER,
                           prepaid_finance_charge_flag=True)
    else:
        fx.attach_escrow_fee(api, loan_file_id)
    return fx.submit_to_underwriting(api, loan_file_id)


def _origination_fee(api, loan_file_id):
    return fx.create_fee_item(api, loan_file_id, "F-ORIG", "ORIGINATION_POINTS",
                              600000, LOAN_OFFICER,
                              prepaid_finance_charge_flag=True)


def _depletion_worksheet(api, loan_file_id, checking, brokerage, retirement):
    version = fx.get_loan_file(api, loan_file_id, UNDERWRITER)["version"]
    return fx.create_worksheet(
        api, loan_file_id, "ASSET_DEPLETION", version, UNDERWRITER,
        asset_bucket_checking_cents=checking,
        asset_bucket_brokerage_cents=brokerage,
        asset_bucket_retirement_cents=retirement)


def _pnl_worksheet(api, loan_file_id, net_income_cents, period_months=12):
    version = fx.get_loan_file(api, loan_file_id, UNDERWRITER)["version"]
    return fx.create_worksheet(
        api, loan_file_id, "PROFIT_AND_LOSS", version, UNDERWRITER,
        p_and_l_net_income_cents=net_income_cents,
        p_and_l_period_months=period_months)


def test_depletion_haircuts_round_per_bucket_before_the_reserve_subtraction(api):
    """Every intermediate of the depletion waterfall is pinned.

    PRD 3.4: "`eligible_assets_after_haircut_cents` is the sum of those three
    already-rounded components — summing the raw products and rounding once at the
    end yields a different figure and is not the rule." and "Required reserves are
    the program's `min_reserves_months` multiplied by the file's current
    `pitia_monthly_cents`, and `depletable_assets_cents` is the eligible assets less
    those required reserves, floored at zero." and "`gross_monthly_income_cents` is
    the depletable assets divided by the program's `depletion_horizon_months`,
    rounded half up to the cent in a single rounding, and
    `monthly_qualifying_income_cents` equals it — no ownership scaling applies to a
    depletion file."
    PRD 3.4: "`eligible_deposit_total_cents`, `net_deposit_total_cents` and
    `included_month_count` are 0 for any non-bank-statement worksheet" and
    "`expense_factor_pct_applied` is null for any non-bank-statement worksheet."
    PRD 3.4: "Calculation touches nothing on the loan file; the recalculated figures
    stay inside the worksheet until it is accepted."

    15000000 at 100 percent plus 20000003 from 22222226 at 90 percent plus 21000001
    from 30000002 at 70 percent is 56000004; less six months of the 274764-cent
    payment it is 54351420, and 54351420 / 84 rounds to 647041.

    Design: Corner/calculations/corner_asset_depletion_bucket_haircuts_and_reserve_subtraction
    """
    program = _depletion_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Owen Reyes", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)
    loan_file = _thirty_million_file(api, borrower["id"], program["id"])
    _submit(api, loan_file["id"], "ASSET_DEPLETION")
    worksheet = _depletion_worksheet(api, loan_file["id"],
                                    15000000, 22222226, 30000002)

    calculated = fx.calculate_worksheet(api, worksheet["id"], UNDERWRITER)

    A.assert_money(calculated["eligible_assets_after_haircut_cents"], 56000004,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(calculated["depletable_assets_cents"], 54351420,
                   "depletable_assets_cents")
    A.assert_money(calculated["gross_monthly_income_cents"], 647041,
                   "gross_monthly_income_cents")
    A.assert_money(calculated["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")
    A.assert_fields(calculated, {"variant_applied": "ASSET_DEPLETION_STANDARD",
                                 "status": "CALCULATED",
                                 "calculation_count": 1,
                                 "included_month_count": 0})
    A.assert_is_null(calculated, "expense_factor_pct_applied")
    A.assert_money(calculated["net_deposit_total_cents"], 0,
                   "net_deposit_total_cents")
    A.assert_money(calculated["eligible_deposit_total_cents"], 0,
                   "eligible_deposit_total_cents")

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_money(after["pitia_monthly_cents"], 274764, "pitia_monthly_cents")
    A.assert_money(after["qualifying_income_monthly_cents"], 0,
                   "qualifying_income_monthly_cents")


def test_retirement_access_factor_switches_at_age_sixty_inclusively(api):
    """Identical buckets, one year of age apart, diverge by 107143 cents a month.

    PRD 3.4: "The retirement access factor is a full 100 percent for a borrower whose
    `age_years` is at least 60, and 70 percent otherwise." and "`variant_applied` is
    `ASSET_DEPLETION_STANDARD`; the older-borrower branch raises both the
    eligible-asset total and the monthly figure relative to the haircut branch, on
    identical balances."

    Design: Corner/calculations/corner_asset_depletion_retirement_variant_selected_by_age
    """
    program = _depletion_program(api)
    younger = fx.create_borrower(
        api, legal_name="Nina Fifty Nine", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=59)
    older = fx.create_borrower(
        api, legal_name="Saul Sixty", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=60)
    young_file = _thirty_million_file(api, younger["id"], program["id"])
    old_file = _thirty_million_file(api, older["id"], program["id"])
    _submit(api, young_file["id"], "ASSET_DEPLETION")
    _submit(api, old_file["id"], "ASSET_DEPLETION")
    young_ws = _depletion_worksheet(api, young_file["id"],
                                    15000000, 22222226, 30000002)
    old_ws = _depletion_worksheet(api, old_file["id"],
                                  15000000, 22222226, 30000002)

    young = fx.calculate_worksheet(api, young_ws["id"], UNDERWRITER)
    old = fx.calculate_worksheet(api, old_ws["id"], UNDERWRITER)

    A.assert_money(young["eligible_assets_after_haircut_cents"], 56000004,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(young["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")
    A.assert_money(old["eligible_assets_after_haircut_cents"], 65000005,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(old["depletable_assets_cents"], 63351421,
                   "depletable_assets_cents")
    A.assert_money(old["monthly_qualifying_income_cents"], 754184,
                   "monthly_qualifying_income_cents")
    assert (old["monthly_qualifying_income_cents"]
            - young["monthly_qualifying_income_cents"]) == 107143
    A.assert_fields(young, {"variant_applied": "ASSET_DEPLETION_STANDARD"})
    A.assert_fields(old, {"variant_applied": "ASSET_DEPLETION_STANDARD"})


def test_amortization_type_selects_the_payment_branch_at_creation(api):
    """One field apart, the same loan is 252500 interest-only and 274764 amortizing.

    PRD 3.3: "Two computations run at creation." and "On an `INTEREST_ONLY` file the
    principal-and-interest component is the loan amount multiplied by that monthly
    rate, rounded half up to the cent — the amortization factor is skipped entirely,
    so this branch always yields a strictly lower payment than the amortizing branch
    on the same inputs." and "`pitia_monthly_cents` is then that
    principal-and-interest component plus `monthly_taxes_cents` plus
    `monthly_insurance_cents` plus `monthly_hoa_cents`." and "`dti_pct` is null
    whenever `qualifying_income_monthly_cents` is 0".

    Design: Corner/calculations/corner_pitia_amortization_branch_selected_by_loan_field
    """
    program = _pnl_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Pia Amort", fico_score=700, self_employed_flag=True,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)

    interest_only = _thirty_million_file(api, borrower["id"], program["id"],
                                         amortization_type="INTEREST_ONLY")
    amortizing = _thirty_million_file(api, borrower["id"], program["id"],
                                      amortization_type="FULLY_AMORTIZING")

    A.assert_money(interest_only["pitia_monthly_cents"], 252500,
                   "pitia_monthly_cents")
    A.assert_money(amortizing["pitia_monthly_cents"], 274764,
                   "pitia_monthly_cents")
    assert (amortizing["pitia_monthly_cents"]
            - interest_only["pitia_monthly_cents"]) == 22264
    for row in (interest_only, amortizing):
        A.assert_pct_2dp(row["ltv_pct"], "75.00", "ltv_pct")
        A.assert_fields(row, {"status": "DRAFT"})
        A.assert_is_null(row, "dti_pct")


def test_profit_and_loss_divides_by_the_declared_period_not_a_constant(api):
    """The divisor is the worksheet's own declared period, and no other aggregate moves.

    PRD 3.4: "`gross_monthly_income_cents` is `p_and_l_net_income_cents` divided by
    `p_and_l_period_months`, rounded half up to the cent, and
    `monthly_qualifying_income_cents` is that figure multiplied by the borrower's
    `entity_ownership_pct` and divided by one hundred, rounded half up to the cent."
    and "No expense factor participates, because expenses are already inside the
    CPA's statement, so `expense_factor_pct_applied` stays null; `variant_applied` is
    `PL_NET_INCOME`." and "`eligible_assets_after_haircut_cents` and
    `depletable_assets_cents` are 0 for any non-depletion worksheet"

    Design: Corner/calculations/corner_profit_and_loss_net_income_over_declared_period
    """
    program = _pnl_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Paula Ledger", fico_score=700, self_employed_flag=True,
        monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=4000000, age_years=45)
    loan_file = _sixty_million_pnl_file(api, borrower["id"], program["id"])
    _submit(api, loan_file["id"], "PROFIT_AND_LOSS")
    worksheet = _pnl_worksheet(api, loan_file["id"], 18333336)

    calculated = fx.calculate_worksheet(api, worksheet["id"], UNDERWRITER)

    A.assert_money(calculated["gross_monthly_income_cents"], 1527778,
                   "gross_monthly_income_cents")
    A.assert_money(calculated["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
    A.assert_fields(calculated, {"variant_applied": "PL_NET_INCOME",
                                 "status": "CALCULATED",
                                 "calculation_count": 1,
                                 "included_month_count": 0})
    A.assert_money(calculated["eligible_deposit_total_cents"], 0,
                   "eligible_deposit_total_cents")
    A.assert_money(calculated["net_deposit_total_cents"], 0,
                   "net_deposit_total_cents")
    A.assert_money(calculated["eligible_assets_after_haircut_cents"], 0,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(calculated["depletable_assets_cents"], 0,
                   "depletable_assets_cents")
    A.assert_is_null(calculated, "expense_factor_pct_applied")


def test_ownership_share_scales_the_already_rounded_monthly_figure(api):
    """Two roundings, not one: 1145834 rather than the collapsed 1145833.

    PRD 3.4: "`gross_monthly_income_cents` is `p_and_l_net_income_cents` divided by
    `p_and_l_period_months`, rounded half up to the cent, and
    `monthly_qualifying_income_cents` is that figure multiplied by the borrower's
    `entity_ownership_pct` and divided by one hundred, rounded half up to the cent."

    18333330 / 12 is 1527777.5, which rounds half up to 1527778, and 75 percent of
    that is 1145833.5, which rounds half up to 1145834. Collapsing the two steps into
    18333330 * 0.75 / 12 = 1145833.125 would report 1145833.

    Design: Corner/calculations/corner_profit_and_loss_rounds_twice_not_once
    """
    program = _pnl_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Quinn Partial", fico_score=700, self_employed_flag=True,
        entity_ownership_pct=75.00, monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=4000000, age_years=45)
    loan_file = _sixty_million_pnl_file(api, borrower["id"], program["id"])
    _submit(api, loan_file["id"], "PROFIT_AND_LOSS")
    worksheet = _pnl_worksheet(api, loan_file["id"], 18333330)

    calculated = fx.calculate_worksheet(api, worksheet["id"], UNDERWRITER)

    A.assert_money(calculated["gross_monthly_income_cents"], 1527778,
                   "gross_monthly_income_cents")
    A.assert_money(calculated["monthly_qualifying_income_cents"], 1145834,
                   "monthly_qualifying_income_cents")
    assert calculated["monthly_qualifying_income_cents"] != 1145833
    A.assert_fields(calculated, {"variant_applied": "PL_NET_INCOME",
                                 "status": "CALCULATED"})


def test_a_second_acceptance_replaces_the_ledger_rather_than_layering_on_it(api):
    """The file adopts worksheet B's figure outright; A keeps its own untouched.

    PRD 3.4: "Acceptance then cascades: any other worksheet on the same loan file
    that was in `ACCEPTED` moves to `SUPERSEDED`" and "the accepted worksheet's
    `monthly_qualifying_income_cents` is copied onto the file's
    `qualifying_income_monthly_cents`; the file's `dti_pct`,
    `residual_income_cents` and `documented_reserves_months` are recomputed; the
    file's `atr_documentation_status` is reset to `INCOMPLETE` and its
    `safe_harbor_class` to `NOT_EVALUATED`" and "the loan file's `version` increments
    by one."
    PRD 3.3: "`documented_reserves_months` is the borrower's
    `verified_liquid_assets_cents` divided by `pitia_monthly_cents`, rounded half up
    to two decimals"

    Design: Corner/calculations/corner_second_accepted_worksheet_reconciles_the_loan_file_ledger
    """
    program = _depletion_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Rita Ledger", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)
    loan_file = _thirty_million_file(api, borrower["id"], program["id"])
    _submit(api, loan_file["id"], "ASSET_DEPLETION")
    worksheet_a = _depletion_worksheet(api, loan_file["id"],
                                       15000000, 22222226, 30000002)
    fx.calculate_worksheet(api, worksheet_a["id"], UNDERWRITER)
    fx.accept_worksheet(api, worksheet_a["id"], UNDERWRITER)
    worksheet_b = _depletion_worksheet(api, loan_file["id"],
                                       15000000, 22222226, 40000002)
    fx.calculate_worksheet(api, worksheet_b["id"], UNDERWRITER)

    before = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_money(before["qualifying_income_monthly_cents"], 647041,
                   "qualifying_income_monthly_cents")
    A.assert_pct_2dp(before["dti_pct"], "56.37", "dti_pct")
    A.assert_money(before["residual_income_cents"], 282277,
                   "residual_income_cents")
    A.assert_decimal_equals(before["documented_reserves_months"], "7.28", 2,
                            "documented_reserves_months")

    accepted = fx.accept_worksheet(api, worksheet_b["id"], UNDERWRITER)

    A.assert_fields(accepted, {"status": "ACCEPTED"})
    A.assert_money(accepted["monthly_qualifying_income_cents"], 730374,
                   "monthly_qualifying_income_cents")
    superseded = validate_success(api.get_worksheet(worksheet_a["id"], UNDERWRITER))
    A.assert_fields(superseded, {"status": "SUPERSEDED"})
    A.assert_money(superseded["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_money(after["qualifying_income_monthly_cents"], 730374,
                   "qualifying_income_monthly_cents")
    A.assert_pct_2dp(after["dti_pct"], "49.94", "dti_pct")
    A.assert_money(after["residual_income_cents"], 365610,
                   "residual_income_cents")
    A.assert_decimal_equals(after["documented_reserves_months"], "7.28", 2,
                            "documented_reserves_months")
    A.assert_fields(after, {"atr_documentation_status": "INCOMPLETE",
                            "safe_harbor_class": "NOT_EVALUATED"})
    assert after["version"] > before["version"]


def test_fee_classification_matrix_selects_the_points_and_fees_input_set(api):
    """Eight lines totalling 1475000 contribute only 895000, per category and flag.

    PRD 3.6: "A charge is `INCLUDED` when its `fee_category` is `ORIGINATION_POINTS`,
    `AFFILIATE_TITLE`, `PMI_UPFRONT`, `PREPAYMENT_PENALTY` or
    `LOAN_LEVEL_PRICE_ADJUSTMENT`; a `DISCOUNT_POINTS` charge is `INCLUDED` only when
    `bona_fide_discount_flag` is false, since bona fide discount points fall outside
    the test; a `THIRD_PARTY_UNAFFILIATED` charge is `INCLUDED` only when
    `paid_to_affiliate_flag` is true, because an affiliate retaining the money pulls
    the charge back in." and "Every other charge is `EXCLUDED`, and `ESCROW_TAXES` is
    always `EXCLUDED`." and "Step three sums `amount_cents` over the included charges
    that also carry `prepaid_finance_charge_flag`, and sets `total_loan_amount_cents`
    to `loan_amount_cents` less that financed-prepaid sum."

    Design: Corner/calculations/corner_points_and_fees_classification_matrix_selects_the_input_set
    """
    program = _dscr_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Felix Schedule", fico_score=700,
        monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=5000000, age_years=50)
    loan_file = _dscr_investment_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)
    _origination_fee(api, loan_file["id"])
    fx.create_fee_item(api, loan_file["id"], "F-DISC-BF", "DISCOUNT_POINTS",
                       300000, LOAN_OFFICER, bona_fide_discount_flag=True)
    fx.create_fee_item(api, loan_file["id"], "F-DISC-NBF", "DISCOUNT_POINTS",
                       150000, LOAN_OFFICER, bona_fide_discount_flag=False)
    fx.create_fee_item(api, loan_file["id"], "F-TITLE", "AFFILIATE_TITLE",
                       80000, LOAN_OFFICER)
    fx.create_fee_item(api, loan_file["id"], "F-PMI", "PMI_UPFRONT",
                       20000, LOAN_OFFICER)
    fx.create_fee_item(api, loan_file["id"], "F-3P-AFF", "THIRD_PARTY_UNAFFILIATED",
                       45000, LOAN_OFFICER, paid_to_affiliate_flag=True)
    fx.create_fee_item(api, loan_file["id"], "F-3P-UNAFF",
                       "THIRD_PARTY_UNAFFILIATED", 30000, LOAN_OFFICER)
    fx.create_fee_item(api, loan_file["id"], "F-ESCROW", "ESCROW_TAXES",
                       250000, LOAN_OFFICER)
    fx.submit_to_underwriting(api, loan_file["id"])

    tested = fx.run_points_and_fees_test(api, loan_file["id"], UNDERWRITER)

    A.assert_money(tested["points_and_fees_total_cents"], 895000,
                   "points_and_fees_total_cents")
    assert tested["points_and_fees_total_cents"] != 1475000
    A.assert_money(tested["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")
    A.assert_money(tested["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_fields(tested, {"points_and_fees_test_result": "PASS"})

    rows = validate_success(api.list_fee_items(loan_file["id"], UNDERWRITER))
    inclusion = {row["fee_code"]: row["inclusion_in_test"] for row in rows}
    assert inclusion == {"F-ORIG": "INCLUDED",
                         "F-DISC-BF": "EXCLUDED",
                         "F-DISC-NBF": "INCLUDED",
                         "F-TITLE": "INCLUDED",
                         "F-PMI": "INCLUDED",
                         "F-3P-AFF": "INCLUDED",
                         "F-3P-UNAFF": "EXCLUDED",
                         "F-ESCROW": "EXCLUDED"}, inclusion


def test_the_higher_priced_threshold_is_selected_by_lien_position(api):
    """One spread of 6.900 classifies a first lien and a second lien differently.

    PRD 3.6: "`rate_spread_pct` is again `note_rate_pct` less `apor_pct`, rounded half
    up to three decimals, and the applicable higher-priced threshold is 6.500 percent
    when `lien_position` is `FIRST` and 8.500 percent when it is `SECOND`." and
    "Otherwise, if `rate_spread_pct` is strictly greater than the applicable
    threshold, it becomes `HIGHER_PRICED_NO_PRESUMPTION` — a spread exactly equal to
    the threshold does not trip this branch. Otherwise it becomes
    `ATR_DOCUMENTED_NO_SAFE_HARBOR`." and "No qualified-mortgage safe harbour is ever
    granted by this platform: `ATR_DOCUMENTED_NO_SAFE_HARBOR` is the best attainable
    classification."

    Design: Corner/calculations/corner_higher_priced_spread_threshold_differs_by_lien_position
    """
    program = _pnl_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Lena Spread", fico_score=700, self_employed_flag=True,
        monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=4000000, age_years=45)
    first = _sixty_million_pnl_file(api, borrower["id"], program["id"],
                                    lien_position="FIRST")
    second = _sixty_million_pnl_file(api, borrower["id"], program["id"],
                                     lien_position="SECOND")
    for loan_file in (first, second):
        fx.select_doc_type(api, loan_file["id"], "PROFIT_AND_LOSS", UNDERWRITER)
        _origination_fee(api, loan_file["id"])
        fx.submit_to_underwriting(api, loan_file["id"])
        worksheet = _pnl_worksheet(api, loan_file["id"], 18333336)
        fx.calculate_worksheet(api, worksheet["id"], UNDERWRITER)
        fx.accept_worksheet(api, worksheet["id"], UNDERWRITER)
        fx.run_points_and_fees_test(api, loan_file["id"], UNDERWRITER)

    first_determined = fx.run_atr_determination(api, first["id"], UNDERWRITER)
    second_determined = fx.run_atr_determination(api, second["id"], UNDERWRITER)

    A.assert_pct_3dp(first_determined["rate_spread_pct"], "6.900",
                     "rate_spread_pct")
    A.assert_fields(first_determined,
                    {"atr_documentation_status": "DOCUMENTED",
                     "safe_harbor_class": "HIGHER_PRICED_NO_PRESUMPTION"})
    A.assert_pct_3dp(second_determined["rate_spread_pct"], "6.900",
                     "rate_spread_pct")
    A.assert_fields(second_determined,
                    {"atr_documentation_status": "DOCUMENTED",
                     "safe_harbor_class": "ATR_DOCUMENTED_NO_SAFE_HARBOR"})
    for row in (first_determined, second_determined):
        A.assert_pct_2dp(row["dti_pct"], "49.09", "dti_pct")
        A.assert_money(row["residual_income_cents"], 777778,
                       "residual_income_cents")
        A.assert_money(row["pitia_monthly_cents"], 750000, "pitia_monthly_cents")


def test_second_valuation_triggers_use_opposite_comparators(api):
    """LTV is a strict comparison; the loan-amount trigger is inclusive.

    PRD 3.5: "`second_valuation_required` is true when any one of three conditions
    holds: the file's `ltv_pct` is strictly above the program's
    `second_valuation_ltv_threshold_pct`; or `loan_amount_cents` is at or above the
    program's `second_valuation_loan_amount_threshold_cents`" and "Whether a second
    valuation is required is re-tested whenever the file is submitted for
    underwriting and whenever `ltv_pct` is recomputed."
    PRD 3.3: "`securitization_eligible`, `second_valuation_required`,
    `investor_notification_required` and `repurchase_flag` all false."

    The threshold pair is 85.00 percent and 150000000 cents, so 85.00 does not fire,
    85.01 does, and a 50.00-percent file at exactly 150000000 fires on amount alone.

    Design: Corner/calculations/corner_second_valuation_trigger_boundaries_on_ltv_and_loan_amount
    """
    program = _depletion_program(api, max_ltv_pct=90.00)
    borrower = fx.create_borrower(
        api, legal_name="Tara Boundary", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=9000000, age_years=45)
    on_boundary = _thirty_million_file(
        api, borrower["id"], program["id"], loan_amount_cents=85000000,
        purchase_price_cents=100000000, property_value_cents=100000000)
    above_boundary = _thirty_million_file(
        api, borrower["id"], program["id"], loan_amount_cents=85010000,
        purchase_price_cents=100000000, property_value_cents=100000000)
    on_amount = _thirty_million_file(
        api, borrower["id"], program["id"], loan_amount_cents=150000000,
        purchase_price_cents=300000000, property_value_cents=300000000)

    A.assert_pct_2dp(on_boundary["ltv_pct"], "85.00", "ltv_pct")
    A.assert_pct_2dp(above_boundary["ltv_pct"], "85.01", "ltv_pct")
    A.assert_pct_2dp(on_amount["ltv_pct"], "50.00", "ltv_pct")
    for row in (on_boundary, above_boundary, on_amount):
        A.assert_fields(row, {"status": "DRAFT",
                              "second_valuation_required": False})
        A.assert_is_null(row, "doc_type")

    submitted = [_submit(api, row["id"], "ASSET_DEPLETION")
                 for row in (on_boundary, above_boundary, on_amount)]

    A.assert_fields(submitted[0], {"second_valuation_required": False})
    A.assert_fields(submitted[1], {"second_valuation_required": True})
    A.assert_fields(submitted[2], {"second_valuation_required": True})
    for loan_file, expected in zip((on_boundary, above_boundary, on_amount),
                                   ("SECOND_NOT_REQUIRED", "SECOND_REQUIRED",
                                    "SECOND_REQUIRED")):
        review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
        A.assert_fields(review, {"second_valuation_status": expected})


def test_the_reserve_bucket_fills_before_any_income_exists(api):
    """Twenty-four months of payment absorb 6594336 cents before the horizon divide.

    PRD 3.4: "Required reserves are the program's `min_reserves_months` multiplied by
    the file's current `pitia_monthly_cents`, and `depletable_assets_cents` is the
    eligible assets less those required reserves, floored at zero."

    Eligible assets of 3500000 and of exactly 6594336 both deplete to nothing, while
    6594420 leaves 84 cents, which over an 84-month horizon is one cent a month.

    Design: Corner/calculations/corner_asset_depletion_reserve_bucket_fills_before_income
    """
    program = _depletion_program(api, name="Asset Depletion 84 Deep Reserves",
                                 min_reserves_months=24,
                                 min_residual_income_cents=0)
    borrower = fx.create_borrower(
        api, legal_name="Wes Waterfall", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)
    loan_file = _thirty_million_file(api, borrower["id"], program["id"])
    _submit(api, loan_file["id"], "ASSET_DEPLETION")
    short_ws = _depletion_worksheet(api, loan_file["id"], 1000000, 2000000, 1000000)
    exact_ws = _depletion_worksheet(api, loan_file["id"], 6594336, 0, 0)
    over_ws = _depletion_worksheet(api, loan_file["id"], 6594420, 0, 0)

    short = fx.calculate_worksheet(api, short_ws["id"], UNDERWRITER)
    exact = fx.calculate_worksheet(api, exact_ws["id"], UNDERWRITER)
    over = fx.calculate_worksheet(api, over_ws["id"], UNDERWRITER)

    A.assert_money(short["eligible_assets_after_haircut_cents"], 3500000,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(short["depletable_assets_cents"], 0, "depletable_assets_cents")
    A.assert_money(short["gross_monthly_income_cents"], 0,
                   "gross_monthly_income_cents")
    A.assert_money(short["monthly_qualifying_income_cents"], 0,
                   "monthly_qualifying_income_cents")

    A.assert_money(exact["eligible_assets_after_haircut_cents"], 6594336,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(exact["depletable_assets_cents"], 0, "depletable_assets_cents")
    A.assert_money(exact["monthly_qualifying_income_cents"], 0,
                   "monthly_qualifying_income_cents")

    A.assert_money(over["eligible_assets_after_haircut_cents"], 6594420,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(over["depletable_assets_cents"], 84, "depletable_assets_cents")
    A.assert_money(over["monthly_qualifying_income_cents"], 1,
                   "monthly_qualifying_income_cents")

    for row in (short, exact, over):
        A.assert_fields(row, {"status": "CALCULATED"})


def test_the_governing_credit_event_is_the_greatest_deficit(api):
    """An undocumented event is filtered out and the worst deficit governs.

    PRD 3.2: "The candidate set is every credit event of the loan file's borrower
    whose `documented_flag` is true — undocumented events are ignored entirely, and
    are therefore visible in the list but invisible to the calculation." and "The
    candidate's deficit is its requirement less its elapsed months. The **governing**
    event is the candidate with the greatest deficit" and "`seasoning_satisfied` is
    true when the elapsed months are at least the required months — exactly meeting
    the requirement satisfies it." and "Recording an event increments the borrower's
    `credit_event_count`"

    On a 2026-08-01 clock the MODIFICATION of 2025-06-01 is 14 months old against a
    12-month requirement, a deficit of -2, and the BK_CH7 of 2024-01-01 is 31 months
    old against 24, a deficit of -7; the undocumented FORECLOSURE would have carried
    the greatest deficit of all at +35.

    Design: Corner/calculations/corner_governing_credit_event_is_greatest_deficit_not_most_recent
    """
    fx.set_clock(api, "2026-08-01T00:00:00Z")
    program = _depletion_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Cyrus Season", fico_score=700,
        monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)
    foreclosure = fx.create_credit_event(api, borrower["id"], "FORECLOSURE",
                                        "2026-07-01T00:00:00Z",
                                        documented_flag=False)
    bankruptcy = fx.create_credit_event(api, borrower["id"], "BK_CH7",
                                       "2024-01-01T00:00:00Z",
                                       documented_flag=True)
    modification = fx.create_credit_event(api, borrower["id"], "MODIFICATION",
                                         "2025-06-01T00:00:00Z",
                                         documented_flag=True)
    loan_file = _thirty_million_file(api, borrower["id"], program["id"])

    submitted = _submit(api, loan_file["id"], "ASSET_DEPLETION")

    A.assert_fields(submitted, {"governing_credit_event_id": modification["id"],
                                "seasoning_months_required": 12,
                                "seasoning_months_elapsed": 14,
                                "seasoning_satisfied": True})
    assert submitted["governing_credit_event_id"] != foreclosure["id"]
    assert submitted["governing_credit_event_id"] != bankruptcy["id"]

    refreshed = validate_success(api.get_borrower(borrower["id"], UNDERWRITER))
    A.assert_fields(refreshed, {"credit_event_count": 3})


def _closed_dscr_file(api, legal_name):
    """A CLOSED, delivery-eligible DSCR file on an 80000000-cent accepted appraisal."""
    program = _dscr_program(api)
    borrower = fx.create_borrower(
        api, legal_name=legal_name, fico_score=700,
        monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=5000000, age_years=50)
    loan_file = _dscr_investment_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)
    _origination_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], UNDERWRITER)
    fx.run_atr_determination(api, loan_file["id"], UNDERWRITER)
    fx.approve(api, loan_file["id"], UNDERWRITER)
    fx.close(api, loan_file["id"])
    return loan_file


def _audit_row(api, audit_id):
    return validate_success(api.get_audit(audit_id, POST_CLOSE_AUDITOR))


def test_severity_weights_reach_the_inclusive_material_threshold(api):
    """Four findings weigh exactly 6, and waiving one MINOR regrades to B_MINOR.

    PRD 3.9: "Each finding weighs 1 if its `severity` is `MINOR`, 3 if `SIGNIFICANT`
    and 6 if `MATERIAL`. `defect_score` is the integer sum of the weights of all
    findings whose `status` is `ISSUED`, `REBUTTED` or `UPHELD`; waived findings are
    the only ones excluded." and "`open_finding_count` is the number of findings that
    are `ISSUED` or `REBUTTED`." and "`grade` is `A_CLEAN` when `defect_score` is 0,
    `B_MINOR` when it lies between 1 and 5 inclusive, and `C_MATERIAL` when it reaches
    6 or more — the material boundary is inclusive, so exactly 6 is material and 5 is
    still minor."
    PRD 3.9: "`WAIVE` removes its weight from the score entirely." and "no post-close
    audit row on the file may carry a `grade` of `C_MATERIAL`."

    Design: Corner/calculations/corner_audit_defect_score_weights_and_material_threshold
    """
    loan_file = _closed_dscr_file(api, "Gala Audit")
    audit = fx.create_audit(api, loan_file["id"], "RANDOM")
    fx.create_finding(api, audit["id"], "AF-1", "APPRAISAL", "MINOR")
    fx.create_finding(api, audit["id"], "AF-2", "POINTS_AND_FEES", "SIGNIFICANT")
    fx.create_finding(api, audit["id"], "AF-3", "SEASONING", "MINOR")
    fourth = fx.create_finding(api, audit["id"], "AF-4", "OVERLAY_EXCEPTION",
                               "MINOR")

    material = _audit_row(api, audit["id"])
    A.assert_fields(material, {"defect_score": 6,
                               "grade": "C_MATERIAL",
                               "open_finding_count": 4,
                               "status": "FINDINGS_ISSUED"})
    gated = fx.get_loan_file(api, loan_file["id"], SECURITIZATION_ANALYST)
    A.assert_fields(gated, {"status": "CLOSED", "securitization_eligible": False})

    waived = fx.adjudicate_finding(api, fourth["id"], "WAIVE", POST_CLOSE_AUDITOR,
                                   "Exception memo located in the imaged file")

    A.assert_fields(waived, {"status": "WAIVED"})
    regraded = _audit_row(api, audit["id"])
    A.assert_fields(regraded, {"defect_score": 5,
                               "grade": "B_MINOR",
                               "open_finding_count": 3,
                               "status": "FINDINGS_ISSUED"})


def test_only_the_last_resolved_breach_reopens_the_delivery_gate(api):
    """Eligibility stays false at two unresolved breaches and at one.

    PRD 3.7: "An overlay whose metric is null on this file — a coverage-ratio overlay
    on an income-documented file, or a debt-to-income overlay on a coverage-ratio file
    — is **skipped**, not treated as breached." and "Every unsatisfied overlay
    contributes its `overlay_code` to `overlay_breach_codes`, which is emitted in
    ascending `overlay_code` order. `unresolved_overlay_breach_count` then counts
    those breached overlays for which no exception request on this loan file, naming
    that same `overlay_id`, currently stands in `APPROVED` status."
    PRD 3.9: "`securitization_eligible` is the single aggregate delivery gate, and it
    is a pure conjunction of ten conditions recomputed — never incrementally patched"
    and "The loan's `status` must be `APPROVED` or `CLOSED`" and
    "`unresolved_overlay_breach_count` must be zero"

    PRD 3.8 makes a zero `unresolved_overlay_breach_count` a precondition of approval,
    so the waivers are decided while the file is still in `UNDERWRITING`; the gate
    therefore stays false through both decisions and opens only on approval.

    Design: Corner/calculations/corner_overlay_resolution_propagates_to_securitization_eligibility
    """
    program = _dscr_program(api)
    fx.create_overlay(api, INVESTOR, "OV-C-DTI", "MAX_DTI_PCT", "LTE", 40.00,
                      waivable_flag=True, required_authority_tier=1,
                      severity="MINOR")
    overlay_b = fx.create_overlay(api, INVESTOR, "OV-B-LTV", "MAX_LTV_PCT", "LTE",
                                 70.00, waivable_flag=True,
                                 required_authority_tier=1, severity="MINOR")
    overlay_a = fx.create_overlay(api, INVESTOR, "OV-A-FICO", "MIN_FICO", "GTE", 740,
                                 waivable_flag=True, required_authority_tier=1,
                                 severity="MINOR")
    borrower = fx.create_borrower(
        api, legal_name="Hugo Overlay", fico_score=700,
        monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=5000000, age_years=50)
    loan_file = _dscr_investment_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)
    _origination_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    request_a = fx.create_exception_request(
        api, loan_file["id"], overlay_a["id"], UNDERWRITER,
        justification="Reserves of 9.66 months offset the 700 score",
        compensating_factors=["RESERVES"])
    request_b = fx.create_exception_request(
        api, loan_file["id"], overlay_b["id"], UNDERWRITER,
        justification="DSCR of 1.2367 offsets the 75.00 LTV")
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], UNDERWRITER)
    fx.run_atr_determination(api, loan_file["id"], UNDERWRITER)

    breached = fx.get_loan_file(api, loan_file["id"], SECURITIZATION_ANALYST)
    A.assert_codes_in_order(breached["overlay_breach_codes"],
                            ["OV-A-FICO", "OV-B-LTV"], "overlay_breach_codes")
    assert "OV-C-DTI" not in breached["overlay_breach_codes"]
    A.assert_fields(breached, {"unresolved_overlay_breach_count": 2,
                               "status": "UNDERWRITING",
                               "securitization_eligible": False})

    decided_a = fx.approve_exception(api, request_a["id"], credit_committee("cc-1"),
                                    "Reserve offset accepted")
    A.assert_fields(decided_a, {"status": "APPROVED"})
    A.assert_decimal_equals(decided_a["pinned_metric_value"], "700", 0,
                            "pinned_metric_value")

    halfway = fx.get_loan_file(api, loan_file["id"], SECURITIZATION_ANALYST)
    A.assert_fields(halfway, {"unresolved_overlay_breach_count": 1,
                              "securitization_eligible": False})
    A.assert_codes_in_order(halfway["overlay_breach_codes"],
                            ["OV-A-FICO", "OV-B-LTV"], "overlay_breach_codes")

    decided_b = fx.approve_exception(api, request_b["id"], credit_committee("cc-1"),
                                    "Coverage offset accepted")
    A.assert_fields(decided_b, {"status": "APPROVED"})
    A.assert_pct_2dp(decided_b["pinned_metric_value"], "75.00",
                     "pinned_metric_value")

    resolved = fx.get_loan_file(api, loan_file["id"], SECURITIZATION_ANALYST)
    A.assert_fields(resolved, {"unresolved_overlay_breach_count": 0,
                               "status": "UNDERWRITING",
                               "securitization_eligible": False})
    A.assert_codes_in_order(resolved["overlay_breach_codes"],
                            ["OV-A-FICO", "OV-B-LTV"], "overlay_breach_codes")

    approved = fx.approve(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(approved, {"status": "APPROVED",
                               "unresolved_overlay_breach_count": 0,
                               "securitization_eligible": True})
