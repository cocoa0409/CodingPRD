"""Two rules live on one request: the ladder decides which one is reported.

Each pair is engineered so both members are simultaneously violated, the
higher-banded one is asserted, and then the higher violation is removed so the
lower one surfaces on the identical call. That second half is what proves the
lower rule was evaluated at all rather than simply skipped.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_DTI_ABOVE_PROGRAM_MAX,
    ERR_HIGH_COST_LOAN_PROHIBITED,
    ERR_LOAN_ALREADY_POOLED,
    ERR_LOAN_FILE_STATE_INVALID,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    SECURITIZATION_ANALYST,
    underwriter,
)

INVESTOR = "INV-ATLAS"


def _suspended_file_over_the_dti_ceiling(api):
    """A profit-and-loss file at 63.62 DTI, suspended out of ``UNDERWRITING``.

    Both the state precondition and the fiscal ceiling are violated for an
    approval attempt: the file is ``SUSPENDED`` and its debt-to-income sits above
    the program's 50.00 maximum.
    """
    program = fx.create_program(
        api, "PROFIT_AND_LOSS", name="CPA P&L 12-Month", statement_period_months=12,
        default_expense_factor_pct=50.00, min_expense_factor_pct=25.00,
        max_ltv_pct=80.00, min_fico=660, min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Ilse Vantoren", fico_score=700, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=400000,
        verified_liquid_assets_cents=4000000, age_years=47)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-9")
    fx.select_doc_type(api, loan_file["id"], "PROFIT_AND_LOSS", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    current = fx.get_loan_file(api, loan_file["id"], uw)
    worksheet = fx.create_worksheet(api, loan_file["id"], "PROFIT_AND_LOSS",
                                    current["version"], uw,
                                    p_and_l_net_income_cents=18333336,
                                    p_and_l_period_months=12)
    fx.calculate_worksheet(api, worksheet["id"], uw)
    fx.accept_worksheet(api, worksheet["id"], uw)
    # The primary appraisal must be cleared before approval can reach the fiscal
    # band at all: PRD 3.8 refuses a `PRIMARY_NOT_ORDERED` review earlier in the
    # ladder, and the acceptance also invalidates the determination, so it runs
    # before the points-and-fees test and the ability-to-repay determination.
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 75000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.suspend(api, loan_file["id"], uw, "Awaiting updated CPA letter")
    return loan_file, uw


def test_the_suspended_state_error_beats_the_live_dti_ceiling_breach(api):
    """Approving a suspended file over its DTI ceiling reports the state error.

    PRD 2.7: "The bands run authentication, then authorization, then existence, then
    request shape, then numeric domain, then optimistic concurrency, then state
    preconditions, then the business rules in the order consumer-protection safety,
    temporal windows, documentation sufficiency and uniqueness, referential linkage,
    and finally fiscal capacity and authority limits."
    PRD 3.8: "The file must be in `UNDERWRITING`, and the checks then apply in the
    ladder's order."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_dti_ceiling_on_suspended_profit_and_loss_file
    """
    loan_file, uw = _suspended_file_over_the_dti_ceiling(api)

    before = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(before, {"status": "SUSPENDED",
                             "points_and_fees_test_result": "PASS"})
    A.assert_money(before["qualifying_income_monthly_cents"], 1527778,
                   "qualifying_income_monthly_cents")
    A.assert_money(before["pitia_monthly_cents"], 572020, "pitia_monthly_cents")
    A.assert_pct_2dp(before["dti_pct"], "63.62", "dti_pct")
    A.assert_money(before["residual_income_cents"], 555758, "residual_income_cents")
    A.assert_decimal_equals(before["documented_reserves_months"], "6.99", 2,
                            "documented_reserves_months")
    # PRD 3.8 invalidates the determination snapshot on suspension.
    A.assert_fields(before, {"atr_documentation_status": "INCOMPLETE",
                             "safe_harbor_class": "NOT_EVALUATED"})

    refused = api.approve_loan_file(
        loan_file["id"], uw,
        {"approval_note": "attempt while suspended and over the DTI ceiling"})
    validate_error(refused, ERR_LOAN_FILE_STATE_INVALID)

    # A refused approval mutates nothing.
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], uw),
                    {"status": "SUSPENDED"})


def test_clearing_conditions_lets_the_dti_ceiling_surface_on_the_same_call(api):
    """With the state violation gone, the identical approve reports the fiscal one.

    PRD 3.8: "`dti_pct` must be non-null and no greater than the program's
    `max_dti_pct`, and a breach is `ERR_DTI_ABOVE_PROGRAM_MAX`" and "The determination
    must then be re-run before the file can be approved."

    Design: Difficulty/priority_pair_validation_conflict/state_error_beats_dti_ceiling_on_suspended_profit_and_loss_file
    """
    loan_file, uw = _suspended_file_over_the_dti_ceiling(api)

    cleared = fx.clear_conditions(api, loan_file["id"], uw, "CPA letter received")
    A.assert_fields(cleared, {"status": "UNDERWRITING"})

    # Suspension invalidated the determination, so re-run it; otherwise the
    # documentation rule, which stands above the fiscal band, answers first.
    determined = fx.run_atr_determination(api, loan_file["id"], uw)
    A.assert_fields(determined,
                    {"atr_documentation_status": "DOCUMENTED",
                     "safe_harbor_class": "ATR_DOCUMENTED_NO_SAFE_HARBOR"})
    A.assert_pct_3dp(determined["rate_spread_pct"], "2.650", "rate_spread_pct")

    refused = api.approve_loan_file(
        loan_file["id"], uw,
        {"approval_note": "attempt after clearing conditions, DTI still 63.62"})
    validate_error(refused, ERR_DTI_ABOVE_PROGRAM_MAX)

    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(after, {"status": "UNDERWRITING"})
    A.assert_pct_2dp(after["dti_pct"], "63.62", "dti_pct")
    A.assert_decimal_equals(after["documented_reserves_months"], "6.99", 2,
                            "documented_reserves_months")
    A.assert_money(after["residual_income_cents"], 555758, "residual_income_cents")


def _pool(api, pool_id):
    return validate_success(api.get_pool(pool_id, SECURITIZATION_ANALYST))


def _pooled_loan_turned_high_cost(api):
    """A closed loan already delivered into PL-2026A, flipped to ``FAIL`` post-close.

    Both bands are live for an assignment into the second pool: the loan is a
    prohibited high-cost loan, and it is also already a member of another pool.
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Jarrow Yield LLC", fico_score=745,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=5000000,
        age_years=55)
    pool_a = fx.create_pool(api, "PL-2026A", INVESTOR, 200000000)
    pool_b = fx.create_pool(api, "PL-2026B", INVESTOR, 200000000)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=8.750, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        monthly_hoa_cents=0, gross_market_rent_cents=620000,
        lease_rent_cents=640000)
    uw = underwriter("uw-10")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    fx.close(api, loan_file["id"])
    fx.assign_loan(api, pool_a["id"], loan_file["id"], pool_a["version"])
    fee = fx.create_fee_item(api, loan_file["id"], "LLPA-INV-3",
                             "LOAN_LEVEL_PRICE_ADJUSTMENT", 3100000, LOAN_OFFICER,
                             prepaid_finance_charge_flag=False)
    return loan_file, pool_a, pool_b, fee


def test_the_high_cost_safety_error_beats_the_already_pooled_referential_error(api):
    """A post-close fee correction outranks the membership conflict.

    PRD 2.7: "the business rules in the order consumer-protection safety, temporal
    windows, documentation sufficiency and uniqueness, referential linkage, and
    finally fiscal capacity and authority limits."
    PRD 3.6: "A file whose result is `FAIL` is a high-cost loan the lender does not
    originate at any price: it can be neither approved, nor closed, nor assigned to a
    delivery pool, and all three refusals report `ERR_HIGH_COST_LOAN_PROHIBITED`."

    Design: Difficulty/priority_pair_validation_conflict/high_cost_safety_error_beats_already_pooled_referential_error
    """
    loan_file, pool_a, pool_b, fee = _pooled_loan_turned_high_cost(api)

    before = fx.get_loan_file(api, loan_file["id"])
    A.assert_money(before["points_and_fees_total_cents"], 3100000,
                   "points_and_fees_total_cents")
    A.assert_money(before["total_loan_amount_cents"], 60000000,
                   "total_loan_amount_cents")
    A.assert_money(before["points_and_fees_cap_cents"], 3000000,
                   "points_and_fees_cap_cents")
    A.assert_fields(before, {"points_and_fees_test_result": "FAIL",
                             "securitization_eligible": False,
                             "pool_id": pool_a["id"]})

    refused = api.assign_loan_to_pool(
        pool_b["id"],
        {"loan_file_id": loan_file["id"], "expected_pool_version": pool_b["version"]},
        SECURITIZATION_ANALYST)
    validate_error(refused, ERR_HIGH_COST_LOAN_PROHIBITED)

    untouched = _pool(api, pool_b["id"])
    A.assert_fields(untouched, {"member_loan_count": 0,
                                "version": pool_b["version"]})
    A.assert_money(untouched["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")


def test_voiding_the_high_cost_charge_lets_the_already_pooled_error_surface(api):
    """Remove the safety violation and the identical assignment reports membership.

    PRD 3.6: "Voiding a charge requires a `void_reason`, moves it `ACTIVE → VOIDED`, and
    removes it from every aggregate".
    PRD 3.9: "The loan must not already sit in any pool: `pool_id` must be null at
    assignment time, or the refusal is `ERR_LOAN_ALREADY_POOLED` at 409."

    Design: Difficulty/priority_pair_validation_conflict/high_cost_safety_error_beats_already_pooled_referential_error
    """
    loan_file, pool_a, pool_b, fee = _pooled_loan_turned_high_cost(api)

    voided = fx.void_fee_item(api, fee["id"], LOAN_OFFICER,
                              "LLPA billed to the wrong file")
    A.assert_fields(voided, {"status": "VOIDED"})
    # PRD 3.6: the void flips the verdict back to `PASS`, and a verdict change
    # invalidates the ability-to-repay determination "exactly as an explicit test run
    # would invalidate it", so the determination has to be re-run before the
    # documentation band stops answering ahead of the membership band.
    fx.run_atr_determination(api, loan_file["id"], underwriter("uw-10"))

    restored = fx.get_loan_file(api, loan_file["id"])
    A.assert_money(restored["points_and_fees_total_cents"], 0,
                   "points_and_fees_total_cents")
    A.assert_money(restored["points_and_fees_cap_cents"], 3000000,
                   "points_and_fees_cap_cents")
    A.assert_fields(restored, {"points_and_fees_test_result": "PASS",
                               "securitization_eligible": True})

    refused = api.assign_loan_to_pool(
        pool_b["id"],
        {"loan_file_id": loan_file["id"], "expected_pool_version": pool_b["version"]},
        SECURITIZATION_ANALYST)
    validate_error(refused, ERR_LOAN_ALREADY_POOLED)

    A.assert_fields(fx.get_loan_file(api, loan_file["id"]),
                    {"pool_id": pool_a["id"]})
