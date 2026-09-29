"""A transition on one entity gated by state the entity does not own.

Approval belongs to the loan file, but whether it may leave `UNDERWRITING`
depends on a dimension of the appraisal review. Membership belongs to the pool,
but whether it may accept a write depends on the loan file's own status. Both
gates are probed from every failing state and then from the one that clears.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE,
    ERR_SECOND_VALUATION_REQUIRED,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    SECURITIZATION_ANALYST,
    underwriter,
)

INVESTOR = "INV-ATLAS"


def _file_with_a_required_second_valuation(api):
    """A file otherwise ready to approve, waiting on its second valuation."""
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=30000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Merrow Ridge Partners LLC", fico_score=752,
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
    uw = underwriter("uw-13")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 55000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    return loan_file, uw


def test_approval_is_refused_at_every_unreconciled_second_dimension_state(api):
    """Required, ordered and received all refuse; the report is not the reconciliation.

    PRD 3.8: "`second_valuation_status` must be `SECOND_NOT_REQUIRED` or
    `SECOND_RECONCILED`; a file whose second dimension still reads `SECOND_REQUIRED`,
    `SECOND_ORDERED` or `SECOND_RECEIVED` is refused with
    `ERR_SECOND_VALUATION_REQUIRED`."

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_by_appraisal_review_second_valuation_dimension
    """
    loan_file, uw = _file_with_a_required_second_valuation(api)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_fields(review, {"second_valuation_status": "SECOND_REQUIRED"})
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_SECOND_VALUATION_REQUIRED)
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], uw),
                    {"status": "UNDERWRITING"})

    second = fx.order_valuation(api, loan_file["id"], "SECOND_APPRAISAL",
                                "2026-06-01T00:00:00Z", APPRAISAL_REVIEWER,
                                vendor_code="VND-BETA")
    A.assert_fields(fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER),
                    {"second_valuation_status": "SECOND_ORDERED"})
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_SECOND_VALUATION_REQUIRED)

    fx.receive_valuation(api, second["id"], 54000000, APPRAISAL_REVIEWER)
    A.assert_fields(fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER),
                    {"second_valuation_status": "SECOND_RECEIVED"})
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_SECOND_VALUATION_REQUIRED)
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], uw),
                    {"status": "UNDERWRITING"})


def test_only_the_reconciled_second_dimension_clears_the_approval_gate(api):
    """Reconciliation opens the gate, having first invalidated the determination.

    PRD 3.5: "Whenever an acceptance changes `reconciled_value_cents`, the full cascade
    fires inside the same request" and "The same value change also resets
    `atr_documentation_status` to `INCOMPLETE` and `safe_harbor_class` to
    `NOT_EVALUATED`."
    PRD 3.8: "On success the file moves `UNDERWRITING → APPROVED` and
    `securitization_eligible` is recomputed."

    Design: Difficulty/cross_entity_state_dependency/loan_approval_gated_by_appraisal_review_second_valuation_dimension
    """
    loan_file, uw = _file_with_a_required_second_valuation(api)
    second = fx.order_valuation(api, loan_file["id"], "SECOND_APPRAISAL",
                                "2026-06-01T00:00:00Z", APPRAISAL_REVIEWER,
                                vendor_code="VND-BETA")
    fx.receive_valuation(api, second["id"], 54000000, APPRAISAL_REVIEWER)

    fx.accept_valuation(api, second["id"], APPRAISAL_REVIEWER)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_pct_2dp(review["variance_pct"], "1.85", "variance_pct")
    A.assert_fields(review, {"second_valuation_status": "SECOND_RECONCILED",
                             "primary_review_status": "PRIMARY_CLEARED"})
    A.assert_money(review["reconciled_value_cents"], 55000000,
                   "reconciled_value_cents")

    reconciled = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_pct_2dp(reconciled["ltv_pct"], "72.73", "ltv_pct")
    A.assert_fields(reconciled, {"atr_documentation_status": "INCOMPLETE",
                                 "safe_harbor_class": "NOT_EVALUATED"})

    redetermined = fx.run_atr_determination(api, loan_file["id"], uw)
    A.assert_fields(redetermined,
                    {"atr_documentation_status": "EXEMPT",
                     "safe_harbor_class": "EXEMPT_BUSINESS_PURPOSE"})

    approved = fx.approve(api, loan_file["id"], uw)
    A.assert_fields(approved, {"status": "APPROVED",
                               "securitization_eligible": True})
    A.assert_money(approved["pitia_monthly_cents"], 401333, "pitia_monthly_cents")
    A.assert_ratio_4dp(approved["dscr_ratio"], "1.1960", "dscr_ratio")
    A.assert_decimal_equals(approved["documented_reserves_months"], "7.48", 2,
                            "documented_reserves_months")


def _approved_but_unclosed_loan(api):
    """An eligible, approved loan and an OPEN pool that cannot yet take it."""
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=75.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Norwood Lane Rentals LLC", fico_score=745,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=5000000,
        age_years=55)
    pool = fx.create_pool(api, "PL-2026A", INVESTOR, 200000000)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=8.750, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        monthly_hoa_cents=0, gross_market_rent_cents=620000,
        lease_rent_cents=640000)
    uw = underwriter("uw-14")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    return loan_file, pool, uw


def test_pool_assignment_is_refused_while_the_loan_is_only_approved(api):
    """Every eligibility conjunct holds; the missing thing is the CLOSED state.

    PRD 3.9: "The named loan must be `CLOSED` with `securitization_eligible` true; a loan
    carrying an unresolved overlay breach, a set `repurchase_flag`, or a `C_MATERIAL`
    audit grade is not poolable and is refused with
    `ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE`."

    Design: Difficulty/cross_entity_state_dependency/pool_assignment_gated_by_loan_file_closing_state
    """
    loan_file, pool, uw = _approved_but_unclosed_loan(api)

    before = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(before, {"status": "APPROVED", "securitization_eligible": True,
                             "pool_id": None, "second_valuation_required": False})
    A.assert_pct_2dp(before["ltv_pct"], "75.00", "ltv_pct")

    refused = api.assign_loan_to_pool(
        pool["id"],
        {"loan_file_id": loan_file["id"], "expected_pool_version": pool["version"]},
        SECURITIZATION_ANALYST)
    validate_error(refused, ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE)

    untouched = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(untouched, {"member_loan_count": 0, "status": "OPEN",
                                "version": pool["version"]})
    A.assert_money(untouched["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(untouched["weighted_avg_coupon_pct"], "0.0000",
                       "weighted_avg_coupon_pct")


def test_closing_the_loan_admits_the_assignment_at_the_same_expected_version(api):
    """The refused write incremented nothing, so the original version still matches.

    PRD 3.9: "the supplied version must match the pool's live `version`, or the write is
    refused with `ERR_STALE_POOL_VERSION`" and "On success the loan's `pool_id` is set,
    the three pool metrics are recomputed, the pool's `version` increments by one".

    Design: Difficulty/cross_entity_state_dependency/pool_assignment_gated_by_loan_file_closing_state
    """
    loan_file, pool, uw = _approved_but_unclosed_loan(api)
    validate_error(
        api.assign_loan_to_pool(
            pool["id"],
            {"loan_file_id": loan_file["id"],
             "expected_pool_version": pool["version"]},
            SECURITIZATION_ANALYST),
        ERR_LOAN_NOT_SECURITIZATION_ELIGIBLE)

    closed = fx.close(api, loan_file["id"])
    A.assert_fields(closed, {"status": "CLOSED"})

    # The same expected_pool_version the refused call used still matches.
    assigned = fx.assign_loan(api, pool["id"], loan_file["id"], pool["version"])
    A.assert_fields(assigned, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(assigned["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(assigned["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(assigned, pool["version"] + 1)
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], uw),
                    {"pool_id": pool["id"]})
