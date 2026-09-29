"""Endpoint-surface corners: the create-and-read catalog, a single-use action, the
one cross-reference link, three agreeing read channels, a conditional settlement
and four parent-scoped child collections.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_LOAN_ALREADY_POOLED,
    ERR_LOAN_FILE_NOT_FOUND,
    ERR_POOL_NOT_FOUND,
    ERR_POOL_STATE_INVALID,
    ERR_REVIEW_STATE_INVALID,
    ERR_WORKSHEET_NOT_FOUND,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    credit_committee,
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


def _dscr_investment_file(api, borrower_id, program_id, **overrides):
    """60000000 cents interest-only at 8.750: PITIA 517500 and DSCR 1.2367."""
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


def _borrower(api, legal_name, **overrides):
    payload = dict(legal_name=legal_name, fico_score=700,
                   monthly_debt_obligations_cents=0,
                   verified_liquid_assets_cents=5000000, age_years=50)
    payload.update(overrides)
    return fx.create_borrower(api, **payload)


def _origination_fee(api, loan_file_id, amount_cents=600000):
    return fx.create_fee_item(api, loan_file_id, "F-ORIG", "ORIGINATION_POINTS",
                              amount_cents, LOAN_OFFICER,
                              prepaid_finance_charge_flag=True)


def test_the_catalog_surface_is_publish_then_read(api):
    """An overlay is written once and read back unchanged by two different roles.

    PRD 3.1: "an optional `applies_to_program_code` drawn from the same five program
    families — when it is null the overlay applies to every program" and "`waivable_flag`,
    which defaults to true and when false means no exception may ever be opened against
    this overlay" and "`severity` is `MINOR` or `MATERIAL`".

    PRD 3.1: "`threshold_value` carries the threshold in the metric's own unit — percent
    for loan-to-value and debt-to-income, a bare ratio for debt-service coverage, cents
    for the loan amount, months for seasoning and reserves, and points for the credit
    score."

    Design: Corner/endpoints/corner_standard_crud_surface_is_create_and_read_only
    """
    overlay_a = fx.create_overlay(api, INVESTOR, "OV-FICO-680", "MIN_FICO", "GTE",
                                 680.00, required_authority_tier=1,
                                 severity="MINOR")
    overlay_b = fx.create_overlay(api, INVESTOR, "OV-LTV-70", "MAX_LTV_PCT", "LTE",
                                 70.00, applies_to_program_code="DSCR",
                                 waivable_flag=False, required_authority_tier=2,
                                 severity="MATERIAL")

    read_a = validate_success(api.get_overlay(overlay_a["id"], UNDERWRITER))
    read_b = validate_success(api.get_overlay(overlay_b["id"], SECURITIZATION_ANALYST))

    assert read_a["id"] == overlay_a["id"]
    A.assert_fields(read_a, {"investor_code": INVESTOR,
                             "overlay_code": "OV-FICO-680",
                             "rule_metric": "MIN_FICO", "comparator": "GTE",
                             "required_authority_tier": 1, "severity": "MINOR",
                             "waivable_flag": True})
    A.assert_is_null(read_a, "applies_to_program_code")
    assert A.as_decimal(read_a["threshold_value"]) == A.as_decimal("680.00"), (
        f"threshold_value was {read_a['threshold_value']!r}")

    assert read_b["id"] == overlay_b["id"]
    A.assert_fields(read_b, {"applies_to_program_code": "DSCR",
                             "waivable_flag": False,
                             "required_authority_tier": 2,
                             "severity": "MATERIAL",
                             "rule_metric": "MAX_LTV_PCT", "comparator": "LTE"})
    assert A.as_decimal(read_b["threshold_value"]) == A.as_decimal("70.00"), (
        f"threshold_value was {read_b['threshold_value']!r}")

    # The read is role-shared: the same identifier reads identically for either role.
    assert read_a == validate_success(api.get_overlay(overlay_a["id"],
                                                      SECURITIZATION_ANALYST))
    assert read_b == validate_success(api.get_overlay(overlay_b["id"], UNDERWRITER))


def _escalated_review(api):
    """A review escalated by a 14.29 percent variance between 80000000 and 70000000."""
    program = _dscr_program(api, name="Investor DSCR Dual Value",
                            second_valuation_loan_amount_threshold_cents=50000000)
    borrower = _borrower(api, "Oona Override")
    loan_file = _dscr_investment_file(api, borrower["id"], program["id"])
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    _origination_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.order_receive_accept(api, loan_file["id"], "SECOND_APPRAISAL",
                            "2026-05-15T00:00:00Z", 70000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    return loan_file, fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER), uw


def test_the_escalation_override_consumes_its_own_precondition(api):
    """The override clears the escalation once and refuses the identical repeat.

    PRD 3.5: "An `AppraisalReviewer` supplies an `override_justification` and the primary
    dimension moves `PRIMARY_ESCALATED → PRIMARY_CLEARED`." and "including a second
    override attempt on an already-cleared review, which is never a no-op — it is refused
    with `ERR_REVIEW_STATE_INVALID`." and "the override does **not** restore the primary
    appraisal's number: `reconciled_value_cents` stays at the conservative lower value,
    the override merely accepts that value as the basis for underwriting." and
    "`escalation_reason` is rewritten to `OVERRIDDEN_BY_REVIEWER`, and because
    `reconciled_value_cents` is unchanged, no loan-to-value recomputation and no
    downstream cascade follow."

    PRD 3.5: "computes `variance_pct` as the difference between them, multiplied by one
    hundred and divided by **the lower** of the two, rounded half up to two decimals."

    Design: Corner/endpoints/corner_override_escalation_action_is_single_use
    """
    loan_file, review, uw = _escalated_review(api)
    A.assert_money(review["primary_value_cents"], 80000000, "primary_value_cents")
    A.assert_money(review["second_value_cents"], 70000000, "second_value_cents")
    A.assert_money(review["reconciled_value_cents"], 70000000,
                   "reconciled_value_cents")
    A.assert_pct_2dp(review["variance_pct"], "14.29", "variance_pct")
    A.assert_fields(review, {"primary_review_status": "PRIMARY_ESCALATED",
                             "second_valuation_status": "SECOND_RECONCILED",
                             "escalation_reason": "VARIANCE_ABOVE_TOLERANCE"})

    cleared = fx.override_escalation(
        api, review["id"], APPRAISAL_REVIEWER,
        "Comparable set reviewed; conservative value accepted.")

    A.assert_fields(cleared, {"primary_review_status": "PRIMARY_CLEARED",
                              "escalation_reason": "OVERRIDDEN_BY_REVIEWER",
                              "second_valuation_status": "SECOND_RECONCILED"})
    A.assert_money(cleared["reconciled_value_cents"], 70000000,
                   "reconciled_value_cents")
    A.assert_pct_2dp(fx.get_loan_file(api, loan_file["id"], uw)["ltv_pct"],
                     "85.71", "ltv_pct")

    refused = api.override_escalation(
        review["id"], F.override_escalation_payload("Second attempt at the same override."),
        APPRAISAL_REVIEWER)

    validate_error(refused, ERR_REVIEW_STATE_INVALID)
    again = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    for field in ("primary_review_status", "escalation_reason",
                  "reconciled_value_cents", "second_valuation_status"):
        assert again[field] == cleared[field], (
            f"{field} moved on the refused repeat: {again[field]!r}")


def _closed_dscr_loan(api, program_id, legal_name, uw_id):
    """One 60000000-cent DSCR loan carried to CLOSED and securitization-eligible."""
    borrower = _borrower(api, legal_name)
    loan_file = _dscr_investment_file(api, borrower["id"], program_id)
    uw = underwriter(uw_id)
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    _origination_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    closed = fx.close(api, loan_file["id"])
    A.assert_fields(closed, {"status": "CLOSED", "securitization_eligible": True})
    return loan_file


def test_the_membership_link_resolves_the_path_before_the_body(api):
    """Two bad identifiers report the pool, and one link excludes the second pool.

    PRD 2.8: "References are resolved strictly left to right: path segments first, parent
    before child, and then request-body foreign keys in the order the fields are listed
    for that endpoint."

    PRD 3.9: "The loan must not already sit in any pool: `pool_id` must be null at
    assignment time, or the refusal is `ERR_LOAN_ALREADY_POOLED` at 409." and "On success
    the loan's `pool_id` is set, the three pool metrics are recomputed, the pool's
    `version` increments by one".

    PRD 4: "the filtered loan-file list, which accepts `borrower_id`, `program_id`,
    `pool_id`, `status` and `doc_type` filters and is the reverse-reachability channel for
    all three foreign keys".

    Design: Corner/endpoints/corner_pool_membership_link_requires_both_sides_and_is_exclusive
    """
    program = _dscr_program(api)
    loan_file = _closed_dscr_loan(api, program["id"], "Linus Link", "uw-1")
    pool_one = fx.create_pool(api, "P-LINK-1", INVESTOR, 200000000)
    pool_two = fx.create_pool(api, "P-LINK-2", INVESTOR, 200000000)

    no_pool = api.assign_loan_to_pool(
        MISSING_ID,
        F.pool_assignment_payload(loan_file["id"], pool_one["version"]),
        SECURITIZATION_ANALYST)
    no_loan = api.assign_loan_to_pool(
        pool_one["id"],
        F.pool_assignment_payload(MISSING_ID, pool_one["version"]),
        SECURITIZATION_ANALYST)
    neither = api.assign_loan_to_pool(
        MISSING_ID, F.pool_assignment_payload(MISSING_ID, pool_one["version"]),
        SECURITIZATION_ANALYST)

    validate_error(no_pool, ERR_POOL_NOT_FOUND)
    validate_error(no_loan, ERR_LOAN_FILE_NOT_FOUND)
    # The path segment is resolved first, so the pool error masks the loan error.
    validate_error(neither, ERR_POOL_NOT_FOUND)

    linked = fx.assign_loan(api, pool_one["id"], loan_file["id"],
                            pool_one["version"])

    A.assert_fields(linked, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(linked["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(linked["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(linked, pool_one["version"] + 1)
    A.assert_fields(fx.get_loan_file(api, loan_file["id"]),
                    {"pool_id": pool_one["id"]})

    from_the_loan_side = api.list_loan_files(SECURITIZATION_ANALYST,
                                             params={"pool_id": pool_one["id"]})
    rows = validate_success(from_the_loan_side)
    A.assert_ids_equal(rows, [loan_file["id"]], "loan-file ids")
    A.assert_meta_pagination(from_the_loan_side.json()["meta"], 10, 0, 1, False)

    already = api.assign_loan_to_pool(
        pool_two["id"],
        F.pool_assignment_payload(loan_file["id"], pool_two["version"]),
        SECURITIZATION_ANALYST)

    validate_error(already, ERR_LOAN_ALREADY_POOLED)
    untouched = validate_success(api.get_pool(pool_two["id"], SECURITIZATION_ANALYST))
    A.assert_fields(untouched, {"member_loan_count": 0})
    A.assert_version(untouched, pool_two["version"])
    # None of the three refused calls consumed a version on the first pool.
    A.assert_version(validate_success(api.get_pool(pool_one["id"],
                                                   SECURITIZATION_ANALYST)),
                     pool_one["version"] + 1)


def test_three_read_channels_agree_on_the_published_income(api):
    """The worksheet detail, the file-scoped list and the loan file report one figure.

    PRD 3.4: "`gross_monthly_income_cents` is `p_and_l_net_income_cents` divided by
    `p_and_l_period_months`, rounded half up to the cent, and
    `monthly_qualifying_income_cents` is that figure multiplied by the borrower's
    `entity_ownership_pct` and divided by one hundred, rounded half up to the cent." and
    "`expense_factor_pct_applied` stays null; `variant_applied` is `PL_NET_INCOME`."

    PRD 3.4: "increments `calculation_count` by one on every run" and "the accepted
    worksheet's `monthly_qualifying_income_cents` is copied onto the file's
    `qualifying_income_monthly_cents`; the file's `dti_pct`, `residual_income_cents` and
    `documented_reserves_months` are recomputed".

    PRD 2.3: "List responses populate `limit`, `offset`, `total_count` and `has_more` in
    `meta`, where `total_count` is the number of records matching the filter before
    pagination is applied and `has_more` is true when records remain beyond the current
    page."

    18333336 / 12 = 1527778 at 100.00 percent ownership; against a 730000 payment that
    is a 47.78 debt ratio, 797778 of residual income and 5.48 months of reserves.

    Design: Corner/endpoints/corner_computed_read_channels_agree_on_published_income
    """
    program = fx.create_program(
        api, "PROFIT_AND_LOSS", name="CPA P and L", statement_period_months=12,
        default_expense_factor_pct=50.00, min_expense_factor_pct=25.00,
        max_ltv_pct=80.00, min_fico=660, min_reserves_months=3, max_dti_pct=55.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = _borrower(api, "Rita Read", fico_score=700, self_employed_flag=True,
                         verified_liquid_assets_cents=4000000, age_years=45)
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
    worksheet = fx.create_worksheet(api, loan_file["id"], "PROFIT_AND_LOSS",
                                    submitted["version"], uw,
                                    p_and_l_net_income_cents=18333336,
                                    p_and_l_period_months=12)
    fx.calculate_worksheet(api, worksheet["id"], uw)
    fx.accept_worksheet(api, worksheet["id"], uw)
    committee = credit_committee("cc-1")

    detail = validate_success(api.get_worksheet(worksheet["id"], committee))
    listed = api.list_worksheets(loan_file["id"], committee)
    published = validate_success(api.get_loan_file(loan_file["id"], committee))

    A.assert_money(detail["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
    A.assert_money(detail["gross_monthly_income_cents"], 1527778,
                   "gross_monthly_income_cents")
    A.assert_fields(detail, {"variant_applied": "PL_NET_INCOME",
                             "status": "ACCEPTED", "calculation_count": 1})
    A.assert_is_null(detail, "expense_factor_pct_applied")

    rows = validate_success(listed)
    A.assert_ids_equal(rows, [worksheet["id"]], "worksheet ids")
    A.assert_money(rows[0]["monthly_qualifying_income_cents"], 1527778,
                   "monthly_qualifying_income_cents")
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)

    A.assert_money(published["qualifying_income_monthly_cents"], 1527778,
                   "qualifying_income_monthly_cents")
    A.assert_money(published["pitia_monthly_cents"], 730000, "pitia_monthly_cents")
    A.assert_pct_2dp(published["dti_pct"], "47.78", "dti_pct")
    A.assert_money(published["residual_income_cents"], 797778,
                   "residual_income_cents")
    A.assert_decimal_equals(published["documented_reserves_months"], "5.48", 2,
                            "documented_reserves_months")
    A.assert_pct_2dp(published["ltv_pct"], "75.00", "ltv_pct")
    A.assert_is_null(published, "dscr_ratio")

    # Reads are projections: neither the file version nor the calculation count moved.
    A.assert_fields(validate_success(api.get_worksheet(worksheet["id"], committee)),
                    {"calculation_count": 1})
    A.assert_version(fx.get_loan_file(api, loan_file["id"], uw),
                     published["version"])


def test_settlement_is_conditional_on_an_empty_pool(api):
    """The byte-identical settlement payload fails first and succeeds second.

    PRD 3.9: "A `SETTLEMENT_FINALIZED` removal is additionally refused with
    `ERR_POOL_STATE_INVALID` unless the pool is `OPEN` and `member_loan_count` would
    become 0, since settlement finalises an emptied pool rather than discarding live
    members." and "On success the named loan's `pool_id` is cleared, the three metrics are
    recomputed, and `version` increments by one; a settlement finalisation moves the pool
    `OPEN → SETTLED`, which is terminal, and leaves all three metrics at zero."

    PRD 3.9: "The pool must be `OPEN` or `REBALANCING` — a `SETTLED` pool accepts no
    membership write at all and refuses with `ERR_POOL_STATE_INVALID`" and "When the
    aggregate balance is zero the coupon is 0.0000 rather than undefined."

    Design: Corner/endpoints/corner_settlement_is_conditional_on_an_empty_pool
    """
    program = _dscr_program(api)
    loan_file = _closed_dscr_loan(api, program["id"], "Sofia Settle", "uw-1")
    pool = fx.create_pool(api, "P-SETTLE", INVESTOR, 200000000)
    member = fx.assign_loan(api, pool["id"], loan_file["id"], pool["version"])
    A.assert_fields(member, {"member_loan_count": 1, "status": "OPEN"})
    A.assert_money(member["aggregate_scheduled_balance_cents"], 60000000,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(member["weighted_avg_coupon_pct"], "8.7500",
                       "weighted_avg_coupon_pct")
    A.assert_version(member, pool["version"] + 1)

    too_early = api.remove_from_pool(
        pool["id"],
        F.pool_removal_payload("SETTLEMENT_FINALIZED", member["version"]),
        SECURITIZATION_ANALYST)

    validate_error(too_early, ERR_POOL_STATE_INVALID)
    still_open = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(still_open, {"status": "OPEN", "member_loan_count": 1})
    A.assert_version(still_open, member["version"])

    emptied = fx.remove_loan(api, pool["id"], "ANALYST_DISCRETION",
                             member["version"], loan_file["id"])

    A.assert_fields(emptied, {"member_loan_count": 0, "status": "OPEN"})
    A.assert_money(emptied["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(emptied["weighted_avg_coupon_pct"], "0.0000",
                       "weighted_avg_coupon_pct")
    A.assert_version(emptied, member["version"] + 1)
    detached = fx.get_loan_file(api, loan_file["id"])
    A.assert_is_null(detached, "pool_id")
    A.assert_fields(detached, {"status": "CLOSED"})

    settled = fx.remove_loan(api, pool["id"], "SETTLEMENT_FINALIZED",
                             emptied["version"])

    A.assert_fields(settled, {"status": "SETTLED", "member_loan_count": 0})
    A.assert_money(settled["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(settled["weighted_avg_coupon_pct"], "0.0000",
                       "weighted_avg_coupon_pct")
    A.assert_version(settled, emptied["version"] + 1)

    after_settlement = api.assign_loan_to_pool(
        pool["id"],
        F.pool_assignment_payload(loan_file["id"], settled["version"]),
        SECURITIZATION_ANALYST)

    validate_error(after_settlement, ERR_POOL_STATE_INVALID)
    terminal = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(terminal, {"status": "SETTLED", "member_loan_count": 0})
    A.assert_version(terminal, settled["version"])


def test_child_collections_are_scoped_to_their_own_parent(api):
    """Four child pages, two of them legitimately empty, and four parent 404s.

    PRD 2.8: "Existence of every referenced resource, on every endpoint that has a path
    parameter or a foreign-key input." and "The applicable code is the one naming the
    missing resource".

    PRD 2.3: "`total_count` is the number of records matching the filter before pagination
    is applied and `has_more` is true when records remain beyond the current page."

    An asset-depletion worksheet has no statement months, and a file still in
    `UNDERWRITING` can have no post-close audit, so two of the four pages are empty
    rather than absent.

    Design: Corner/endpoints/corner_child_collection_reads_are_scoped_to_their_parent
    """
    program = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion Child Reads",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000)
    borrower = _borrower(api, "Scoped Sofia", fico_score=720,
                         monthly_debt_obligations_cents=90000,
                         verified_liquid_assets_cents=4000000)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "ASSET_DEPLETION", uw)
    _origination_fee(api, loan_file["id"], 300000)
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    worksheet = fx.create_worksheet(api, loan_file["id"], "ASSET_DEPLETION",
                                    submitted["version"], uw,
                                    asset_bucket_checking_cents=15000000,
                                    asset_bucket_brokerage_cents=22222225,
                                    asset_bucket_retirement_cents=30000001)
    order = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                               "2026-05-01T00:00:00Z", APPRAISAL_REVIEWER,
                               vendor_code="VEND-A")

    worksheets = api.list_worksheets(loan_file["id"], UNDERWRITER)
    months = api.list_statement_months(worksheet["id"], UNDERWRITER)
    orders = api.list_valuation_orders(loan_file["id"], APPRAISAL_REVIEWER)
    audits = api.list_audits(loan_file["id"], POST_CLOSE_AUDITOR)

    worksheet_rows = validate_success(worksheets)
    A.assert_ids_equal(worksheet_rows, [worksheet["id"]], "worksheet ids")
    A.assert_fields(worksheet_rows[0], {"status": "DRAFT"})
    A.assert_meta_pagination(worksheets.json()["meta"], 10, 0, 1, False)

    assert validate_success(months) == []
    A.assert_meta_pagination(months.json()["meta"], 10, 0, 0, False)

    order_rows = validate_success(orders)
    A.assert_ids_equal(order_rows, [order["id"]], "valuation order ids")
    A.assert_fields(order_rows[0], {"valuation_type": "PRIMARY_APPRAISAL",
                                    "status": "ORDERED"})
    A.assert_meta_pagination(orders.json()["meta"], 10, 0, 1, False)

    assert validate_success(audits) == []
    A.assert_meta_pagination(audits.json()["meta"], 10, 0, 0, False)

    # A never-issued parent id is a 404 naming the parent, not an empty page.
    validate_error(api.list_worksheets(MISSING_ID, UNDERWRITER),
                   ERR_LOAN_FILE_NOT_FOUND)
    validate_error(api.list_valuation_orders(MISSING_ID, APPRAISAL_REVIEWER),
                   ERR_LOAN_FILE_NOT_FOUND)
    validate_error(api.list_audits(MISSING_ID, POST_CLOSE_AUDITOR),
                   ERR_LOAN_FILE_NOT_FOUND)
    # The statement-month route's parent is the worksheet, not the loan file.
    validate_error(api.list_statement_months(MISSING_ID, UNDERWRITER),
                   ERR_WORKSHEET_NOT_FOUND)
