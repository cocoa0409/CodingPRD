"""Conserved quantities: an undo must restore the aggregate to the last decimal.

Both scenarios perturb an aggregate and then reverse the perturbation. The point
is not that the undo succeeds but that the restored figures are byte-identical to
the pre-perturbation snapshot, which only holds when the aggregate is recomputed
from the surviving member set rather than unwound by an incremental delta.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    SECURITIZATION_ANALYST,
    underwriter,
)

INVESTOR = "INV-ATLAS"


def _pool(api, pool_id):
    return validate_success(api.get_pool(pool_id, SECURITIZATION_ANALYST))


def _closed_investment_loan(api, program_id, borrower_id, uw_id, *,
                            loan_amount_cents, property_value_cents, note_rate_pct,
                            purpose, monthly_insurance_cents, monthly_hoa_cents,
                            gross_market_rent_cents, lease_rent_cents):
    """Carry one DSCR investment loan all the way to ``CLOSED``."""
    overrides = dict(
        loan_amount_cents=loan_amount_cents,
        property_value_cents=property_value_cents, occupancy="INVESTMENT",
        purpose=purpose, lien_position="FIRST", note_rate_pct=note_rate_pct,
        apor_pct=6.100, term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=monthly_insurance_cents,
        monthly_hoa_cents=monthly_hoa_cents,
        gross_market_rent_cents=gross_market_rent_cents,
        lease_rent_cents=lease_rent_cents)
    if purpose == "PURCHASE":
        overrides["purchase_price_cents"] = property_value_cents
    loan_file = fx.create_loan_file(api, borrower_id, program_id, INVESTOR,
                                    **overrides)
    uw = underwriter(uw_id)
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", property_value_cents,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    fx.close(api, loan_file["id"])
    return loan_file


def _pool_and_two_closed_loans(api):
    """An OPEN pool plus loan A at 8.750 on 60000000 and loan B at 9.250 on 40000000.

    The program's second-valuation triggers are 90.00 LTV and 150000000 cents, and
    neither loan reaches either, so both files clear on the primary appraisal alone.
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True)
    borrower = fx.create_borrower(
        api, legal_name="Quarry Bend Estates LLC", fico_score=748,
        self_employed_flag=False, entity_ownership_pct=100.00,
        monthly_debt_obligations_cents=0, verified_liquid_assets_cents=5000000,
        age_years=57)
    pool = fx.create_pool(api, "PL-2026A", INVESTOR, 200000000)
    loan_a = _closed_investment_loan(
        api, program["id"], borrower["id"], "uw-17",
        loan_amount_cents=60000000, property_value_cents=80000000,
        note_rate_pct=8.750, purpose="PURCHASE", monthly_insurance_cents=20000,
        monthly_hoa_cents=0, gross_market_rent_cents=620000,
        lease_rent_cents=640000)
    loan_b = _closed_investment_loan(
        api, program["id"], borrower["id"], "uw-18",
        loan_amount_cents=40000000, property_value_cents=55000000,
        note_rate_pct=9.250, purpose="RATE_TERM_REFI",
        monthly_insurance_cents=18000, monthly_hoa_cents=15000,
        gross_market_rent_cents=420000, lease_rent_cents=480000)
    return pool, loan_a, loan_b


def test_a_second_member_moves_the_weighted_average_coupon(api):
    """8.7500 on loan A alone becomes 8.9500 once loan B is delivered.

    PRD 3.9: "`member_loan_count` is the count of members,
    `aggregate_scheduled_balance_cents` the sum of their `loan_amount_cents` in whole
    cents, and `weighted_avg_coupon_pct` the balance-weighted mean of their
    `note_rate_pct`: the sum over members of balance times note rate, divided by the
    aggregate balance, with the single rounding to 4 decimals applied once to the final
    quotient."

    Design: Difficulty/compensating_invariant/pool_balance_and_weighted_coupon_restored_exactly_after_removal
    """
    pool, loan_a, loan_b = _pool_and_two_closed_loans(api)

    after_a = fx.assign_loan(api, pool["id"], loan_a["id"], pool["version"])
    A.assert_fields(after_a, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(after_a["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(after_a["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(after_a, pool["version"] + 1)

    after_b = fx.assign_loan(api, pool["id"], loan_b["id"], after_a["version"])
    A.assert_fields(after_b, {"member_loan_count": 2, "status": "OPEN"})
    A.assert_money(after_b["aggregate_scheduled_balance_cents"], 100000000,
                   "aggregate_scheduled_balance_cents")
    # (60000000 x 8.750 + 40000000 x 9.250) / 100000000 = 8.9500 exactly.
    A.assert_ratio_4dp(after_b["weighted_avg_coupon_pct"], "8.9500",
                       "weighted_avg_coupon_pct")
    A.assert_version(after_b, after_a["version"] + 1)
    A.assert_fields(fx.get_loan_file(api, loan_a["id"]), {"pool_id": pool["id"],
                                                          "status": "CLOSED"})
    A.assert_fields(fx.get_loan_file(api, loan_b["id"]), {"pool_id": pool["id"],
                                                          "status": "CLOSED"})


def test_removing_that_member_restores_the_coupon_to_the_last_decimal(api):
    """The pool returns to 8.7500 with no 8.7499 or 8.7501 drift.

    PRD 3.9: "Pool metrics are always recomputed from scratch over the member set, never
    adjusted by delta, because incremental arithmetic accumulates rounding drift in the
    coupon." "Because removal recomputes rather than subtracts, removing a loan restores
    the pre-assignment aggregates exactly."

    Design: Difficulty/compensating_invariant/pool_balance_and_weighted_coupon_restored_exactly_after_removal
    """
    pool, loan_a, loan_b = _pool_and_two_closed_loans(api)
    after_a = fx.assign_loan(api, pool["id"], loan_a["id"], pool["version"])
    after_b = fx.assign_loan(api, pool["id"], loan_b["id"], after_a["version"])

    restored = fx.remove_loan(api, pool["id"], "LOAN_INELIGIBLE",
                              after_b["version"], loan_b["id"])

    A.assert_fields(restored, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(restored["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(restored["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(restored, after_b["version"] + 1)

    # Byte-identical to the post-first-assignment snapshot on all three metrics.
    for field in ("member_loan_count", "aggregate_scheduled_balance_cents"):
        assert restored[field] == after_a[field], (
            f"{field} was not restored: {restored[field]!r} != {after_a[field]!r}")
    assert A.as_decimal(restored["weighted_avg_coupon_pct"]) == \
        A.as_decimal(after_a["weighted_avg_coupon_pct"])

    # Removal is a membership operation, not a loan-state operation.
    A.assert_is_null(fx.get_loan_file(api, loan_b["id"]), "pool_id")
    A.assert_fields(fx.get_loan_file(api, loan_b["id"]), {"status": "CLOSED"})
    A.assert_fields(fx.get_loan_file(api, loan_a["id"]), {"pool_id": pool["id"],
                                                          "status": "CLOSED"})
    assert restored["version"] > after_b["version"] > after_a["version"] > pool["version"]


BASELINE_CLASSIFICATIONS = {
    "ORIG-1PT": "INCLUDED",
    "TITLE-AFF": "INCLUDED",
    "ESCROW-TAX": "EXCLUDED",
    "APPR-FEE": "EXCLUDED",
    "DISC-BONA": "EXCLUDED",
}


def _classifications(api, loan_file_id):
    rows = validate_success(api.list_fee_items(loan_file_id, LOAN_OFFICER))
    return {row["fee_code"]: row for row in rows}


def _tested_file_with_a_five_line_schedule(api):
    """A 60000000-cent file whose five charges test at 850000 against a 2970000 cap.

    Only two charges are included: the origination points, which are also the file's
    only financed prepaid charge, and the affiliate title charge. The escrow charge
    is excluded by category, the third-party charge because no affiliate retains it,
    and the discount points because they are bona fide.
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
        api, legal_name="Roswitha Klemm", fico_score=712, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=120000,
        verified_liquid_assets_cents=4000000, age_years=46)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, property_value_cents=75000000,
        occupancy="PRIMARY", purpose="RATE_TERM_REFI", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=78000,
        monthly_insurance_cents=22000, monthly_hoa_cents=0)
    uw = underwriter("uw-19")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    fx.create_fee_item(api, loan_file["id"], "ORIG-1PT", "ORIGINATION_POINTS",
                       600000, LOAN_OFFICER, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.create_fee_item(api, loan_file["id"], "TITLE-AFF", "AFFILIATE_TITLE",
                       250000, LOAN_OFFICER, paid_to_affiliate_flag=True)
    fx.create_fee_item(api, loan_file["id"], "ESCROW-TAX", "ESCROW_TAXES",
                       180000, LOAN_OFFICER)
    fx.create_fee_item(api, loan_file["id"], "APPR-FEE", "THIRD_PARTY_UNAFFILIATED",
                       300000, LOAN_OFFICER, paid_to_affiliate_flag=False)
    fx.create_fee_item(api, loan_file["id"], "DISC-BONA", "DISCOUNT_POINTS",
                       500000, LOAN_OFFICER, bona_fide_discount_flag=True)
    baseline = fx.run_points_and_fees_test(api, loan_file["id"], uw)
    return loan_file, baseline, uw


def _assert_baseline_numbers(row):
    A.assert_money(row["points_and_fees_total_cents"], 850000,
                   "points_and_fees_total_cents")
    A.assert_money(row["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")
    A.assert_money(row["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_fields(row, {"points_and_fees_test_result": "PASS"})
    A.assert_money(row["pitia_monthly_cents"], 572020, "pitia_monthly_cents")


def test_one_prepaid_charge_moves_the_total_up_and_the_cap_down_at_once(api):
    """Adding a financed 2200000 adjustment perturbs both sums and flips to FAIL.

    PRD 3.6: "Step three sums `amount_cents` over the included charges that also carry
    `prepaid_finance_charge_flag`, and sets `total_loan_amount_cents` to
    `loan_amount_cents` less that financed-prepaid sum." "the classification, the
    included total, the financed-prepaid total and `total_loan_amount_cents` — steps one
    through three — are always recomputed, while the cap tier and the pass-or-fail verdict
    of steps four and five are recomputed only once a test has already been run on the
    file, that is, only when `points_and_fees_test_result` is something other than
    `NOT_TESTED`."

    Design: Difficulty/compensating_invariant/points_and_fees_totals_and_cap_restored_exactly_after_fee_void
    """
    loan_file, baseline, uw = _tested_file_with_a_five_line_schedule(api)
    _assert_baseline_numbers(baseline)
    for code, expected in BASELINE_CLASSIFICATIONS.items():
        A.assert_fields(_classifications(api, loan_file["id"])[code],
                        {"inclusion_in_test": expected, "status": "ACTIVE"})

    fx.create_fee_item(api, loan_file["id"], "LLPA-CASHOUT",
                       "LOAN_LEVEL_PRICE_ADJUSTMENT", 2200000, uw,
                       prepaid_finance_charge_flag=True)

    perturbed = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_money(perturbed["points_and_fees_total_cents"], 3050000,
                   "points_and_fees_total_cents")
    A.assert_money(perturbed["total_loan_amount_cents"], 57200000,
                   "total_loan_amount_cents")
    A.assert_money(perturbed["points_and_fees_cap_cents"], 2860000,
                   "points_and_fees_cap_cents")
    A.assert_fields(perturbed, {"points_and_fees_test_result": "FAIL"})
    # Fee items never touch the payment.
    A.assert_money(perturbed["pitia_monthly_cents"], 572020, "pitia_monthly_cents")

    surviving = _classifications(api, loan_file["id"])
    for code, expected in BASELINE_CLASSIFICATIONS.items():
        A.assert_fields(surviving[code], {"inclusion_in_test": expected})
    A.assert_fields(surviving["LLPA-CASHOUT"], {"inclusion_in_test": "INCLUDED"})


def test_voiding_that_charge_restores_all_three_figures_exactly(api):
    """The totals a void produces are exactly the totals that preceded the addition.

    PRD 3.6: "Voiding a charge requires a `void_reason`, moves it `ACTIVE → VOIDED`, and
    removes it from every aggregate — a void restores the prior totals exactly."
    "Voided charges are absent from both sums, so the totals a void produces are exactly
    the totals that preceded the corresponding addition."

    Design: Difficulty/compensating_invariant/points_and_fees_totals_and_cap_restored_exactly_after_fee_void
    """
    loan_file, baseline, uw = _tested_file_with_a_five_line_schedule(api)
    charge = fx.create_fee_item(api, loan_file["id"], "LLPA-CASHOUT",
                                "LOAN_LEVEL_PRICE_ADJUSTMENT", 2200000, uw,
                                prepaid_finance_charge_flag=True)

    voided = fx.void_fee_item(api, charge["id"], uw,
                              "LLPA repriced and re-disclosed")
    A.assert_fields(voided, {"status": "VOIDED",
                             "void_reason": "LLPA repriced and re-disclosed"})

    restored = fx.get_loan_file(api, loan_file["id"], uw)
    _assert_baseline_numbers(restored)
    for field in ("points_and_fees_total_cents", "total_loan_amount_cents",
                  "points_and_fees_cap_cents", "points_and_fees_test_result"):
        assert restored[field] == baseline[field], (
            f"{field} was not restored: {restored[field]!r} != {baseline[field]!r}")

    surviving = _classifications(api, loan_file["id"])
    for code, expected in BASELINE_CLASSIFICATIONS.items():
        A.assert_fields(surviving[code], {"inclusion_in_test": expected,
                                          "status": "ACTIVE"})
