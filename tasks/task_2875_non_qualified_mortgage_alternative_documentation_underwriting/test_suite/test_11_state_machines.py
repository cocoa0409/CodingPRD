"""Declared initial states, guarded transitions, terminal lockdown and the two
aggregate machines that never take a status input.

Every scenario in this module is built from the same DSCR configuration the
corner index uses, so the reachable states differ only in how far the file was
driven before the trigger under test.
"""

from test_helpers import assertions as A
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_DOC_TYPE_PROGRAM_MISMATCH,
    ERR_LOAN_FILE_STATE_INVALID,
    ERR_VALUATION_ORDER_STATE_INVALID,
)
from test_helpers.test_users import (
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    credit_committee,
)

INVESTOR = "INV-ALPHA"


def _dscr_program(api, **overrides):
    """The corner index's canonical coverage-ratio program."""
    return fx.create_program(
        api, "DSCR", name="Investor DSCR", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True, **overrides)


def _novak(api, **overrides):
    return fx.create_borrower(
        api, legal_name="Ida Novak", fico_score=700, self_employed_flag=False,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=5000000, age_years=50, **overrides)


def _dscr_file(api, borrower_id, program_id, **overrides):
    """A 60000000-cent interest-only investment purchase with an in-place lease."""
    return fx.create_loan_file(
        api, borrower_id, program_id, INVESTOR, loan_amount_cents=60000000,
        purchase_price_cents=80000000, property_value_cents=80000000,
        occupancy="INVESTMENT", purpose="PURCHASE", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="INTEREST_ONLY", monthly_taxes_cents=60000,
        monthly_insurance_cents=20000, gross_market_rent_cents=620000,
        lease_rent_cents=640000, **overrides)


def _origination_fee(api, loan_file_id):
    """The single ACTIVE charge PRD 3.3 requires before a submission."""
    return fx.create_fee_item(api, loan_file_id, "F-ORIG", "ORIGINATION_POINTS",
                              600000, LOAN_OFFICER,
                              prepaid_finance_charge_flag=True)


def _file_in_underwriting(api, uw=UNDERWRITER):
    """Program, borrower and a DSCR file driven DRAFT -> ... -> UNDERWRITING."""
    program = _dscr_program(api)
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    _origination_fee(api, loan_file["id"])
    fx.submit_to_underwriting(api, loan_file["id"])
    return program, borrower, loan_file


def _closed_file(api, uw=UNDERWRITER):
    """The same DSCR file driven all the way to CLOSED.

    The 600000-cent origination charge is a financed prepaid finance charge, so
    the step-three figure is 59400000 and the 5.00 percent cap of 2970000 is far
    above the 600000-cent included total: the verdict is `PASS`. The program funds
    business-purpose investment loans, so the determination short-circuits to
    `EXEMPT`, and the primary appraisal effective 2026-05-01 is still inside its
    120-day window on the default 2026-08-01 clock.
    """
    program, borrower, loan_file = _file_in_underwriting(api, uw)
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000, APPRAISAL_REVIEWER,
                            APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    fx.run_atr_determination(api, loan_file["id"], uw)
    fx.approve(api, loan_file["id"], uw)
    closed = fx.close(api, loan_file["id"])
    A.assert_fields(closed, {"status": "CLOSED", "securitization_eligible": True})
    return program, borrower, loan_file


def _audit(api, audit_id):
    return validate_success(api.get_audit(audit_id, POST_CLOSE_AUDITOR))


def test_new_rows_start_in_their_declared_initial_state(api):
    """A file, a pool and a fee item each open in the state the PRD declares.

    PRD 3.3: "A file opens with `status` `DRAFT`, `doc_type` null, `pool_id` null and
    `assigned_underwriter_id` null."
    PRD 3.3: "it stays null on any file whose `doc_type` is not `DSCR`".
    PRD 3.9: "A new pool starts `OPEN` with `aggregate_scheduled_balance_cents` of 0,
    `weighted_avg_coupon_pct` of 0.0000 and `member_loan_count` of 0."
    PRD 3.6: "A charge is created `ACTIVE` with `void_reason` null."

    Design: Corner/state_machines/corner_new_rows_start_in_declared_initial_state
    """
    program = _dscr_program(api)
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])
    fee = _origination_fee(api, loan_file["id"])

    pool = fx.create_pool(api, "POOL-2026-A", INVESTOR, 100000000)

    A.assert_created_row(pool)
    stored_pool = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(stored_pool, {"status": "OPEN", "member_loan_count": 0,
                                  "version": 1})
    A.assert_money(stored_pool["aggregate_scheduled_balance_cents"], 0,
                   "aggregate_scheduled_balance_cents")
    A.assert_ratio_4dp(stored_pool["weighted_avg_coupon_pct"], "0.0000",
                       "weighted_avg_coupon_pct")

    stored_file = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(stored_file, {"status": "DRAFT", "version": 1})
    A.assert_is_null(stored_file, "doc_type", "assigned_underwriter_id", "pool_id",
                     "dscr_ratio")

    A.assert_fields(fee, {"status": "ACTIVE"})
    A.assert_is_null(fee, "void_reason")


def test_doc_type_selection_binds_the_underwriter_and_publishes_the_ratio(api):
    """One selection call moves the state, binds uw-1 and mints the coverage ratio.

    PRD 3.3: "the file advances `DRAFT → DOC_TYPE_SELECTED`" and "On success the file
    records `doc_type` — immutable from that moment on — stores the acting `X-User-ID`
    in `assigned_underwriter_id`, and recomputes `pitia_monthly_cents` and
    `documented_reserves_months`."
    PRD 3.3: "the qualifying rent is the lesser of the contract rent and 120 percent of
    `gross_market_rent_cents` rounded half up to the cent, and `dscr_ratio` records the
    `LEASE_IN_PLACE` shape" and "deliberately leaves `qualifying_income_monthly_cents`
    at 0".

    The lease of 640000 is below 120 percent of the 620000-cent market rent, which is
    744000, so the qualifying rent is the lease itself and the ratio is 640000 divided
    by the 517500-cent interest-only payment.

    Design: Corner/state_machines/corner_doc_type_selection_binds_underwriter_and_publishes_dscr
    """
    program = _dscr_program(api)
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])

    selected = fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)

    A.assert_fields(selected, {"status": "DOC_TYPE_SELECTED", "doc_type": "DSCR",
                               "assigned_underwriter_id": "uw-1", "version": 2})
    A.assert_money(selected["pitia_monthly_cents"], 517500, "pitia_monthly_cents")
    A.assert_ratio_4dp(selected["dscr_ratio"], "1.2367", "dscr_ratio")
    A.assert_money(selected["qualifying_income_monthly_cents"], 0,
                   "qualifying_income_monthly_cents")
    A.assert_decimal_equals(selected["documented_reserves_months"], "9.66", 2,
                            "documented_reserves_months")
    A.assert_pct_2dp(selected["ltv_pct"], "75.00", "ltv_pct")
    A.assert_is_null(selected, "dti_pct")


def test_doc_type_selection_data_preconditions_are_rejected(api):
    """An owner-occupied file cannot take DSCR, and a DSCR program offers nothing else.

    PRD 3.3: "choosing `DSCR` additionally requires `occupancy` to be `INVESTMENT` and
    `gross_market_rent_cents` to be present" and "`ASSET_DEPLETION` requires
    `ASSET_DEPLETION`" and "Any violation of any of these is refused with
    `ERR_DOC_TYPE_PROGRAM_MISMATCH`."

    Design: Corner/state_machines/corner_doc_type_selection_data_preconditions_rejected
    """
    program = _dscr_program(api)
    borrower = fx.create_borrower(
        api, legal_name="Owner Occupant", fico_score=700, self_employed_flag=False,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=0,
        verified_liquid_assets_cents=5000000, age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR, loan_amount_cents=60000000,
        purchase_price_cents=80000000, property_value_cents=80000000,
        occupancy="PRIMARY", purpose="PURCHASE", lien_position="FIRST",
        note_rate_pct=8.750, apor_pct=6.100, term_months=360,
        amortization_type="INTEREST_ONLY", monthly_taxes_cents=60000,
        monthly_insurance_cents=20000)

    wrong_occupancy = api.select_doc_type(loan_file["id"], {"doc_type": "DSCR"},
                                         UNDERWRITER)
    validate_error(wrong_occupancy, ERR_DOC_TYPE_PROGRAM_MISMATCH)

    wrong_family = api.select_doc_type(loan_file["id"],
                                      {"doc_type": "ASSET_DEPLETION"}, UNDERWRITER)
    validate_error(wrong_family, ERR_DOC_TYPE_PROGRAM_MISMATCH)

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(after, {"status": "DRAFT", "version": 1})
    A.assert_is_null(after, "doc_type", "assigned_underwriter_id", "dscr_ratio")


def test_draft_loan_file_rejects_every_later_trigger(api):
    """Five later triggers all bounce off DRAFT with the state code, not with 404s.

    The acting underwriter is not the file's `assigned_underwriter_id` — nothing is
    assigned yet — and the state band still answers first, because it stands above the
    authority band on the ladder.

    PRD 2.8: "on every POST beneath `/loan-files/{id}/`".
    PRD 3.3: "It is accepted only from `DOC_TYPE_SELECTED`".
    PRD 3.8: "The file must be in `UNDERWRITING`, and the checks then apply in the
    ladder's order." and "It is accepted only from `APPROVED` and only while
    `securitization_eligible` is true."

    Design: Corner/state_machines/corner_draft_loan_file_rejects_every_later_trigger
    """
    program = _dscr_program(api)
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])
    _origination_fee(api, loan_file["id"])

    validate_error(api.submit_to_underwriting(loan_file["id"], LOAN_OFFICER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.suspend_loan_file(loan_file["id"],
                                        {"suspension_reason": "TOO_EARLY"},
                                        UNDERWRITER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.clear_conditions(loan_file["id"],
                                       {"resolution_note": "TOO_EARLY"}, UNDERWRITER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.approve_loan_file(loan_file["id"], UNDERWRITER,
                                        {"approval_note": "TOO_EARLY"}),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.close_loan_file(loan_file["id"], LOAN_OFFICER),
                   ERR_LOAN_FILE_STATE_INVALID)

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(after, {"status": "DRAFT", "version": 1})
    A.assert_is_null(after, "doc_type", "assigned_underwriter_id")


def test_denied_loan_file_is_locked_against_every_trigger(api):
    """DENIED is the one truly terminal status, and even a fee correction is refused.

    PRD 3.8: "a denied file accepts no trigger of any kind, and every attempt is refused
    with `ERR_LOAN_FILE_STATE_INVALID`" and "`securitization_eligible` is set to false".
    PRD 3.6: "Fee items may be added in every loan-file status except `DENIED`".

    Design: Corner/state_machines/corner_denied_loan_file_is_locked_against_every_trigger
    """
    program, borrower, loan_file = _file_in_underwriting(api)
    denied = validate_success(api.deny_loan_file(
        loan_file["id"], {"denial_reason": "INSUFFICIENT_RENT_COVERAGE"}, UNDERWRITER))
    A.assert_fields(denied, {"status": "DENIED", "securitization_eligible": False})

    validate_error(api.suspend_loan_file(loan_file["id"],
                                        {"suspension_reason": "REOPEN_ATTEMPT"},
                                        UNDERWRITER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.approve_loan_file(loan_file["id"], UNDERWRITER,
                                        {"approval_note": "REOPEN_ATTEMPT"}),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.close_loan_file(loan_file["id"], LOAN_OFFICER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.run_points_and_fees_test(loan_file["id"], UNDERWRITER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.create_fee_item({"loan_file_id": loan_file["id"],
                                       "fee_code": "F-LATE",
                                       "fee_category": "AFFILIATE_TITLE",
                                       "amount_cents": 100000}, LOAN_OFFICER),
                   ERR_LOAN_FILE_STATE_INVALID)

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(after, {"status": "DENIED", "securitization_eligible": False})

    listed = api.list_fee_items(loan_file["id"], LOAN_OFFICER)
    rows = validate_success(listed)
    assert [row["fee_code"] for row in rows] == ["F-ORIG"], rows
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)


def test_repeated_triggers_are_rejected_rather_than_absorbed(api):
    """A second selection and a second receipt are refused, each with its own code.

    PRD 3.3: "The selection is only accepted while `status` is `DRAFT` and `doc_type` is
    still null; attempting it from any other state is refused with
    `ERR_LOAN_FILE_STATE_INVALID`."
    PRD 3.5: "A second receipt against the same order, or a receipt against an order
    that is not `ORDERED`, is refused with `ERR_VALUATION_ORDER_STATE_INVALID`".

    Design: Corner/state_machines/corner_repeated_triggers_rejected_rather_than_no_op
    """
    program, borrower, loan_file = _file_in_underwriting(api)
    order = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                               "2026-05-01T00:00:00Z", APPRAISAL_REVIEWER,
                               vendor_code="VEND-1")
    fx.receive_valuation(api, order["id"], 80000000, APPRAISAL_REVIEWER)

    validate_error(api.select_doc_type(loan_file["id"], {"doc_type": "DSCR"},
                                      UNDERWRITER),
                   ERR_LOAN_FILE_STATE_INVALID)
    validate_error(api.receive_valuation(order["id"],
                                        {"appraised_value_cents": 91000000},
                                        APPRAISAL_REVIEWER),
                   ERR_VALUATION_ORDER_STATE_INVALID)

    stored_order = validate_success(api.get_valuation_order(order["id"],
                                                           APPRAISAL_REVIEWER))
    A.assert_fields(stored_order, {"status": "RECEIVED"})
    A.assert_money(stored_order["appraised_value_cents"], 80000000,
                   "appraised_value_cents")

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(after, {"status": "UNDERWRITING", "doc_type": "DSCR",
                            "assigned_underwriter_id": "uw-1"})


def test_submit_to_underwriting_fires_all_four_side_effects(api):
    """One call recomputes seasoning, re-tests the second valuation, mints the
    review row and re-runs the overlay sweep.

    PRD 3.3: "Submission then does four things: it recomputes the credit-event seasoning
    fields against the current logical clock, re-tests whether a second valuation is
    required and moves the appraisal review's second dimension to `SECOND_REQUIRED` when
    it is, creates the file's appraisal review row if none exists yet with
    `primary_review_status` at `PRIMARY_NOT_ORDERED`, and re-runs the investor-overlay
    sweep to rebuild `overlay_breach_codes` and `unresolved_overlay_breach_count`."
    PRD 3.2: "When the candidate set is empty, `governing_credit_event_id` is null,
    `seasoning_months_required` and `seasoning_months_elapsed` are both zero, and
    `seasoning_satisfied` is true."
    PRD 3.5: "`second_valuation_status` tracks the second-valuation requirement through
    `SECOND_NOT_REQUIRED`, `SECOND_REQUIRED`, `SECOND_ORDERED`, `SECOND_RECEIVED` and
    `SECOND_RECONCILED`, starting at `SECOND_NOT_REQUIRED`."

    The 75.00 loan-to-value is below the program's 90.00 trigger, the 60000000-cent note
    is below the 150000000-cent trigger, and the purpose is a purchase, so no second
    valuation is required and the second dimension is left where it started.

    Design: Corner/state_machines/corner_submit_to_underwriting_fires_all_four_side_effects
    """
    program = _dscr_program(api)
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)
    _origination_fee(api, loan_file["id"])

    submitted = fx.submit_to_underwriting(api, loan_file["id"])

    A.assert_fields(submitted, {"status": "UNDERWRITING",
                                "seasoning_months_required": 0,
                                "seasoning_months_elapsed": 0,
                                "seasoning_satisfied": True,
                                "unresolved_overlay_breach_count": 0,
                                "second_valuation_required": False})
    A.assert_is_null(submitted, "governing_credit_event_id")
    A.assert_codes_in_order(submitted["overlay_breach_codes"], [],
                            "overlay_breach_codes")

    listed = api.list_appraisal_reviews(loan_file["id"], APPRAISAL_REVIEWER)
    rows = validate_success(listed)
    assert len(rows) == 1, rows
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)
    review = rows[0]
    A.assert_fields(review, {"primary_review_status": "PRIMARY_NOT_ORDERED",
                             "second_valuation_status": "SECOND_NOT_REQUIRED"})
    A.assert_is_null(review, "primary_value_cents", "second_value_cents",
                     "variance_pct", "reconciled_value_cents")


def test_accepting_the_worksheet_publishes_income_onto_the_loan_file(api):
    """Acceptance is the only act that moves a number from a worksheet to a file.

    PRD 3.4: "the accepted worksheet's `monthly_qualifying_income_cents` is copied onto
    the file's `qualifying_income_monthly_cents`; the file's `dti_pct`,
    `residual_income_cents` and `documented_reserves_months` are recomputed; the file's
    `atr_documentation_status` is reset to `INCOMPLETE` and its `safe_harbor_class` to
    `NOT_EVALUATED`".
    PRD 3.4: "The retirement access factor is a full 100 percent for a borrower whose
    `age_years` is at least 60, and 70 percent otherwise." and
    "`eligible_assets_after_haircut_cents` is the sum of those three already-rounded
    components" and "Required reserves are the program's `min_reserves_months` multiplied
    by the file's current `pitia_monthly_cents`, and `depletable_assets_cents` is the
    eligible assets less those required reserves, floored at zero."

    The 45-year-old borrower takes the 70 percent retirement factor: 15000000 plus
    20000003 plus 21000001 is 56000004, less six months of the 274764-cent payment
    leaves 54351420, and dividing by the 84-month horizon gives 647041.

    Design: Corner/state_machines/corner_worksheet_accept_publishes_income_to_loan_file
    """
    program = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion 84",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=60.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Peter Ashworth", fico_score=700, self_employed_flag=False,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=2000000, age_years=45)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR, loan_amount_cents=30000000,
        purchase_price_cents=40000000, property_value_cents=40000000,
        occupancy="PRIMARY", purpose="PURCHASE", lien_position="FIRST",
        note_rate_pct=7.500, apor_pct=6.100, term_months=360,
        amortization_type="FULLY_AMORTIZING", monthly_taxes_cents=50000,
        monthly_insurance_cents=15000)
    fx.select_doc_type(api, loan_file["id"], "ASSET_DEPLETION", UNDERWRITER)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS", 200000,
                       LOAN_OFFICER, prepaid_finance_charge_flag=True)
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    A.assert_money(submitted["pitia_monthly_cents"], 274764, "pitia_monthly_cents")

    worksheet = fx.create_worksheet(api, loan_file["id"], "ASSET_DEPLETION",
                                    submitted["version"], UNDERWRITER,
                                    asset_bucket_checking_cents=15000000,
                                    asset_bucket_brokerage_cents=22222226,
                                    asset_bucket_retirement_cents=30000002)
    fx.calculate_worksheet(api, worksheet["id"], UNDERWRITER)

    accepted = fx.accept_worksheet(api, worksheet["id"], UNDERWRITER)

    A.assert_fields(accepted, {"status": "ACCEPTED",
                               "variant_applied": "ASSET_DEPLETION_STANDARD"})
    A.assert_money(accepted["eligible_assets_after_haircut_cents"], 56000004,
                   "eligible_assets_after_haircut_cents")
    A.assert_money(accepted["depletable_assets_cents"], 54351420,
                   "depletable_assets_cents")
    A.assert_money(accepted["gross_monthly_income_cents"], 647041,
                   "gross_monthly_income_cents")
    A.assert_money(accepted["monthly_qualifying_income_cents"], 647041,
                   "monthly_qualifying_income_cents")

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_money(after["qualifying_income_monthly_cents"], 647041,
                   "qualifying_income_monthly_cents")
    A.assert_money(after["pitia_monthly_cents"], 274764, "pitia_monthly_cents")
    A.assert_pct_2dp(after["dti_pct"], "56.37", "dti_pct")
    A.assert_money(after["residual_income_cents"], 282277, "residual_income_cents")
    A.assert_decimal_equals(after["documented_reserves_months"], "7.28", 2,
                            "documented_reserves_months")
    A.assert_fields(after, {"atr_documentation_status": "INCOMPLETE",
                            "safe_harbor_class": "NOT_EVALUATED",
                            "status": "UNDERWRITING"})


def test_audit_status_and_grade_are_derived_from_child_findings(api):
    """The audit takes no status input: one finding grades it, a waive clears it.

    PRD 3.9: "the audit begins `OPEN`, `NOT_GRADED`, with `defect_score` of 0" and "The
    first finding on an audit moves it `OPEN → FINDINGS_ISSUED`."
    PRD 3.9: "Each finding weighs 1 if its `severity` is `MINOR`, 3 if `SIGNIFICANT` and
    6 if `MATERIAL`." and "`grade` is `A_CLEAN` when `defect_score` is 0, `B_MINOR` when
    it lies between 1 and 5 inclusive".
    PRD 3.9: "`WAIVE` removes its weight from the score entirely." and "Once
    `open_finding_count` reaches zero — every finding terminal — an audit in
    `FINDINGS_ISSUED` moves to `CLEARED` if its grade is `A_CLEAN` or `B_MINOR`".

    Design: Corner/state_machines/corner_audit_status_and_grade_derived_from_child_findings
    """
    program, borrower, loan_file = _closed_file(api)
    audit = fx.create_audit(api, loan_file["id"], "RANDOM")
    A.assert_fields(audit, {"status": "OPEN", "grade": "NOT_GRADED",
                            "defect_score": 0, "open_finding_count": 0})

    finding = fx.create_finding(api, audit["id"], "AF-DOC-01", "ATR_DOCUMENTATION",
                               "MINOR")
    A.assert_fields(finding, {"status": "ISSUED"})

    graded = _audit(api, audit["id"])
    A.assert_fields(graded, {"status": "FINDINGS_ISSUED", "defect_score": 1,
                             "grade": "B_MINOR", "open_finding_count": 1})

    waived = fx.adjudicate_finding(api, finding["id"], "WAIVE", POST_CLOSE_AUDITOR,
                                  "Documentation located in imaging")
    A.assert_fields(waived, {"status": "WAIVED"})

    cleared = _audit(api, audit["id"])
    A.assert_fields(cleared, {"defect_score": 0, "grade": "A_CLEAN",
                              "open_finding_count": 0, "status": "CLEARED"})

    after = fx.get_loan_file(api, loan_file["id"], UNDERWRITER)
    A.assert_fields(after, {"status": "CLOSED", "repurchase_flag": False,
                            "securitization_eligible": True})


def test_return_for_more_info_cycles_the_finding_and_counts_the_rounds(api):
    """The finding loops ISSUED to REBUTTED to ISSUED while the score never moves.

    PRD 3.9: "the finding moves `ISSUED → REBUTTED` and `rebuttal_round` increments by
    one" and "a rebuttal does not reduce the audit's score and does not reduce
    `open_finding_count`, because `REBUTTED` still counts as open and carries full
    severity weight".
    PRD 3.9: "`RETURN_FOR_MORE_INFO` stores the note and cycles the finding
    `REBUTTED → ISSUED`, leaving `defect_score` unchanged; a finding may loop
    `ISSUED → REBUTTED → ISSUED` without bound, and `rebuttal_round` records how many
    loops occurred."

    Design: Corner/state_machines/corner_finding_return_for_more_info_cycles_and_counts_rounds
    """
    program, borrower, loan_file = _closed_file(api)
    audit = fx.create_audit(api, loan_file["id"], "INVESTOR_REQUEST")
    finding = fx.create_finding(api, audit["id"], "AF-INC-07", "INCOME_CALCULATION",
                               "SIGNIFICANT")
    rebutted = fx.rebut_finding(api, finding["id"], UNDERWRITER,
                               "Rent roll supports the qualifying rent")
    A.assert_fields(rebutted, {"status": "REBUTTED", "rebuttal_round": 1})

    returned = fx.adjudicate_finding(api, finding["id"], "RETURN_FOR_MORE_INFO",
                                    POST_CLOSE_AUDITOR, "Send the executed lease")

    A.assert_fields(returned, {"status": "ISSUED", "rebuttal_round": 1})
    mid = _audit(api, audit["id"])
    A.assert_fields(mid, {"defect_score": 3, "grade": "B_MINOR",
                          "open_finding_count": 1, "status": "FINDINGS_ISSUED"})

    again = fx.rebut_finding(api, finding["id"], UNDERWRITER,
                            "Executed lease attached")
    A.assert_fields(again, {"status": "REBUTTED", "rebuttal_round": 2})

    listed = api.list_findings(audit["id"], POST_CLOSE_AUDITOR)
    rows = validate_success(listed)
    assert len(rows) == 1, rows
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 1, False)
    end = _audit(api, audit["id"])
    A.assert_fields(end, {"defect_score": 3, "grade": "B_MINOR",
                          "open_finding_count": 1, "status": "FINDINGS_ISSUED"})
    A.assert_fields(fx.get_loan_file(api, loan_file["id"], UNDERWRITER),
                    {"status": "CLOSED"})


def test_denial_voids_only_the_non_terminal_exception_request(api):
    """The already-approved waiver survives the denial; the pending one is voided.

    PRD 3.8: "every exception request on the file in `PENDING_REVIEW` or
    `AWAITING_SECOND_SIGNATURE` is cascaded to `VOIDED`, and the file moves to `DENIED`".
    PRD 3.7: "when a loan file reaches `DENIED`, every request on it still in
    `PENDING_REVIEW` or `AWAITING_SECOND_SIGNATURE` moves to `VOIDED` with
    `decision_reason` set to `LOAN_DENIED`".
    PRD 3.7: "pins `pinned_metric_value` to the value the overlay's metric holds on the
    file at that instant" and "It records `first_signoff_user_id` as the acting
    `X-User-ID`, recomputes the file's `unresolved_overlay_breach_count` so that the
    waived overlay stops counting".

    Design: Corner/state_machines/corner_deny_voids_only_non_terminal_exception_requests
    """
    program = _dscr_program(api)
    overlay_a = fx.create_overlay(api, INVESTOR, "OV-A-FICO", "MIN_FICO", "GTE", 740,
                                 waivable_flag=True, required_authority_tier=1,
                                 severity="MINOR")
    overlay_b = fx.create_overlay(api, INVESTOR, "OV-B-LTV", "MAX_LTV_PCT", "LTE",
                                 70.00, waivable_flag=True,
                                 required_authority_tier=1, severity="MINOR")
    borrower = _novak(api)
    loan_file = _dscr_file(api, borrower["id"], program["id"])
    fx.select_doc_type(api, loan_file["id"], "DSCR", UNDERWRITER)
    _origination_fee(api, loan_file["id"])
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    A.assert_codes_in_order(submitted["overlay_breach_codes"],
                            ["OV-A-FICO", "OV-B-LTV"], "overlay_breach_codes")
    A.assert_fields(submitted, {"unresolved_overlay_breach_count": 2})

    request_a = fx.create_exception_request(
        api, loan_file["id"], overlay_a["id"], UNDERWRITER,
        justification="Reserves of 9.66 months compensate for the 700 score",
        compensating_factors=["RESERVES", "LOW_PAYMENT_SHOCK"])
    fx.approve_exception(api, request_a["id"], credit_committee("cc-1"),
                         "Committee accepts the reserve offset")
    request_b = fx.create_exception_request(
        api, loan_file["id"], overlay_b["id"], UNDERWRITER,
        justification="LTV 75.00 against a 70.00 overlay ceiling")
    A.assert_fields(request_b, {"status": "PENDING_REVIEW"})

    denied = validate_success(api.deny_loan_file(
        loan_file["id"], {"denial_reason": "LTV_OVERLAY_NOT_WAIVED"}, UNDERWRITER))
    A.assert_fields(denied, {"status": "DENIED", "securitization_eligible": False})

    survivor = validate_success(api.get_exception_request(request_a["id"],
                                                         UNDERWRITER))
    A.assert_fields(survivor, {"status": "APPROVED",
                               "first_signoff_user_id": "cc-1",
                               "required_authority_tier": 1})
    A.assert_is_null(survivor, "second_signoff_user_id")
    assert A.as_decimal(survivor["pinned_metric_value"]) == A.as_decimal(700), (
        f"pinned_metric_value: expected 700, got {survivor['pinned_metric_value']!r}"
    )

    voided = validate_success(api.get_exception_request(request_b["id"], UNDERWRITER))
    A.assert_fields(voided, {"status": "VOIDED", "decision_reason": "LOAN_DENIED"})
    A.assert_pct_2dp(voided["pinned_metric_value"], "75.00", "pinned_metric_value")
