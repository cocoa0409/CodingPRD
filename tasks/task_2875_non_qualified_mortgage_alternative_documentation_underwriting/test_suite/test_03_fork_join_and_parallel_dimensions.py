"""Non-linear state machines: the tier-2 signoff fork-join and the appraisal
review's two independent dimensions.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    chief_credit_officer,
    credit_committee,
    underwriter,
)

INVESTOR = "INV-ATLAS"


def _material_overlay_scenario(api):
    """A file breaching a MATERIAL fico overlay, with a PENDING_REVIEW request."""
    program = fx.create_program(
        api, "BANK_STATEMENT_12MO", name="12-Month Bank Statement",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    overlay = fx.create_overlay(
        api, INVESTOR, "OVL-FICO", "MIN_FICO", "GTE", 700,
        waivable_flag=True, required_authority_tier=1, severity="MATERIAL")
    borrower = fx.create_borrower(
        api, legal_name="Efe Nakamura", fico_score=680, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=120000,
        verified_liquid_assets_cents=4000000, age_years=47)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-5")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    request = fx.create_exception_request(
        api, loan_file["id"], overlay["id"], uw,
        justification="24 months reserves and 9 years in business",
        compensating_factors=["RESERVES_24_MONTHS", "BUSINESS_TENURE_9_YEARS"])
    return loan_file, overlay, request, uw


def test_material_overlay_forks_to_awaiting_second_signature(api):
    """A MATERIAL overlay demands tier 2, and the first signoff only parks it.

    PRD 3.7: "computes `required_authority_tier` as the greater of the overlay's own
    `required_authority_tier` and the value 2 when the overlay's `severity` is
    `MATERIAL`, or 1 when it is `MINOR`" and "The first approval takes the request
    `PENDING_REVIEW → AWAITING_SECOND_SIGNATURE`" and "It records
    `first_signoff_user_id` as the acting `X-User-ID`" and "does **not** reduce
    `unresolved_overlay_breach_count`, because a half-signed waiver is not yet
    effective."

    Design: Difficulty/non_linear_state_machine/exception_request_tier_two_fork_join_dual_signature
    """
    loan_file, overlay, request, uw = _material_overlay_scenario(api)
    A.assert_fields(request, {"required_authority_tier": 2,
                              "status": "PENDING_REVIEW"})
    assert request["pinned_metric_value"] is not None
    assert A.as_decimal(request["pinned_metric_value"]) == A.as_decimal(680)

    first = fx.approve_exception(api, request["id"], credit_committee("cc-1"),
                                "Committee concurs")

    A.assert_fields(first, {"status": "AWAITING_SECOND_SIGNATURE",
                            "first_signoff_user_id": "cc-1"})
    A.assert_is_null(first, "second_signoff_user_id")
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_codes_in_order(after["overlay_breach_codes"], ["OVL-FICO"],
                            "overlay_breach_codes")
    A.assert_fields(after, {"unresolved_overlay_breach_count": 1,
                            "investor_notification_required": False})


def test_tier_two_join_notifies_the_investor_and_clears_the_breach(api):
    """The second, different signer joins the fork and fires its exclusive effect.

    PRD 3.7: "The second signature, supplied by a `ChiefCreditOfficer`, takes the
    request `AWAITING_SECOND_SIGNATURE → APPROVED`" and "It records
    `second_signoff_user_id`, sets the file's `investor_notification_required` to
    true" and "recomputes both `unresolved_overlay_breach_count` and
    `securitization_eligible`."

    Design: Difficulty/non_linear_state_machine/exception_request_tier_two_fork_join_dual_signature
    """
    loan_file, overlay, request, uw = _material_overlay_scenario(api)
    fx.approve_exception(api, request["id"], credit_committee("cc-1"),
                         "Committee concurs")

    joined = fx.approve_exception(api, request["id"],
                                 chief_credit_officer("cco-1"),
                                 "CCO second signature")

    A.assert_fields(joined, {"status": "APPROVED",
                             "first_signoff_user_id": "cc-1",
                             "second_signoff_user_id": "cco-1"})
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_codes_in_order(after["overlay_breach_codes"], ["OVL-FICO"],
                            "overlay_breach_codes")
    A.assert_fields(after, {"unresolved_overlay_breach_count": 0,
                            "investor_notification_required": True})


def _second_valuation_scenario(api):
    """A 40000000-cent DSCR file whose loan amount forces a second valuation."""
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=30000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Farrow Rentals LLC", fico_score=745,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=3000000,
        age_years=55)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=40000000, property_value_cents=55000000,
        occupancy="INVESTMENT", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=9.250, apor_pct=6.100, term_months=360,
        amortization_type="INTEREST_ONLY", monthly_taxes_cents=60000,
        monthly_insurance_cents=18000, monthly_hoa_cents=15000,
        gross_market_rent_cents=420000, lease_rent_cents=480000)
    uw = underwriter("uw-6")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    primary = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                                 "2026-04-01T00:00:00Z", APPRAISAL_REVIEWER,
                                 vendor_code="VND-ALPHA")
    fx.receive_valuation(api, primary["id"], 55000000)
    fx.accept_valuation(api, primary["id"])
    return loan_file, primary, uw


def test_accepting_the_primary_leaves_the_primary_dimension_pending(api):
    """With a second valuation outstanding the primary acceptance reconciles nothing.

    PRD 3.5: "When the accepted order is the primary appraisal, its value becomes
    `primary_value_cents`; and if the second dimension reads `SECOND_NOT_REQUIRED`,
    that value is adopted directly as `reconciled_value_cents` and the primary
    dimension advances `PRIMARY_PENDING_REVIEW → PRIMARY_CLEARED`."

    The 40000000-cent loan is at or above the program's 30000000-cent second
    valuation threshold, so the second dimension reads `SECOND_REQUIRED` and neither
    the adoption nor the clearance happens.

    Design: Difficulty/non_linear_state_machine/appraisal_review_parallel_dimensions_advance_independently
    """
    loan_file, primary, uw = _second_valuation_scenario(api)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)

    A.assert_fields(review, {"primary_review_status": "PRIMARY_PENDING_REVIEW",
                             "second_valuation_status": "SECOND_REQUIRED"})
    A.assert_money(review["primary_value_cents"], 55000000, "primary_value_cents")
    A.assert_is_null(review, "reconciled_value_cents", "second_value_cents",
                     "variance_pct")
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(after, {"second_valuation_required": True})
    A.assert_pct_2dp(after["ltv_pct"], "72.73", "ltv_pct")


def test_second_dimension_advances_twice_while_the_primary_stands_still(api):
    """Ordering and receiving the second appraisal moves only the second dimension.

    PRD 3.5: "Neither dimension waits for the other; they are joined only at
    reconciliation, which cannot compute a variance until both values exist." and
    "Receiving publishes nothing to the review" and "for a `SECOND_APPRAISAL` it moves
    `second_valuation_status` from `SECOND_ORDERED` to `SECOND_RECEIVED`."

    Design: Difficulty/non_linear_state_machine/appraisal_review_parallel_dimensions_advance_independently
    """
    loan_file, primary, uw = _second_valuation_scenario(api)

    second = fx.order_valuation(api, loan_file["id"], "SECOND_APPRAISAL",
                                "2026-05-01T00:00:00Z", APPRAISAL_REVIEWER,
                                vendor_code="VND-BETA")
    fx.receive_valuation(api, second["id"], 49000000)

    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_fields(review, {"primary_review_status": "PRIMARY_PENDING_REVIEW",
                             "second_valuation_status": "SECOND_RECEIVED"})
    A.assert_money(review["primary_value_cents"], 55000000, "primary_value_cents")
    A.assert_is_null(review, "second_value_cents", "reconciled_value_cents",
                     "variance_pct")
    after = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_pct_2dp(after["ltv_pct"], "72.73", "ltv_pct")
