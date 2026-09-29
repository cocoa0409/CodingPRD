"""Validation corners: the ladder's own banding, two inclusive thresholds, one
method-conditional rule, one closed temporal interval and one cascading
invalidation of the safe-harbour class.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_BORROWER_NOT_FOUND,
    ERR_HIGH_COST_LOAN_PROHIBITED,
    ERR_INSUFFICIENT_STATEMENT_MONTHS,
    ERR_INVALID_REQUEST,
    ERR_MISSING_ROLE_HEADER,
    ERR_OVERLAY_NOT_BREACHED,
    ERR_POOL_BALANCE_CAP_EXCEEDED,
    ERR_UNAUTHORIZED,
    ERR_UNKNOWN_ROLE,
    ERR_VALUATION_EXPIRED,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    SECURITIZATION_ANALYST,
    headers_with_unknown_role,
    headers_without_role,
    underwriter,
)

INVESTOR = "INV-ALPHA"
# A syntactically valid UUID that is never created by any of these tests.
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _dscr_program(api, **overrides):
    payload = dict(
        name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00, min_fico=660,
        min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True,
    )
    payload.update(overrides)
    return fx.create_program(api, "DSCR", **payload)


def _borrower(api, legal_name, verified_liquid_assets_cents, **overrides):
    payload = dict(legal_name=legal_name, fico_score=700,
                   monthly_debt_obligations_cents=0,
                   verified_liquid_assets_cents=verified_liquid_assets_cents,
                   age_years=50)
    payload.update(overrides)
    return fx.create_borrower(api, **payload)


def _dscr_investment_file(api, borrower_id, program_id, **overrides):
    """60000000 cents interest-only at 8.750: PITIA 517500, LTV 75.00, DSCR 1.2367."""
    payload = dict(
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=8.750, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000,
    )
    payload.update(overrides)
    return fx.create_loan_file(api, borrower_id, program_id, INVESTOR, **payload)


def _origination_fee(api, loan_file_id, amount_cents=600000):
    """One financed origination charge, the only entry in the fee schedule."""
    return fx.create_fee_item(api, loan_file_id, "F-ORIG", "ORIGINATION_POINTS",
                              amount_cents, LOAN_OFFICER,
                              prepaid_finance_charge_flag=True)


def _underwritten_dscr_file(api, program_id, legal_name, assets, uw_id,
                            fee_amount_cents=600000,
                            appraised_value_cents=80000000, **file_overrides):
    """A DSCR file in UNDERWRITING with its appraisal cleared, fees tested and
    ability-to-repay determined, so that approval is the only remaining act."""
    borrower = _borrower(api, legal_name, assets)
    loan_file = _dscr_investment_file(api, borrower["id"], program_id,
                                      **file_overrides)
    uw = underwriter(uw_id)
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    _origination_fee(api, loan_file["id"], fee_amount_cents)
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", appraised_value_cents,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    return loan_file, uw


def _closed_dscr_file(api, program_id, legal_name, assets, uw_id, **overrides):
    loan_file, uw = _underwritten_dscr_file(api, program_id, legal_name, assets,
                                            uw_id, **overrides)
    fx.approve(api, loan_file["id"], uw)
    return loan_file, fx.close(api, loan_file["id"])


def test_an_exception_needs_a_live_breach_and_no_live_request(api):
    """Both halves of the waiver rule report one identifier on the same file.

    PRD 3.7: "Three conditions must hold, and all three failures report
    `ERR_OVERLAY_NOT_BREACHED`: the named overlay must currently appear in the file's
    `overlay_breach_codes`, since there is nothing to waive on an overlay the file
    already satisfies" and "there must be no live request — one already
    `PENDING_REVIEW`, `AWAITING_SECOND_SIGNATURE` or `APPROVED` — for the same loan
    file and overlay pair."

    PRD 3.7: "the overlay is satisfied when its `comparator` is `GTE` and the metric
    is at least `threshold_value`", so the 700-score borrower clears OV-SAT at 660
    and breaches OV-BREACH at 740.

    Design: Corner/validations/corner_exception_against_satisfied_or_duplicated_overlay_rejected
    """
    program = _dscr_program(api)
    ov_sat = fx.create_overlay(api, INVESTOR, "OV-SAT", "MIN_FICO", "GTE", 660,
                               waivable_flag=True, required_authority_tier=1,
                               severity="MINOR")
    ov_breach = fx.create_overlay(api, INVESTOR, "OV-BREACH", "MIN_FICO", "GTE", 740,
                                  waivable_flag=True, required_authority_tier=1,
                                  severity="MINOR")
    borrower = _borrower(api, "Iris Waiver", 5000000)
    loan_file = _dscr_investment_file(api, borrower["id"], program["id"])
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.attach_escrow_fee(api, loan_file["id"])
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    A.assert_codes_in_order(submitted["overlay_breach_codes"], ["OV-BREACH"],
                            "overlay_breach_codes")
    A.assert_fields(submitted, {"unresolved_overlay_breach_count": 1})
    first = fx.create_exception_request(
        api, loan_file["id"], ov_breach["id"], uw,
        justification="Reserves offset the 700 score")
    A.assert_fields(first, {"status": "PENDING_REVIEW",
                            "required_authority_tier": 1,
                            "requested_by_user_id": "uw-1"})
    assert A.as_decimal(first["pinned_metric_value"]) == A.as_decimal(700)

    against_satisfied = api.create_exception_request(
        F.exception_request_payload(
            loan_file["id"], ov_sat["id"],
            justification="Pre-emptive waiver on an overlay we already clear"), uw)
    against_live_request = api.create_exception_request(
        F.exception_request_payload(loan_file["id"], ov_breach["id"],
                                    justification="Second bite at the same overlay"),
        uw)

    validate_error(against_satisfied, ERR_OVERLAY_NOT_BREACHED)
    validate_error(against_live_request, ERR_OVERLAY_NOT_BREACHED)
    listed = api.list_exception_requests(uw, {"loan_file_id": loan_file["id"]})
    rows = validate_success(listed)
    A.assert_ids_equal(rows, [first["id"]], "exception request ids")
    A.assert_fields(rows[0], {"status": "PENDING_REVIEW"})
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)


def test_reserves_exactly_at_the_program_minimum_clear_the_inclusive_floor(api):
    """3105000 cents over a 517500 payment is 6.00 months, and 6.00 is enough.

    PRD 3.8: "`documented_reserves_months` must be at least the program's
    `min_reserves_months`, inclusively, or the refusal is `ERR_RESERVES_INSUFFICIENT`."
    and "a `DSCR` file, whose `dti_pct` is null, is exempt from this rule and is
    governed by the coverage-ratio floor instead".

    PRD 3.3: "`documented_reserves_months` is the borrower's
    `verified_liquid_assets_cents` divided by `pitia_monthly_cents`, rounded half up to
    two decimals".

    Design: Corner/validations/corner_reserves_exactly_at_program_minimum_passes_approval
    """
    program = _dscr_program(api, min_reserves_months=6)
    loan_file, uw = _underwritten_dscr_file(api, program["id"], "Jonas Exact",
                                            3105000, "uw-1")

    approved = fx.approve(api, loan_file["id"], uw)

    A.assert_money(approved["pitia_monthly_cents"], 517500, "pitia_monthly_cents")
    A.assert_decimal_equals(approved["documented_reserves_months"], "6.00", 2,
                            "documented_reserves_months")
    A.assert_fields(approved, {"status": "APPROVED",
                               "points_and_fees_test_result": "PASS",
                               "atr_documentation_status": "EXEMPT",
                               "safe_harbor_class": "EXEMPT_BUSINESS_PURPOSE",
                               "securitization_eligible": True})
    A.assert_ratio_4dp(approved["dscr_ratio"], "1.2367", "dscr_ratio")
    A.assert_is_null(approved, "dti_pct")
    A.assert_pct_2dp(approved["ltv_pct"], "75.00", "ltv_pct")


def test_the_ladder_reports_the_highest_band_each_request_violates(api):
    """Five requests, each defective twice over, each answered by its highest band.

    PRD 2.8: "When a single request would fail more than one rule, the platform reports
    the failure that stands highest on a fixed ladder."

    PRD 2.1: "If `X-User-Role` is absent, empty, or consists only of whitespace, the
    request is rejected with `ERR_MISSING_ROLE_HEADER` (HTTP 401)" and "If the supplied
    role is not one of the eight roles the platform recognises, the request is rejected
    with `ERR_UNKNOWN_ROLE` (HTTP 401)." and "Only once both headers are accepted does
    the platform consider whether the role is permitted to perform the requested
    operation; a role that is not listed for the endpoint is rejected with
    `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.8: "The applicable code is the one naming the missing resource" and
    "`ERR_INVALID_REQUEST` — on every POST endpoint: a non-optional input field is
    missing".

    Design: Corner/validations/corner_authentication_precedes_existence_precedes_shape
    """
    program = _dscr_program(api)
    borrower = _borrower(api, "Kara Ladder", 5000000)
    facts = dict(loan_amount_cents=60000000, purchase_price_cents=80000000,
                 property_value_cents=80000000, occupancy="INVESTMENT",
                 purpose="PURCHASE", lien_position="FIRST", apor_pct=6.100,
                 term_months=360, amortization_type="INTEREST_ONLY",
                 monthly_taxes_cents=60000, monthly_insurance_cents=20000,
                 note_rate_pct=None)
    unresolvable = F.loan_file_payload(MISSING_ID, program["id"], INVESTOR, **facts)
    resolvable = F.loan_file_payload(borrower["id"], program["id"], INVESTOR, **facts)
    # The one shape defect these payloads carry is the missing note rate.
    assert "note_rate_pct" not in unresolvable and "note_rate_pct" not in resolvable

    no_role = api.get_loan_file(MISSING_ID, headers_without_role("lo-1"))
    unknown_role = api.get_loan_file(MISSING_ID,
                                     headers_with_unknown_role("lo-1", "Auditor"))
    wrong_role = api.create_loan_file(unresolvable, SECURITIZATION_ANALYST)
    bad_foreign_key = api.create_loan_file(unresolvable, LOAN_OFFICER)
    bad_shape = api.create_loan_file(resolvable, LOAN_OFFICER)

    # A missing role header outranks the 404 the path would otherwise produce.
    validate_error(no_role, ERR_MISSING_ROLE_HEADER)
    validate_error(unknown_role, ERR_UNKNOWN_ROLE)
    # SecuritizationAnalyst is absent from the roles of POST /loan-files, so neither
    # the unresolvable borrower nor the missing note rate is ever reached.
    validate_error(wrong_role, ERR_UNAUTHORIZED)
    validate_error(bad_foreign_key, ERR_BORROWER_NOT_FOUND)
    validate_error(bad_shape, ERR_INVALID_REQUEST)

    listing = api.list_loan_files(LOAN_OFFICER)
    assert validate_success(listing) == []
    A.assert_meta_pagination(listing.json()["meta"], 10, 0, 0, False)


def test_the_pool_balance_cap_is_an_inclusive_aggregate_ceiling(api):
    """Two individually poolable loans; the aggregate decides which pool takes them.

    PRD 3.9: "Finally the balance cap applies: the assignment must not push
    `aggregate_scheduled_balance_cents` above the pool's `target_balance_cents`. That cap
    is inclusive — landing exactly on the target is allowed, exceeding it by a single cent
    is not — and a breach is refused with `ERR_POOL_BALANCE_CAP_EXCEEDED`." and "On
    success the loan's `pool_id` is set, the three pool metrics are recomputed, the pool's
    `version` increments by one".

    PRD 3.9: "`weighted_avg_coupon_pct` the balance-weighted mean of their
    `note_rate_pct`: the sum over members of balance times note rate, divided by the
    aggregate balance, with the single rounding to 4 decimals applied once to the final
    quotient".

    Design: Corner/validations/corner_pool_target_balance_is_an_inclusive_aggregate_ceiling
    """
    program = _dscr_program(api)
    file_a, closed_a = _closed_dscr_file(api, program["id"], "Mona Alpha", 5000000,
                                        "uw-1")
    file_b, closed_b = _closed_dscr_file(
        api, program["id"], "Nils Beta", 3000000, "uw-1",
        fee_amount_cents=400000, appraised_value_cents=55000000,
        loan_amount_cents=40000000, purchase_price_cents=55000000,
        property_value_cents=55000000, note_rate_pct=9.250,
        monthly_insurance_cents=18000, monthly_hoa_cents=15000,
        gross_market_rent_cents=420000, lease_rent_cents=480000)
    A.assert_fields(closed_a, {"status": "CLOSED", "securitization_eligible": True})
    A.assert_fields(closed_b, {"status": "CLOSED", "securitization_eligible": True})
    pool_cap = fx.create_pool(api, "P-CAP", INVESTOR, 99999999)
    pool_exact = fx.create_pool(api, "P-EXACT", INVESTOR, 40000000)

    first = fx.assign_loan(api, pool_cap["id"], file_a["id"], pool_cap["version"])
    refused = api.assign_loan_to_pool(
        pool_cap["id"],
        F.pool_assignment_payload(file_b["id"], first["version"]),
        SECURITIZATION_ANALYST)

    A.assert_money(first["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_fields(first, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_ratio_4dp(first["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(first, pool_cap["version"] + 1)

    # 60000000 + 40000000 is 100000000, one cent above the 99999999 target.
    validate_error(refused, ERR_POOL_BALANCE_CAP_EXCEEDED)
    unchanged = validate_success(api.get_pool(pool_cap["id"], SECURITIZATION_ANALYST))
    A.assert_money(unchanged["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_fields(unchanged, {"member_loan_count": 1})
    A.assert_version(unchanged, first["version"])
    A.assert_is_null(fx.get_loan_file(api, file_b["id"]), "pool_id")

    # Landing exactly on the target is allowed. The refused assignment above left
    # file_b unpooled, so this is the first membership write it takes.
    third = fx.assign_loan(api, pool_exact["id"], file_b["id"],
                           pool_exact["version"])
    A.assert_money(third["aggregate_scheduled_balance_cents"], 40000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_money(third["target_balance_cents"], 40000000, "target_balance_cents")
    A.assert_fields(third, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_ratio_4dp(third["weighted_avg_coupon_pct"], "9.2500",
                       "weighted_avg_coupon_pct")
    A.assert_fields(fx.get_loan_file(api, file_b["id"]), {"pool_id": pool_exact["id"]})


def _thirty_million_file(api, borrower_id, program_id):
    """30000000 cents fully amortizing at 7.500 with 65000 of escrow: PITIA 274764."""
    return fx.create_loan_file(
        api, borrower_id, program_id, INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)


def test_the_month_count_rule_is_conditional_on_the_worksheet_method(api):
    """Three months are too few; zero months are not too few on a depletion sheet.

    PRD 3.4: "For a bank-statement worksheet the count of `INCLUDED` months must equal
    the program's `statement_period_months` exactly — fewer months is insufficient
    documentation and more months is an unaudited sample — and any other count is refused
    with `ERR_INSUFFICIENT_STATEMENT_MONTHS`." and "`eligible_deposit_total_cents`,
    `net_deposit_total_cents` and `included_month_count` are 0 for any non-bank-statement
    worksheet" and "the accepted worksheet's `monthly_qualifying_income_cents` is copied
    onto the file's `qualifying_income_monthly_cents`; the file's `dti_pct`,
    `residual_income_cents` and `documented_reserves_months` are recomputed".

    PRD 3.3 opens a file with `qualifying_income_monthly_cents` at 0, so the refused
    acceptance leaves that figure at 0 rather than at null.

    Design: Corner/validations/corner_included_month_count_rule_applies_only_to_bank_statement_worksheets
    """
    months = [
        ("2026-05-01T00:00:00Z", "2026-06-01T00:00:00Z", 12222221, 0),
        ("2026-06-01T00:00:00Z", "2026-07-01T00:00:00Z", 12222221, 0),
        ("2026-07-01T00:00:00Z", "2026-08-01T00:00:00Z", 12500000, 277780),
    ]
    bs_program = fx.create_program(
        api, "BANK_STATEMENT_12MO", name="Bank Statement 12",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=3, max_dti_pct=55.00, min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    ad_program = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion 84",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=60.00, min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = _borrower(api, "Priya Conditional", 4000000,
                         monthly_debt_obligations_cents=90000,
                         self_employed_flag=True)
    uw = underwriter("uw-1")

    bs_file = _thirty_million_file(api, borrower["id"], bs_program["id"])
    fx.select_doc_type(api, bs_file["id"], "BANK_STATEMENT", uw)
    _origination_fee(api, bs_file["id"], 300000)
    bs_submitted = fx.submit_to_underwriting(api, bs_file["id"])
    bs_sheet = fx.create_worksheet(api, bs_file["id"], "BANK_STATEMENT",
                                   bs_submitted["version"], uw,
                                   expense_factor_source="PROGRAM_DEFAULT")
    for start, end, deposits, ineligible in months:
        fx.attach_statement_month(api, bs_sheet["id"], start, end, deposits, uw,
                                  ineligible_transfer_cents=ineligible)
    bs_calculated = fx.calculate_worksheet(api, bs_sheet["id"], uw)
    A.assert_money(bs_calculated["eligible_deposit_total_cents"], 36666662,
                   "eligible_deposit_total_cents")
    A.assert_money(bs_calculated["net_deposit_total_cents"], 18333332,
                   "net_deposit_total_cents")
    A.assert_money(bs_calculated["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
    A.assert_fields(bs_calculated, {"included_month_count": 3,
                                    "status": "CALCULATED"})

    ad_file = _thirty_million_file(api, borrower["id"], ad_program["id"])
    fx.select_doc_type(api, ad_file["id"], "ASSET_DEPLETION", uw)
    _origination_fee(api, ad_file["id"], 300000)
    ad_submitted = fx.submit_to_underwriting(api, ad_file["id"])
    ad_sheet = fx.create_worksheet(api, ad_file["id"], "ASSET_DEPLETION",
                                   ad_submitted["version"], uw,
                                   asset_bucket_checking_cents=15000000,
                                   asset_bucket_brokerage_cents=22222225,
                                   asset_bucket_retirement_cents=30000001)
    ad_calculated = fx.calculate_worksheet(api, ad_sheet["id"], uw)
    A.assert_money(ad_calculated["eligible_assets_after_haircut_cents"], 56000004,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(ad_calculated["depletable_assets_cents"], 54351420,
                   "depletable_assets_cents")
    A.assert_money(ad_calculated["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")
    A.assert_fields(ad_calculated, {"included_month_count": 0,
                                    "status": "CALCULATED"})
    before = fx.get_loan_file(api, bs_file["id"], uw)

    refused = api.accept_worksheet(bs_sheet["id"], uw)
    accepted = fx.accept_worksheet(api, ad_sheet["id"], uw)

    validate_error(refused, ERR_INSUFFICIENT_STATEMENT_MONTHS)
    A.assert_fields(validate_success(api.get_worksheet(bs_sheet["id"], uw)),
                    {"status": "CALCULATED"})
    untouched = fx.get_loan_file(api, bs_file["id"], uw)
    A.assert_money(untouched["qualifying_income_monthly_cents"], 0,
                   "qualifying_income_monthly_cents")
    A.assert_is_null(untouched, "dti_pct")
    A.assert_version(untouched, before["version"])

    # The month-count rule never evaluates for a non-bank-statement method.
    A.assert_fields(accepted, {"status": "ACCEPTED", "included_month_count": 0})
    published = fx.get_loan_file(api, ad_file["id"], uw)
    A.assert_money(published["qualifying_income_monthly_cents"], 647041,
                   "qualifying_income_monthly_cents")
    A.assert_pct_2dp(published["dti_pct"], "56.37", "dti_pct")
    A.assert_money(published["residual_income_cents"], 282277,
                   "residual_income_cents")
    A.assert_decimal_equals(published["documented_reserves_months"], "14.56", 2,
                            "documented_reserves_months")


def test_the_valuation_validity_window_is_a_closed_interval_at_day_one_hundred_twenty(api):
    """Nothing but the clock separates the refused close from the accepted one.

    PRD 3.8: "the accepted valuation supporting `reconciled_value_cents` must still be
    inside its 120-day validity window at close time: the window is evaluated as a
    closed interval running from the order's `effective_date`, so the
    one-hundred-and-twentieth day is still valid and the one-hundred-and-twenty-first
    is expired, and a stale valuation is refused with `ERR_VALUATION_EXPIRED`."

    PRD 2.6: "An administrative capability available to all eight roles accepts a
    `current_utc` instant and moves the logical clock to it; the call stores no derived
    values and recomputes nothing, because every time-dependent rule reads the clock at
    the moment it is evaluated."

    The appraisal is effective 2026-05-01, so day 120 falls on 2026-08-29 and
    2026-08-30 is day 121.

    Design: Corner/validations/corner_valuation_validity_window_closed_at_day_one_hundred_twenty
    """
    program = _dscr_program(api)
    loan_file, uw = _underwritten_dscr_file(api, program["id"], "Tomas Temporal",
                                            5000000, "uw-1")
    approved = fx.approve(api, loan_file["id"], uw)
    A.assert_fields(approved, {"status": "APPROVED",
                               "securitization_eligible": True})

    fx.set_clock(api, "2026-08-30T00:00:00Z", LOAN_OFFICER)
    refused = api.close_loan_file(loan_file["id"], LOAN_OFFICER)

    validate_error(refused, ERR_VALUATION_EXPIRED)
    untouched = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(untouched, {"status": "APPROVED",
                                "securitization_eligible": True})

    fx.set_clock(api, "2026-08-29T00:00:00Z", LOAN_OFFICER)
    closed = fx.close(api, loan_file["id"])

    A.assert_fields(closed, {"status": "CLOSED",
                             "securitization_eligible": True})
    review = fx.get_review(api, loan_file["id"])
    A.assert_money(review["reconciled_value_cents"], 80000000,
                   "reconciled_value_cents")
    A.assert_fields(review, {"primary_review_status": "PRIMARY_CLEARED",
                             "second_valuation_status": "SECOND_NOT_REQUIRED"})


def _profit_and_loss_program(api):
    return fx.create_program(
        api, "PROFIT_AND_LOSS", name="CPA P and L",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=3, max_dti_pct=55.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)


def _fee_rows(api, loan_file_id):
    return {row["fee_code"]: row
            for row in validate_success(api.list_fee_items(loan_file_id, LOAN_OFFICER))}


def test_the_fee_verdict_must_exist_before_the_safe_harbour_class_can_condemn(api):
    """The same unchanged file classifies twice, and only the second run condemns it.

    PRD 3.6: "If `points_and_fees_test_result` is `FAIL`, `safe_harbor_class` becomes
    `HIGH_COST_PROHIBITED`. Otherwise, if documentation is not complete, it becomes
    `NOT_EVALUATED`. Otherwise, if `rate_spread_pct` is strictly greater than the
    applicable threshold, it becomes `HIGHER_PRICED_NO_PRESUMPTION` — a spread exactly
    equal to the threshold does not trip this branch. Otherwise it becomes
    `ATR_DOCUMENTED_NO_SAFE_HARBOR`."

    PRD 3.6: "if the verdict in `points_and_fees_test_result` changed, it resets
    `atr_documentation_status` to `INCOMPLETE` and `safe_harbor_class` to
    `NOT_EVALUATED`."

    PRD 3.8: "`points_and_fees_test_result` must not be `FAIL`, or the attempt is
    refused with `ERR_HIGH_COST_LOAN_PROHIBITED`." and "`atr_documentation_status` must
    be `DOCUMENTED` or `EXEMPT` with a `safe_harbor_class` other than `NOT_EVALUATED`,
    or the attempt is refused with `ERR_ATR_DOCUMENTATION_INCOMPLETE`" -- both are
    violated here and the ladder reports the first.

    The 12.600 note rate against a 6.100 index is a spread of exactly 6.500, equal to
    the first-lien threshold, so the higher-priced branch never fires and the
    classification turns solely on the fee verdict.

    Design: Corner/validations/corner_safe_harbor_classification_requires_the_fee_test_to_have_run_first
    """
    program = _profit_and_loss_program(api)
    borrower = _borrower(api, "Cassie Cascade", 4000000, self_employed_flag=True)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=12.600, apor_pct=6.100,
        term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=78000, monthly_insurance_cents=22000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "PROFIT_AND_LOSS", uw)
    _origination_fee(api, loan_file["id"])
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    A.assert_money(submitted["pitia_monthly_cents"], 730000, "pitia_monthly_cents")
    worksheet = fx.create_worksheet(api, loan_file["id"], "PROFIT_AND_LOSS",
                                    submitted["version"], uw,
                                    p_and_l_net_income_cents=18333336,
                                    p_and_l_period_months=12)
    fx.calculate_worksheet(api, worksheet["id"], uw)
    fx.accept_worksheet(api, worksheet["id"], uw)
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)

    first = fx.run_atr_determination(api, loan_file["id"], uw)

    A.assert_fields(first, {"atr_documentation_status": "DOCUMENTED",
                            "safe_harbor_class": "ATR_DOCUMENTED_NO_SAFE_HARBOR"})
    A.assert_pct_3dp(first["rate_spread_pct"], "6.500", "rate_spread_pct")
    A.assert_pct_2dp(first["dti_pct"], "47.78", "dti_pct")
    A.assert_money(first["residual_income_cents"], 797778, "residual_income_cents")
    A.assert_decimal_equals(first["documented_reserves_months"], "5.48", 2,
                            "documented_reserves_months")

    fx.create_fee_item(api, loan_file["id"], "F-LLPA",
                       "LOAN_LEVEL_PRICE_ADJUSTMENT", 2500000, LOAN_OFFICER,
                       prepaid_finance_charge_flag=False)
    A.assert_fields(_fee_rows(api, loan_file["id"])["F-LLPA"],
                    {"inclusion_in_test": "INCLUDED", "status": "ACTIVE"})

    tested = fx.run_points_and_fees_test(api, loan_file["id"], uw)

    A.assert_money(tested["points_and_fees_total_cents"], 3100000,
                   "points_and_fees_total_cents")
    A.assert_money(tested["total_loan_amount_cents"], 59400000,
                   "total_loan_amount_cents")
    A.assert_money(tested["points_and_fees_cap_cents"], 2970000,
                   "points_and_fees_cap_cents")
    A.assert_fields(tested, {"points_and_fees_test_result": "FAIL",
                             "atr_documentation_status": "INCOMPLETE",
                             "safe_harbor_class": "NOT_EVALUATED",
                             "securitization_eligible": False})

    refused = api.approve_loan_file(loan_file["id"], uw)
    validate_error(refused, ERR_HIGH_COST_LOAN_PROHIBITED)

    second = fx.run_atr_determination(api, loan_file["id"], uw)
    A.assert_fields(second, {"atr_documentation_status": "DOCUMENTED",
                             "safe_harbor_class": "HIGH_COST_PROHIBITED",
                             "securitization_eligible": False,
                             "status": "UNDERWRITING"})
    A.assert_pct_3dp(second["rate_spread_pct"], "6.500", "rate_spread_pct")
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], uw),
                    {"status": "UNDERWRITING",
                     "safe_harbor_class": "HIGH_COST_PROHIBITED"})
