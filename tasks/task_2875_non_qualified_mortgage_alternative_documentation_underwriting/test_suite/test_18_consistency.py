"""Immediate consistency: the write response is already final, and the parent's
recomputed picture is complete on the very next read with no second write.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_success
from test_helpers.test_users import underwriter

INVESTOR = "INV-ALPHA"
SEASONING = {"FORECLOSURE": 36, "SHORT_SALE": 24, "DEED_IN_LIEU": 24,
             "BK_CH7": 24, "BK_CH13": 12, "MODIFICATION": 12,
             "MORTGAGE_LATE_60": 12}


def test_accepting_a_worksheet_publishes_the_whole_picture_in_one_request(api):
    """The accept body is final and the next read of the parent is already complete.

    PRD 3.4: "Acceptance is what publishes income." and "the accepted worksheet's
    `monthly_qualifying_income_cents` is copied onto the file's
    `qualifying_income_monthly_cents`; the file's `dti_pct`, `residual_income_cents` and
    `documented_reserves_months` are recomputed" and "the overlay sweep re-runs to rebuild
    `overlay_breach_codes` and `unresolved_overlay_breach_count`"

    PRD 2.9: "Whenever a cascade fires, each affected resource has its own `updated_at`
    refreshed and its own `version` incremented, and the caller sees only the resource it
    addressed — the rest must be re-read."

    PRD 3.4: "`eligible_assets_after_haircut_cents` is the sum of those three
    already-rounded components" and "`depletable_assets_cents` is the eligible assets less
    those required reserves, floored at zero" and "`gross_monthly_income_cents` is the
    depletable assets divided by the program's `depletion_horizon_months`, rounded half up
    to the cent in a single rounding, and `monthly_qualifying_income_cents` equals it" and
    "`variant_applied` is `ASSET_DEPLETION_STANDARD`"

    PRD 2.9: "accepting an income worksheet, a points-and-fees verdict that changes, a
    change to the reconciled value, a manual suspension and a cascade-driven suspension all
    reset `atr_documentation_status` to `INCOMPLETE` and `safe_harbor_class` to
    `NOT_EVALUATED`."

    PRD 3.3: "`documented_reserves_months` is the borrower's
    `verified_liquid_assets_cents` divided by `pitia_monthly_cents`, rounded half up to two
    decimals; `residual_income_cents` is `qualifying_income_monthly_cents` less the
    borrower's `monthly_debt_obligations_cents` less `pitia_monthly_cents`" and "`dti_pct`
    is null whenever `qualifying_income_monthly_cents` is 0, and is otherwise the sum of
    `monthly_debt_obligations_cents` and `pitia_monthly_cents`, multiplied by 100 and
    divided by `qualifying_income_monthly_cents`, rounded half up to two decimals"

    PRD 3.3: "it stays null on any file whose `doc_type` is not `DSCR`"

    PRD 3.9: "The loan's `status` must be `APPROVED` or `CLOSED`"

    Design: Corner/consistency_model/corner_immediate_consistency_worksheet_accept_publishes_in_the_same_response
    """
    program = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion Immediate",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        seasoning_matrix=SEASONING)
    borrower = fx.create_borrower(api, legal_name="Immediate Ida",
                                 fico_score=720,
                                 monthly_debt_obligations_cents=90000,
                                 verified_liquid_assets_cents=4000000,
                                 age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "ASSET_DEPLETION", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       300000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    submitted = fx.get_loan_file(api, loan_file["id"], uw)
    worksheet = fx.create_worksheet(api, loan_file["id"], "ASSET_DEPLETION",
                                   submitted["version"], uw,
                                   asset_bucket_checking_cents=15000000,
                                   asset_bucket_brokerage_cents=22222225,
                                   asset_bucket_retirement_cents=30000001)
    fx.calculate_worksheet(api, worksheet["id"], uw)

    accepted = fx.accept_worksheet(api, worksheet["id"], uw)

    # The write response is already the final one: 15000000 + 20000003 + 21000001.
    A.assert_fields(accepted, {"status": "ACCEPTED"})
    A.assert_money(accepted["eligible_assets_after_haircut_cents"], 56000004,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(accepted["depletable_assets_cents"], 54351420,
                   "depletable_assets_cents")
    A.assert_money(accepted["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")

    published = fx.get_loan_file(api, loan_file["id"], uw)

    # No second write, no delay: every dependent is correct on the first read.
    A.assert_money(published["qualifying_income_monthly_cents"], 647041,
                   "qualifying_income_monthly_cents")
    A.assert_money(published["pitia_monthly_cents"], 274764, "pitia_monthly_cents")
    A.assert_pct_2dp(published["dti_pct"], "56.37", "dti_pct")
    A.assert_money(published["residual_income_cents"], 282277,
                   "residual_income_cents")
    A.assert_decimal_equals(published["documented_reserves_months"], "14.56", 2,
                            "documented_reserves_months")
    A.assert_is_null(published, "dscr_ratio")
    A.assert_codes_in_order(published["overlay_breach_codes"], [],
                            "overlay_breach_codes")
    A.assert_fields(published, {"unresolved_overlay_breach_count": 0,
                                "status": "UNDERWRITING",
                                "securitization_eligible": False,
                                "atr_documentation_status": "INCOMPLETE",
                                "safe_harbor_class": "NOT_EVALUATED"})
    for field in ("qualifying_income_monthly_cents", "pitia_monthly_cents",
                  "dti_pct", "residual_income_cents",
                  "documented_reserves_months"):
        assert published[field] is not None, field

    reread = validate_success(api.get_worksheet(worksheet["id"], uw))

    # The write response was not a preliminary view that a later read corrects.
    for field in ("status", "eligible_assets_after_haircut_cents",
                  "depletable_assets_cents", "monthly_qualifying_income_cents",
                  "gross_monthly_income_cents", "variant_applied"):
        assert reread[field] == accepted[field], field


def test_a_fee_write_leaves_the_parent_correct_before_its_own_response_returns(api):
    """Adding and voiding a charge cascades into the file with no intermediate view.

    PRD 3.6: "Step two sets `points_and_fees_total_cents` to the sum of `amount_cents` over
    the included charges." and "Step three sums `amount_cents` over the included charges
    that also carry `prepaid_finance_charge_flag`, and sets `total_loan_amount_cents` to
    `loan_amount_cents` less that financed-prepaid sum." and "when `total_loan_amount_cents`
    is at or above 24,866 dollars, `points_and_fees_cap_cents` is 5.00 percent of
    `total_loan_amount_cents`, rounded half up to the cent"

    PRD 3.6: "A charge is `INCLUDED` when its `fee_category` is `ORIGINATION_POINTS`,
    `AFFILIATE_TITLE`, `PMI_UPFRONT`, `PREPAYMENT_PENALTY` or
    `LOAN_LEVEL_PRICE_ADJUSTMENT`" and "A charge is created `ACTIVE` with `void_reason`
    null."

    PRD 3.6: "Adding or voiding a charge behaves in a deliberately partial way: the
    classification, the included total, the financed-prepaid total and
    `total_loan_amount_cents` — steps one through three — are always recomputed, while the
    cap tier and the pass-or-fail verdict of steps four and five are recomputed only once a
    test has already been run on the file" and "Where such a re-run does change the verdict,
    the ability-to-repay determination is invalidated exactly as an explicit test run would
    invalidate it, and securitization eligibility is recomputed either way."

    PRD 3.6: "Voided charges are absent from both sums, so the totals a void produces are
    exactly the totals that preceded the corresponding addition." and "Voiding a charge
    requires a `void_reason`, moves it `ACTIVE → VOIDED`, and removes it from every
    aggregate"

    PRD 3.6: "the determination short-circuits: `atr_documentation_status` becomes
    `EXEMPT`, `safe_harbor_class` becomes `EXEMPT_BUSINESS_PURPOSE`"

    PRD 2.9: "the caller sees only the resource it addressed — the rest must be re-read."

    Design: Corner/consistency_model/corner_immediate_consistency_fee_recompute_visible_on_the_next_read
    """
    program = fx.create_program(
        api, "DSCR", name="Investor DSCR Immediate", min_dscr=1.1000,
        max_ltv_pct=85.00, min_fico=660, min_reserves_months=6,
        min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True, seasoning_matrix=SEASONING)
    borrower = fx.create_borrower(api, legal_name="Cascade Cara", fico_score=700,
                                 monthly_debt_obligations_cents=0,
                                 verified_liquid_assets_cents=5000000,
                                 age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT",
        purpose="PURCHASE", lien_position="FIRST", note_rate_pct=8.750,
        apor_pct=6.100, term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       600000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)

    tested = fx.get_loan_file(api, loan_file["id"], uw)

    A.assert_money(tested["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")
    A.assert_money(tested["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_money(tested["points_and_fees_total_cents"], 600000,
                   "points_and_fees_total_cents")
    A.assert_fields(tested, {"points_and_fees_test_result": "PASS",
                             "atr_documentation_status": "EXEMPT",
                             "safe_harbor_class": "EXEMPT_BUSINESS_PURPOSE"})

    adjustment = fx.create_fee_item(api, loan_file["id"], "F-LLPA",
                                    "LOAN_LEVEL_PRICE_ADJUSTMENT", 2500000, uw)

    # The child write returns a charge, not the file, so the cascade is invisible here.
    A.assert_fields(adjustment, {"loan_file_id": loan_file["id"],
                                 "fee_code": "F-LLPA",
                                 "status": "ACTIVE",
                                 "inclusion_in_test": "INCLUDED"})
    A.assert_is_null(adjustment, "void_reason")

    flipped = fx.get_loan_file(api, loan_file["id"], uw)

    # The very next read: 600000 + 2500000 is above the unchanged 2970000 cap.
    A.assert_money(flipped["points_and_fees_total_cents"], 3100000,
                   "points_and_fees_total_cents")
    A.assert_fields(flipped, {"points_and_fees_test_result": "FAIL",
                             "atr_documentation_status": "INCOMPLETE",
                             "safe_harbor_class": "NOT_EVALUATED",
                             "securitization_eligible": False})
    A.assert_money(flipped["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_money(flipped["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")

    voided = fx.void_fee_item(api, adjustment["id"], uw,
                              "Fee waived by the investor")
    A.assert_fields(voided, {"status": "VOIDED",
                             "void_reason": "Fee waived by the investor"})

    restored = fx.get_loan_file(api, loan_file["id"], uw)

    # The totals are restored exactly, but the invalidation is not undone.
    A.assert_money(restored["points_and_fees_total_cents"], 600000,
                   "points_and_fees_total_cents")
    A.assert_money(restored["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_money(restored["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")
    A.assert_fields(restored, {"points_and_fees_test_result": "PASS",
                               "atr_documentation_status": "INCOMPLETE",
                               "safe_harbor_class": "NOT_EVALUATED"})
