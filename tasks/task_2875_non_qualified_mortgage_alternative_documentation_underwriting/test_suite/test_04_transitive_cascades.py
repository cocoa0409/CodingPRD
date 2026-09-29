"""Multi-hop cascades: one POST that moves four entities.

Two chains are exercised. Adjudicating the last open finding on a post-close
audit regrades the audit, defects the loan file and rebalances the pool it was
delivered into. Accepting a second appraisal reconciles the value down, rebases
loan-to-value, voids the exception whose waiver was pinned to the old figure and
suspends the file.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    credit_committee,
    underwriter,
)

INVESTOR = "INV-ATLAS"


def _pool(api, pool_id):
    return validate_success(api.get_pool(pool_id, SECURITIZATION_ANALYST))


def _audit(api, audit_id):
    return validate_success(api.get_audit(audit_id, POST_CLOSE_AUDITOR))


def _closed_and_pooled_loan(api):
    """A DSCR loan driven to CLOSED, delivered into an OPEN pool, then audited.

    The pool reads one member at 60000000 cents and a 8.7500 coupon; the audit
    carries a single MATERIAL finding that has been rebutted once.
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=75.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Gullane Holdings LLC", fico_score=745,
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
    uw = underwriter("uw-7")
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
    fx.assign_loan(api, pool["id"], loan_file["id"], pool["version"])
    audit = fx.create_audit(api, loan_file["id"], "RANDOM")
    finding = fx.create_finding(api, audit["id"], "AF-INC-01",
                                "INCOME_CALCULATION", "MATERIAL")
    fx.rebut_finding(api, finding["id"], LOAN_OFFICER)
    return loan_file, pool, audit, finding


def test_upholding_the_last_open_finding_defects_the_closed_loan_file(api):
    """One adjudication moves the finding, the audit and the loan file.

    PRD 3.9: "`UPHOLD` fixes the finding as a confirmed defect." and "`defect_score`
    is the integer sum of the weights of all findings whose `status` is `ISSUED`,
    `REBUTTED` or `UPHELD`; waived findings are the only ones excluded." and "A
    `MATERIAL_DEFECT` conclusion runs the repurchase cascade: the loan file's
    `repurchase_flag` is set true, its `securitization_eligible` false, and the file
    moves `CLOSED → AUDIT_DEFECT`".

    Design: Difficulty/transitive_cascade/audit_material_defect_cascade_to_pool_rebalance
    """
    loan_file, pool, audit, finding = _closed_and_pooled_loan(api)

    before = fx.get_loan_file(api, loan_file["id"])
    # The file was delivered while eligible, but PRD 3.9 recomputes eligibility "on
    # every audit grade change" and forbids any audit row grading `C_MATERIAL`, so the
    # MATERIAL finding already cost the file its eligibility. Membership, status and
    # the repurchase flag are what the adjudication still has to move.
    A.assert_fields(before, {"status": "CLOSED", "repurchase_flag": False,
                             "securitization_eligible": False,
                             "pool_id": pool["id"]})
    A.assert_fields(_audit(api, audit["id"]),
                    {"status": "FINDINGS_ISSUED", "grade": "C_MATERIAL",
                     "defect_score": 6, "open_finding_count": 1})

    adjudicated = fx.adjudicate_finding(
        api, finding["id"], "UPHOLD", POST_CLOSE_AUDITOR,
        adjudication_note="Lease unsigned at close")

    # Hop 1: the finding itself, with the rebuttal round it accumulated.
    A.assert_fields(adjudicated, {"status": "UPHELD", "rebuttal_round": 1})

    # Hop 2: the parent audit regrades and becomes terminal.
    A.assert_fields(_audit(api, audit["id"]),
                    {"status": "MATERIAL_DEFECT", "defect_score": 6,
                     "grade": "C_MATERIAL", "open_finding_count": 0})

    # Hop 3: the loan file is defected and detached.
    after = fx.get_loan_file(api, loan_file["id"])
    A.assert_fields(after, {"status": "AUDIT_DEFECT", "repurchase_flag": True,
                            "pool_id": None, "securitization_eligible": False})


def test_the_defect_cascade_recomputes_all_three_pool_metrics_from_scratch(api):
    """The fourth hop is arithmetic: the emptied pool rebalances to zero.

    PRD 3.9: "which drives the pool `OPEN → REBALANCING`, recomputes all three pool
    metrics from scratch over the remaining members, and increments the pool's
    `version` by one." and "The member set is exactly those loan files whose
    `pool_id` equals this pool's id" and "When the aggregate balance is zero the
    coupon is 0.0000 rather than undefined."

    Design: Difficulty/transitive_cascade/audit_material_defect_cascade_to_pool_rebalance
    """
    loan_file, pool, audit, finding = _closed_and_pooled_loan(api)

    before = _pool(api, pool["id"])
    A.assert_fields(before, {"status": "OPEN", "member_loan_count": 1})
    A.assert_money(before["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(before["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")

    fx.adjudicate_finding(api, finding["id"], "UPHOLD", POST_CLOSE_AUDITOR,
                          adjudication_note="Lease unsigned at close")

    after = _pool(api, pool["id"])
    A.assert_fields(after, {"status": "REBALANCING", "member_loan_count": 0})
    A.assert_money(after["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(after["weighted_avg_coupon_pct"], "0.0000",
                       "weighted_avg_coupon_pct")
    A.assert_version(after, before["version"] + 1)

    # The cascade touches membership and eligibility, not the loan's own numbers.
    defected = fx.get_loan_file(api, loan_file["id"])
    A.assert_money(defected["pitia_monthly_cents"], 517500, "pitia_monthly_cents")
    A.assert_ratio_4dp(defected["dscr_ratio"], "1.2367", "dscr_ratio")
    A.assert_pct_2dp(defected["ltv_pct"], "75.00", "ltv_pct")
    A.assert_fields(defected, {"points_and_fees_test_result": "PASS"})


def _exception(api, exception_id):
    return validate_success(api.get_exception_request(exception_id,
                                                      credit_committee("cc-1")))


def _waived_file_awaiting_its_second_appraisal(api):
    """A 72.73-LTV file whose OVL-LTV breach is covered by a tier-1 waiver.

    The primary appraisal is accepted at 55000000 but, because a second valuation
    is required, it publishes no reconciled value. The second appraisal is
    received at 49000000 and left undecided.
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=30000000,
        atr_exempt_flag=True)
    overlay = fx.create_overlay(
        api, INVESTOR, "OVL-LTV", "MAX_LTV_PCT", "LTE", 70.00,
        waivable_flag=True, required_authority_tier=1, severity="MINOR")
    borrower = fx.create_borrower(
        api, legal_name="Halberd Property Group LLC", fico_score=752,
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
    uw = underwriter("uw-8")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    request = fx.create_exception_request(
        api, loan_file["id"], overlay["id"], uw,
        justification="72.73 LTV with a 1.1960 DSCR and 7.48 months reserves")
    fx.approve_exception(api, request["id"], credit_committee("cc-1"),
                         decision_reason="Tier 1 committee approval at 72.73")
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 55000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    second = fx.order_valuation(api, loan_file["id"], "SECOND_APPRAISAL",
                                "2026-06-01T00:00:00Z", APPRAISAL_REVIEWER,
                                vendor_code="VND-BETA")
    fx.receive_valuation(api, second["id"], 49000000, APPRAISAL_REVIEWER)
    return loan_file, request, second


def test_accepting_the_second_appraisal_reconciles_down_and_rebases_ltv(api):
    """The middle hops of the chain are arithmetic, not state.

    PRD 3.5: "its value becomes `second_value_cents`, and the platform takes the lower
    and the higher of the two values and computes `variance_pct` as the difference
    between them, multiplied by one hundred and divided by **the lower** of the two,
    rounded half up to two decimals." and "If `variance_pct` is strictly above 10.00
    percent, the file is underwritten conservatively: `reconciled_value_cents` becomes
    the lower of the two values, the primary dimension moves `PRIMARY_PENDING_REVIEW →
    PRIMARY_ESCALATED`, and `escalation_reason` records `VARIANCE_ABOVE_TOLERANCE`."
    PRD 3.3: "`ltv_pct` is the loan amount multiplied by 100 and divided by the basis,
    rounded half up to two decimals in a single rounding step."

    Design: Difficulty/transitive_cascade/second_valuation_acceptance_cascade_to_exception_void
    """
    loan_file, request, second = _waived_file_awaiting_its_second_appraisal(api)

    before = fx.get_loan_file(api, loan_file["id"])
    A.assert_pct_2dp(before["ltv_pct"], "72.73", "ltv_pct")
    A.assert_codes_in_order(before["overlay_breach_codes"], ["OVL-LTV"],
                            "overlay_breach_codes")
    A.assert_fields(before, {"unresolved_overlay_breach_count": 0})
    pinned = _exception(api, request["id"])
    A.assert_fields(pinned, {"status": "APPROVED"})
    A.assert_pct_2dp(pinned["pinned_metric_value"], "72.73", "pinned_metric_value")

    accepted = fx.accept_valuation(api, second["id"], APPRAISAL_REVIEWER)

    # Hop 1: the order itself.
    A.assert_fields(accepted, {"status": "ACCEPTED"})

    # Hop 2: reconciliation takes the lower value and escalates the primary.
    review = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_money(review["primary_value_cents"], 55000000, "primary_value_cents")
    A.assert_money(review["second_value_cents"], 49000000, "second_value_cents")
    A.assert_money(review["reconciled_value_cents"], 49000000,
                   "reconciled_value_cents")
    A.assert_pct_2dp(review["variance_pct"], "12.24", "variance_pct")
    A.assert_fields(review, {"second_valuation_status": "SECOND_RECONCILED",
                             "primary_review_status": "PRIMARY_ESCALATED",
                             "escalation_reason": "VARIANCE_ABOVE_TOLERANCE"})

    # Hop 3: loan-to-value is rebased on the new basis in a single rounding.
    after = fx.get_loan_file(api, loan_file["id"])
    A.assert_pct_2dp(after["ltv_pct"], "81.63", "ltv_pct")


def test_the_rebased_metric_voids_the_pinned_waiver_and_suspends_the_file(api):
    """The last two hops are state: the waiver dies with its metric.

    PRD 3.7: "a waiver is valid only for the exact metric value it was granted
    against, so when the loan file metric named by the overlay's `rule_metric` changes
    value, an `APPROVED` request moves `APPROVED → VOIDED`, records
    `PINNED_METRIC_CHANGED` in `decision_reason`, and the breach returns to
    `unresolved_overlay_breach_count`; a loan file in `UNDERWRITING` is cascaded to
    `SUSPENDED` as a result."

    Design: Difficulty/transitive_cascade/second_valuation_acceptance_cascade_to_exception_void
    """
    loan_file, request, second = _waived_file_awaiting_its_second_appraisal(api)

    fx.accept_valuation(api, second["id"], APPRAISAL_REVIEWER)

    # Hop 4: the approved exception is voided and the breach counts again.
    voided = _exception(api, request["id"])
    A.assert_fields(voided, {"status": "VOIDED",
                             "decision_reason": "PINNED_METRIC_CHANGED"})
    after = fx.get_loan_file(api, loan_file["id"])
    A.assert_fields(after, {"unresolved_overlay_breach_count": 1})
    A.assert_codes_in_order(after["overlay_breach_codes"], ["OVL-LTV"],
                            "overlay_breach_codes")

    # Hop 5: the file itself is suspended.
    A.assert_fields(after, {"status": "SUSPENDED"})

    # Coverage does not depend on value, so the cascade leaves it alone.
    A.assert_fields(after, {"second_valuation_required": True})
    A.assert_ratio_4dp(after["dscr_ratio"], "1.1960", "dscr_ratio")
