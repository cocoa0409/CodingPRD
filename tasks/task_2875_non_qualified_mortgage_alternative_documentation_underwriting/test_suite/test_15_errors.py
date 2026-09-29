"""Error-code reachability: the three 401 bands, the shape-domain-uniqueness split,
all thirteen 404 codes, the per-entity 409 codes and the ordered guideline ceilings.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_APPRAISAL_ESCALATION_UNRESOLVED,
    ERR_ATR_DOCUMENTATION_INCOMPLETE,
    ERR_AUDIT_NOT_FOUND,
    ERR_BORROWER_NOT_FOUND,
    ERR_DOC_TYPE_PROGRAM_MISMATCH,
    ERR_DSCR_BELOW_PROGRAM_MIN,
    ERR_DTI_ABOVE_PROGRAM_MAX,
    ERR_DUPLICATE_CODE,
    ERR_EXCEPTION_NOT_FOUND,
    ERR_FEE_ITEM_NOT_FOUND,
    ERR_FICO_BELOW_PROGRAM_MIN,
    ERR_FINDING_NOT_FOUND,
    ERR_FINDING_STATE_INVALID,
    ERR_INVALID_REQUEST,
    ERR_LOAN_FILE_NOT_FOUND,
    ERR_LOAN_NOT_IN_POOL,
    ERR_LTV_ABOVE_PROGRAM_MAX,
    ERR_MISSING_ROLE_HEADER,
    ERR_MISSING_USER_HEADER,
    ERR_NO_INCLUDED_STATEMENT_MONTHS,
    ERR_OVERLAY_NOT_FOUND,
    ERR_POOL_NOT_FOUND,
    ERR_PROGRAM_NOT_FOUND,
    ERR_RESERVES_INSUFFICIENT,
    ERR_RESIDUAL_INCOME_INSUFFICIENT,
    ERR_REVIEW_NOT_FOUND,
    ERR_SEASONING_NOT_SATISFIED,
    ERR_SECOND_VALUATION_REQUIRED,
    ERR_STATEMENT_MONTH_NOT_FOUND,
    ERR_STATEMENT_MONTH_STATE_INVALID,
    ERR_UNKNOWN_ROLE,
    ERR_VALUATION_ORDER_NOT_FOUND,
    ERR_VALUATION_ORDER_STATE_INVALID,
    ERR_VALUE_OUT_OF_RANGE,
    ERR_WORKSHEET_NOT_FOUND,
    ERR_WORKSHEET_STATE_INVALID,
)
from test_helpers.constants import ROLE_PROGRAM_ADMIN
from test_helpers.test_users import (
    ADMIN,
    APPRAISAL_REVIEWER,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    headers_with_blank_role,
    headers_with_blank_user,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user,
    underwriter,
)

INVESTOR = "INV-ALPHA"
# A syntactically valid UUID that the server never issued.
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


def test_the_three_authentication_codes_are_distinct(api):
    """One request that would succeed fails three different ways on its headers.

    PRD 2.1: "If `X-User-Role` is absent, empty, or consists only of whitespace, the
    request is rejected with `ERR_MISSING_ROLE_HEADER` (HTTP 401); a header sent as an
    empty or whitespace-only string counts as absent rather than as a role name. If the
    supplied role is not one of the eight roles the platform recognises, the request is
    rejected with `ERR_UNKNOWN_ROLE` (HTTP 401). If `X-User-ID` is absent, empty, or
    whitespace-only, the request is rejected with `ERR_MISSING_USER_HEADER` (HTTP 401)."

    Design: Corner/errors/corner_missing_auth_headers_return_the_three_401_codes
    """
    program = _dscr_program(api)

    no_role = api.get_program(program["id"], headers_without_role("pa-1"))
    blank_role = api.get_program(program["id"], headers_with_blank_role("pa-1"))
    unknown_role = api.get_program(program["id"],
                                   headers_with_unknown_role("pa-1", "Auditor"))
    no_user = api.get_program(program["id"],
                              headers_without_user(ROLE_PROGRAM_ADMIN))
    blank_user = api.get_program(program["id"],
                                 headers_with_blank_user(ROLE_PROGRAM_ADMIN))
    accepted = api.get_program(program["id"], ADMIN)

    validate_error(no_role, ERR_MISSING_ROLE_HEADER)
    # An empty string counts as absent, never as a role name.
    validate_error(blank_role, ERR_MISSING_ROLE_HEADER)
    validate_error(unknown_role, ERR_UNKNOWN_ROLE)
    validate_error(no_user, ERR_MISSING_USER_HEADER)
    validate_error(blank_user, ERR_MISSING_USER_HEADER)
    # The same path and the same permissions succeed with both headers present.
    assert validate_success(accepted)["id"] == program["id"]


def test_shape_domain_and_uniqueness_failures_are_three_different_codes(api):
    """A missing field, a bad enum, an out-of-domain number and a reused code.

    PRD 2.8: "`ERR_INVALID_REQUEST` — on every POST endpoint: a non-optional input field
    is missing, a value has the wrong type, an enum value is not a declared member, or the
    body carries a field the endpoint does not declare."

    PRD 3.1: "a value outside its domain is rejected with `ERR_VALUE_OUT_OF_RANGE`" and
    "every amount field denominated in cents must be zero or greater" and "`fico_score`
    must be between 300 and 850 inclusive".

    PRD 3.1: "A second registration reusing an existing `program_code` is rejected with
    `ERR_DUPLICATE_CODE`".

    Design: Corner/errors/corner_invalid_payload_shape_range_and_duplicate_code_rejected
    """
    program = _dscr_program(api)
    borrower = fx.create_borrower(api, legal_name="Vera Valid", fico_score=700,
                                  monthly_debt_obligations_cents=0,
                                  verified_liquid_assets_cents=5000000,
                                  age_years=50)

    missing_field = api.create_borrower(
        F.borrower_payload(legal_name="No Fico", fico_score=None,
                          monthly_debt_obligations_cents=0,
                          verified_liquid_assets_cents=5000000, age_years=50),
        LOAN_OFFICER)
    out_of_domain = api.create_borrower(
        F.borrower_payload(legal_name="High Fico", fico_score=900,
                          monthly_debt_obligations_cents=0,
                          verified_liquid_assets_cents=5000000, age_years=50),
        LOAN_OFFICER)
    bad_enum = api.create_loan_file(
        F.loan_file_payload(borrower["id"], program["id"], INVESTOR,
                           loan_amount_cents=60000000,
                           property_value_cents=80000000,
                           occupancy="PRIMARY_RESIDENCE", purpose="PURCHASE",
                           lien_position="FIRST", note_rate_pct=8.750,
                           apor_pct=6.100, term_months=360,
                           amortization_type="INTEREST_ONLY",
                           monthly_taxes_cents=60000,
                           monthly_insurance_cents=20000),
        LOAN_OFFICER)
    negative_money = api.create_borrower(
        F.borrower_payload(legal_name="Negative Assets", fico_score=700,
                          monthly_debt_obligations_cents=0,
                          verified_liquid_assets_cents=-1, age_years=50),
        LOAN_OFFICER)
    duplicate = api.create_program(
        F.program_payload("DSCR", name="Investor DSCR Second Attempt",
                         min_dscr=1.2000, max_ltv_pct=80.00, min_fico=680,
                         min_reserves_months=6, min_residual_income_cents=0,
                         second_valuation_ltv_threshold_pct=90.00,
                         second_valuation_loan_amount_threshold_cents=150000000,
                         atr_exempt_flag=True),
        ADMIN)

    assert "fico_score" not in F.borrower_payload(fico_score=None)
    validate_error(missing_field, ERR_INVALID_REQUEST)
    validate_error(out_of_domain, ERR_VALUE_OUT_OF_RANGE)
    # The shape rule fires before the existence rule would have accepted the ids.
    validate_error(bad_enum, ERR_INVALID_REQUEST)
    validate_error(negative_money, ERR_VALUE_OUT_OF_RANGE)
    validate_error(duplicate, ERR_DUPLICATE_CODE)

    # The refused duplicate overwrote nothing.
    survivor = validate_success(api.get_program(program["id"], ADMIN))
    A.assert_fields(survivor, {"name": "Investor DSCR", "min_fico": 660})
    assert A.as_decimal(survivor["min_dscr"]) == A.as_decimal("1.1000")


def test_all_thirteen_not_found_codes_are_reachable_and_distinct(api):
    """One never-issued identifier, thirteen resource-specific 404 codes.

    PRD 2.8: "Existence of every referenced resource, on every endpoint that has a path
    parameter or a foreign-key input." and "The applicable code is the one naming the
    missing resource — `ERR_PROGRAM_NOT_FOUND`, `ERR_OVERLAY_NOT_FOUND`,
    `ERR_BORROWER_NOT_FOUND`, `ERR_LOAN_FILE_NOT_FOUND`, `ERR_WORKSHEET_NOT_FOUND`,
    `ERR_STATEMENT_MONTH_NOT_FOUND`, `ERR_VALUATION_ORDER_NOT_FOUND`,
    `ERR_REVIEW_NOT_FOUND`, `ERR_FEE_ITEM_NOT_FOUND`, `ERR_EXCEPTION_NOT_FOUND`,
    `ERR_AUDIT_NOT_FOUND`, `ERR_FINDING_NOT_FOUND` or `ERR_POOL_NOT_FOUND` — each at HTTP
    404."

    Design: Corner/errors/corner_every_declared_not_found_code_is_reachable
    """
    validate_error(api.get_program(MISSING_ID, ADMIN), ERR_PROGRAM_NOT_FOUND)
    validate_error(api.get_overlay(MISSING_ID, ADMIN), ERR_OVERLAY_NOT_FOUND)
    validate_error(api.get_borrower(MISSING_ID, LOAN_OFFICER),
                   ERR_BORROWER_NOT_FOUND)
    validate_error(api.get_loan_file(MISSING_ID, LOAN_OFFICER),
                   ERR_LOAN_FILE_NOT_FOUND)
    validate_error(api.get_worksheet(MISSING_ID, UNDERWRITER),
                   ERR_WORKSHEET_NOT_FOUND)
    validate_error(api.exclude_statement_month(
        MISSING_ID, F.exclusion_payload("Non-recurring transfer"), UNDERWRITER),
        ERR_STATEMENT_MONTH_NOT_FOUND)
    validate_error(api.get_valuation_order(MISSING_ID, APPRAISAL_REVIEWER),
                   ERR_VALUATION_ORDER_NOT_FOUND)
    validate_error(api.override_escalation(
        MISSING_ID, F.override_escalation_payload("No such review"),
        APPRAISAL_REVIEWER), ERR_REVIEW_NOT_FOUND)
    validate_error(api.void_fee_item(MISSING_ID,
                                     F.void_payload("No such fee item"),
                                     LOAN_OFFICER), ERR_FEE_ITEM_NOT_FOUND)
    validate_error(api.get_exception_request(MISSING_ID, UNDERWRITER),
                   ERR_EXCEPTION_NOT_FOUND)
    validate_error(api.get_audit(MISSING_ID, POST_CLOSE_AUDITOR),
                   ERR_AUDIT_NOT_FOUND)
    validate_error(api.rebut_finding(MISSING_ID,
                                     F.rebuttal_payload("No such finding"),
                                     LOAN_OFFICER), ERR_FINDING_NOT_FOUND)
    validate_error(api.get_pool(MISSING_ID, SECURITIZATION_ANALYST),
                   ERR_POOL_NOT_FOUND)


def _bank_statement_file_with_children(api):
    """A DRAFT worksheet with two adjacent months and one ORDERED primary order."""
    program = fx.create_program(
        api, "BANK_STATEMENT_12MO", name="Bank Statement 12",
        statement_period_months=12, default_expense_factor_pct=50.00,
        min_expense_factor_pct=25.00, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=3, max_dti_pct=55.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)
    borrower = fx.create_borrower(
        api, legal_name="Stefan State", fico_score=700, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=90000,
        verified_liquid_assets_cents=4000000, age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program["id"], INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    uw = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "BANK_STATEMENT", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       300000, prepaid_finance_charge_flag=True)
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    worksheet = fx.create_worksheet(api, loan_file["id"], "BANK_STATEMENT",
                                    submitted["version"], uw,
                                    expense_factor_source="PROGRAM_DEFAULT")
    month_one = fx.attach_statement_month(api, worksheet["id"],
                                          "2026-06-01T00:00:00Z",
                                          "2026-07-01T00:00:00Z", 12222221, uw)
    month_two = fx.attach_statement_month(api, worksheet["id"],
                                          "2026-07-01T00:00:00Z",
                                          "2026-08-01T00:00:00Z", 12222221, uw)
    order = fx.order_valuation(api, loan_file["id"], "PRIMARY_APPRAISAL",
                               "2026-05-01T00:00:00Z", APPRAISAL_REVIEWER,
                               vendor_code="VEND-A")
    return worksheet, month_one, month_two, order, uw


def test_each_child_entity_owns_its_own_wrong_state_code(api):
    """Three children, three distinct 409 codes, and one 422 that is not a state error.

    PRD 3.4: "The file's `Underwriter` accepts a worksheet in `CALCULATED` status while
    the loan file is in `UNDERWRITING` or `SUSPENDED`, moving it `CALCULATED →
    ACCEPTED`."

    PRD 2.8: "`ERR_WORKSHEET_STATE_INVALID` — on `POST
    /income-worksheets/{id}/statement-months`, `POST /income-worksheets/{id}/calculate`
    and `POST /income-worksheets/{id}/accept`."

    PRD 3.4: "is refused with `ERR_STATEMENT_MONTH_STATE_INVALID` when the month is
    already `EXCLUDED` — an exclusion is never treated as a harmless no-op." and
    "Excluding the only remaining `INCLUDED` month is refused with
    `ERR_NO_INCLUDED_STATEMENT_MONTHS`."

    PRD 3.5: "A second receipt against the same order, or a receipt against an order
    that is not `ORDERED`, is refused with `ERR_VALUATION_ORDER_STATE_INVALID`, as is a
    decision against an order that is not `RECEIVED`."

    Design: Corner/errors/corner_child_lifecycle_state_codes_rejected_per_entity
    """
    worksheet, month_one, month_two, order, uw = _bank_statement_file_with_children(api)

    accept_draft = api.accept_worksheet(worksheet["id"], uw)
    excluded = fx.exclude_statement_month(api, month_one["id"], uw,
                                          "Interaccount transfer")
    re_exclude = api.exclude_statement_month(
        month_one["id"],
        F.exclusion_payload("Interaccount transfer, second attempt"), uw)
    empty_sample = api.exclude_statement_month(
        month_two["id"], F.exclusion_payload("Would empty the sample"), uw)
    decide_ordered = api.decide_valuation(order["id"],
                                          F.accept_valuation_payload(),
                                          APPRAISAL_REVIEWER)
    received = fx.receive_valuation(api, order["id"], 40000000)
    receive_again = api.receive_valuation(order["id"],
                                          F.receive_payload(40000000),
                                          APPRAISAL_REVIEWER)

    # Accept demands CALCULATED; the worksheet never left DRAFT.
    validate_error(accept_draft, ERR_WORKSHEET_STATE_INVALID)
    A.assert_fields(excluded, {"inclusion_status": "EXCLUDED",
                               "exclusion_reason": "Interaccount transfer"})
    after_exclusion = validate_success(api.get_worksheet(worksheet["id"], uw))
    # The exclusion is not a calculation, so the worksheet stays in DRAFT. PRD 3.4
    # writes `included_month_count` in step one of the bank-statement calculation,
    # which has never run here, so its value on a DRAFT worksheet is not pinned.
    A.assert_fields(after_exclusion, {"status": "DRAFT"})
    validate_error(re_exclude, ERR_STATEMENT_MONTH_STATE_INVALID)
    # Emptying the included set is a business-rule refusal, not a state refusal.
    validate_error(empty_sample, ERR_NO_INCLUDED_STATEMENT_MONTHS)
    surviving = [row for row in validate_success(
        api.list_statement_months(worksheet["id"], uw))
        if row["id"] == month_two["id"]]
    A.assert_fields(surviving[0], {"inclusion_status": "INCLUDED"})
    validate_error(decide_ordered, ERR_VALUATION_ORDER_STATE_INVALID)
    A.assert_fields(received, {"status": "RECEIVED"})
    A.assert_money(received["appraised_value_cents"], 40000000,
                   "appraised_value_cents")
    validate_error(receive_again, ERR_VALUATION_ORDER_STATE_INVALID)
    once = validate_success(api.get_valuation_order(order["id"],
                                                    APPRAISAL_REVIEWER))
    A.assert_money(once["appraised_value_cents"], 40000000,
                   "appraised_value_cents")
    A.assert_fields(once, {"status": "RECEIVED"})


def _depletion_program(api):
    return fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion Gates",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=60.00,
        min_residual_income_cents=300000,
        second_valuation_ltv_threshold_pct=85.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=False)


def _depletion_file_ready_to_approve(api, program_id, legal_name, debts, assets,
                                     uw):
    """One 30000000-cent depletion loan carried to the brink of approval."""
    borrower = fx.create_borrower(
        api, legal_name=legal_name, fico_score=700, self_employed_flag=True,
        entity_ownership_pct=100.00, monthly_debt_obligations_cents=debts,
        verified_liquid_assets_cents=assets, age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program_id, INVESTOR,
        loan_amount_cents=30000000, purchase_price_cents=40000000,
        property_value_cents=40000000, occupancy="PRIMARY", purpose="PURCHASE",
        lien_position="FIRST", note_rate_pct=7.500, apor_pct=6.100,
        term_months=360, amortization_type="FULLY_AMORTIZING",
        monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    fx.select_doc_type(api, loan_file["id"], "ASSET_DEPLETION", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       300000, prepaid_finance_charge_flag=True)
    submitted = fx.submit_to_underwriting(api, loan_file["id"])
    worksheet = fx.create_worksheet(
        api, loan_file["id"], "ASSET_DEPLETION", submitted["version"], uw,
        asset_bucket_checking_cents=15000000,
        asset_bucket_brokerage_cents=22222225,
        asset_bucket_retirement_cents=30000001)
    calculated = fx.calculate_worksheet(api, worksheet["id"], uw)
    fx.accept_worksheet(api, worksheet["id"], uw)
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 40000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    determined = fx.run_atr_determination(api, loan_file["id"], uw)
    return loan_file, calculated, determined


def test_the_three_program_ceilings_fire_in_their_declared_order(api):
    """One income, three borrowers, and the ordering that masks a second shortfall.

    PRD 3.9: "Only then do the program ceilings and floors apply, and they too are
    ordered." and "`dti_pct` must be non-null and no greater than the program's
    `max_dti_pct`, and a breach is `ERR_DTI_ABOVE_PROGRAM_MAX`" and
    "`documented_reserves_months` must be at least the program's `min_reserves_months`,
    inclusively, or the refusal is `ERR_RESERVES_INSUFFICIENT`." and
    "`residual_income_cents` must be at least the program's
    `min_residual_income_cents`, or the refusal is `ERR_RESIDUAL_INCOME_INSUFFICIENT`".

    PRD 3.4: "`eligible_assets_after_haircut_cents` is the sum of those three
    already-rounded components" and "Required reserves are the program's
    `min_reserves_months` multiplied by the file's current `pitia_monthly_cents`, and
    `depletable_assets_cents` is the eligible assets less those required reserves,
    floored at zero."

    The DTI file carries a residual of 172277 against the 300000 floor, so priority 36
    hides a breach that priority 38 would also have caught.

    Design: Corner/errors/corner_program_ceiling_codes_fire_in_priority_order_at_approval
    """
    program = _depletion_program(api)
    uw = underwriter("uw-1")
    dti_file, dti_ws, dti_state = _depletion_file_ready_to_approve(
        api, program["id"], "Dora Debt", 200000, 4000000, uw)
    reserves_file, reserves_ws, reserves_state = _depletion_file_ready_to_approve(
        api, program["id"], "Rex Reserve", 90000, 500000, uw)
    residual_file, residual_ws, residual_state = _depletion_file_ready_to_approve(
        api, program["id"], "Rosa Residual", 90000, 4000000, uw)

    for worksheet in (dti_ws, reserves_ws, residual_ws):
        A.assert_money(worksheet["eligible_assets_after_haircut_cents"], 56000004,
                       "eligible_assets_after_haircut_cents")
        A.assert_money(worksheet["depletable_assets_cents"], 54351420,
                       "depletable_assets_cents")
        A.assert_money(worksheet["monthly_qualifying_income_cents"], 647041,
                       "monthly_qualifying_income_cents")
    for state in (dti_state, reserves_state, residual_state):
        A.assert_money(state["pitia_monthly_cents"], 274764, "pitia_monthly_cents")
        A.assert_pct_2dp(state["ltv_pct"], "75.00", "ltv_pct")
        A.assert_fields(state, {"points_and_fees_test_result": "PASS",
                                "atr_documentation_status": "DOCUMENTED"})
    A.assert_pct_2dp(dti_state["dti_pct"], "73.37", "dti_pct")
    A.assert_money(dti_state["residual_income_cents"], 172277,
                   "residual_income_cents")
    A.assert_pct_2dp(dti_state["documented_reserves_months"], "14.56",
                     "documented_reserves_months")
    A.assert_pct_2dp(reserves_state["dti_pct"], "56.37", "dti_pct")
    A.assert_money(reserves_state["residual_income_cents"], 282277,
                   "residual_income_cents")
    A.assert_pct_2dp(reserves_state["documented_reserves_months"], "1.82",
                     "documented_reserves_months")
    A.assert_pct_2dp(residual_state["dti_pct"], "56.37", "dti_pct")
    A.assert_money(residual_state["residual_income_cents"], 282277,
                   "residual_income_cents")
    A.assert_pct_2dp(residual_state["documented_reserves_months"], "14.56",
                     "documented_reserves_months")

    dti_refused = api.approve_loan_file(dti_file["id"], uw)
    reserves_refused = api.approve_loan_file(reserves_file["id"], uw)
    residual_refused = api.approve_loan_file(residual_file["id"], uw)

    validate_error(dti_refused, ERR_DTI_ABOVE_PROGRAM_MAX)
    validate_error(reserves_refused, ERR_RESERVES_INSUFFICIENT)
    validate_error(residual_refused, ERR_RESIDUAL_INCOME_INSUFFICIENT)
    for loan_file in (dti_file, reserves_file, residual_file):
        after = fx.get_loan_file(api, loan_file["id"], uw)
        A.assert_fields(after, {"status": "UNDERWRITING"})


def test_the_documentation_and_appraisal_gates_refuse_in_ladder_order(api):
    """Seven refused approvals on one file, four codes, and one code twice.

    PRD 3.9: "`atr_documentation_status` must be `DOCUMENTED` or `EXEMPT` with a
    `safe_harbor_class` other than `NOT_EVALUATED`, or the attempt is refused with
    `ERR_ATR_DOCUMENTATION_INCOMPLETE`" and "`second_valuation_status` must be
    `SECOND_NOT_REQUIRED` or `SECOND_RECONCILED`; a file whose second dimension still
    reads `SECOND_REQUIRED`, `SECOND_ORDERED` or `SECOND_RECEIVED` is refused with
    `ERR_SECOND_VALUATION_REQUIRED`." and "`primary_review_status` must be
    `PRIMARY_CLEARED`; `PRIMARY_NOT_ORDERED`, `PRIMARY_PENDING_REVIEW` and
    `PRIMARY_ESCALATED` are all refused with `ERR_APPRAISAL_ESCALATION_UNRESOLVED`".

    PRD 3.9: "`ltv_pct`, measured against the current reconciled value rather than the
    purchase price, must be no more than the program's `max_ltv_pct`, inclusively, or
    the refusal is `ERR_LTV_ABOVE_PROGRAM_MAX`."

    PRD 3.6: "`atr_documentation_status` becomes `EXEMPT`, `safe_harbor_class` becomes
    `EXEMPT_BUSINESS_PURPOSE`, and `rate_spread_pct` is recorded as `note_rate_pct` less
    `apor_pct`, rounded half up to three decimals."

    PRD 3.5: "The same value change also resets `atr_documentation_status` to
    `INCOMPLETE` and `safe_harbor_class` to `NOT_EVALUATED`."

    Design: Corner/errors/corner_documentation_and_appraisal_gate_codes_rejected_in_ladder_order
    """
    program = _dscr_program(api, name="Investor DSCR Gates",
                            second_valuation_loan_amount_threshold_cents=50000000)
    borrower = fx.create_borrower(api, legal_name="Gita Gate", fico_score=700,
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

    # 1. The documentation gate at priority 19 precedes the valuation gates.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_ATR_DOCUMENTATION_INCOMPLETE)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    exempted = fx.run_atr_determination(api, loan_file["id"], uw)
    A.assert_fields(exempted, {"atr_documentation_status": "EXEMPT",
                               "safe_harbor_class": "EXEMPT_BUSINESS_PURPOSE"})
    A.assert_decimal_equals(exempted["rate_spread_pct"], "2.650", 3,
                            "rate_spread_pct")
    # 2. Documentation done, the second-valuation gate at priority 21 takes over.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_SECOND_VALUATION_REQUIRED)
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    # 3. An accepted primary publishes no reconciled value, so nothing moved.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_SECOND_VALUATION_REQUIRED)
    fx.order_receive_accept(api, loan_file["id"], "SECOND_APPRAISAL",
                            "2026-05-15T00:00:00Z", 70000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    # 4. Reconciliation moved the value and invalidated the determination.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_ATR_DOCUMENTATION_INCOMPLETE)
    invalidated = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(invalidated, {"atr_documentation_status": "INCOMPLETE",
                                  "safe_harbor_class": "NOT_EVALUATED"})
    fx.run_atr_determination(api, loan_file["id"], uw)
    # 5. With the second dimension reconciled, the escalation gate fires.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_APPRAISAL_ESCALATION_UNRESOLVED)
    escalated = fx.get_review(api, loan_file["id"], APPRAISAL_REVIEWER)
    A.assert_fields(escalated, {"primary_review_status": "PRIMARY_ESCALATED",
                                "second_valuation_status": "SECOND_RECONCILED"})
    fx.override_escalation(
        api, escalated["id"], APPRAISAL_REVIEWER,
        override_justification="Conservative value accepted after comparable review.")
    # 6. Only the conservative basis is left to fail on.
    validate_error(api.approve_loan_file(loan_file["id"], uw),
                   ERR_LTV_ABOVE_PROGRAM_MAX)

    final = fx.get_loan_file(api, loan_file["id"], uw)
    A.assert_fields(final, {"status": "UNDERWRITING"})
    A.assert_pct_2dp(final["ltv_pct"], "85.71", "ltv_pct")
    A.assert_pct_2dp(final["documented_reserves_months"], "9.66",
                     "documented_reserves_months")
    A.assert_ratio_4dp(final["dscr_ratio"], "1.2367", "dscr_ratio")
    A.assert_money(final["pitia_monthly_cents"], 517500, "pitia_monthly_cents")


def _documented_investment_file(api, program_id, legal_name, fico_score, uw):
    """A DSCR file carried to the brink of approval; every earlier gate cleared."""
    borrower = fx.create_borrower(api, legal_name=legal_name,
                                  fico_score=fico_score,
                                  monthly_debt_obligations_cents=0,
                                  verified_liquid_assets_cents=5000000,
                                  age_years=50)
    loan_file = fx.create_loan_file(
        api, borrower["id"], program_id, INVESTOR,
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT",
        purpose="PURCHASE", lien_position="FIRST", note_rate_pct=8.750,
        apor_pct=6.100, term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000)
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       600000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    fx.order_receive_accept(api, loan_file["id"], "PRIMARY_APPRAISAL",
                            "2026-05-01T00:00:00Z", 80000000,
                            APPRAISAL_REVIEWER, APPRAISAL_REVIEWER)
    fx.run_points_and_fees_test(api, loan_file["id"], uw)
    return loan_file, fx.run_atr_determination(api, loan_file["id"], uw)


def test_the_fico_floor_is_inclusive_and_precedes_the_coverage_floor(api):
    """700 fails on FICO; exactly 720 passes it and fails on the ratio instead.

    PRD 3.9: "The borrower's `fico_score` must be at least the program's `min_fico`,
    inclusively — a score exactly equal to the minimum passes — or the refusal is
    `ERR_FICO_BELOW_PROGRAM_MIN`." and "And on a `DSCR` file only, `dscr_ratio` must be
    at least the program's `min_dscr`, or the refusal is `ERR_DSCR_BELOW_PROGRAM_MIN`".

    PRD 3.3: "the qualifying rent is the lesser of the contract rent and 120 percent of
    `gross_market_rent_cents` rounded half up to the cent".

    The two files differ in nothing but the borrower's score, so an implementation using
    a strict comparison on FICO would refuse both with the same code.

    Design: Corner/errors/corner_fico_and_dscr_program_floors_are_inclusive_and_ordered
    """
    program = _dscr_program(api, name="Investor DSCR Tight", min_dscr=1.2500,
                            max_ltv_pct=90.00, min_fico=720)
    uw = underwriter("uw-1")
    low_file, low_state = _documented_investment_file(
        api, program["id"], "Low Fico Investor", 700, uw)
    exact_file, exact_state = _documented_investment_file(
        api, program["id"], "Exact Fico Investor", 720, uw)

    for state in (low_state, exact_state):
        A.assert_fields(state, {"points_and_fees_test_result": "PASS",
                                "atr_documentation_status": "EXEMPT",
                                "safe_harbor_class": "EXEMPT_BUSINESS_PURPOSE"})
    review = fx.get_review(api, exact_file["id"], APPRAISAL_REVIEWER)
    A.assert_fields(review, {"second_valuation_status": "SECOND_NOT_REQUIRED",
                             "primary_review_status": "PRIMARY_CLEARED"})

    low_refused = api.approve_loan_file(low_file["id"], uw)
    exact_refused = api.approve_loan_file(exact_file["id"], uw)

    validate_error(low_refused, ERR_FICO_BELOW_PROGRAM_MIN)
    validate_error(exact_refused, ERR_DSCR_BELOW_PROGRAM_MIN)
    settled = fx.get_loan_file(api, exact_file["id"], uw)
    A.assert_ratio_4dp(settled["dscr_ratio"], "1.2367", "dscr_ratio")
    A.assert_money(settled["pitia_monthly_cents"], 517500, "pitia_monthly_cents")
    A.assert_pct_2dp(settled["documented_reserves_months"], "9.66",
                     "documented_reserves_months")
    A.assert_pct_2dp(settled["ltv_pct"], "75.00", "ltv_pct")
    A.assert_is_null(settled, "dti_pct")
    A.assert_fields(settled, {"status": "UNDERWRITING"})
    A.assert_fields(fx.get_loan_file(api, low_file["id"], uw),
                    {"status": "UNDERWRITING"})


def test_the_intake_gates_refuse_for_two_reasons_and_one_stale_clock(api):
    """A doc type the program will not offer, one whose data fails, and 23 months.

    PRD 3.3: "The chosen type must be one the file's program actually offers" and
    "choosing `DSCR` additionally requires `occupancy` to be `INVESTMENT` and
    `gross_market_rent_cents` to be present" and "Any violation of any of these is
    refused with `ERR_DOC_TYPE_PROGRAM_MISMATCH`."

    PRD 3.2: "computes the months elapsed as the whole calendar months from the event's
    `completion_date` to the current logical clock date" and "`seasoning_satisfied` is
    true when the elapsed months are at least the required months — exactly meeting the
    requirement satisfies it." and "a file whose `seasoning_satisfied` is false cannot be
    submitted for underwriting and cannot be approved, and both refusals report
    `ERR_SEASONING_NOT_SATISFIED`."

    Design: Corner/errors/corner_intake_gate_codes_mismatch_and_seasoning_are_reachable
    """
    depletion = fx.create_program(
        api, "ASSET_DEPLETION", name="Asset Depletion Standard",
        depletion_horizon_months=84, max_ltv_pct=80.00, min_fico=660,
        min_reserves_months=6, max_dti_pct=50.00,
        min_residual_income_cents=250000,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000)
    dscr = _dscr_program(api, name="Investor DSCR Standard")
    borrower = fx.create_borrower(api, legal_name="Seasoned Sam",
                                  fico_score=700,
                                  monthly_debt_obligations_cents=90000,
                                  verified_liquid_assets_cents=30000001,
                                  age_years=50)
    event = fx.create_credit_event(api, borrower["id"], "FORECLOSURE",
                                   "2024-09-01T00:00:00Z", UNDERWRITER,
                                   documented_flag=True)
    common = dict(loan_amount_cents=30000000, purchase_price_cents=40000000,
                  property_value_cents=40000000, occupancy="PRIMARY",
                  purpose="PURCHASE", lien_position="FIRST",
                  note_rate_pct=7.500, apor_pct=6.100, term_months=360,
                  amortization_type="FULLY_AMORTIZING",
                  monthly_taxes_cents=50000, monthly_insurance_cents=15000)
    depletion_file = fx.create_loan_file(api, borrower["id"], depletion["id"],
                                         INVESTOR, **common)
    dscr_file = fx.create_loan_file(api, borrower["id"], dscr["id"], INVESTOR,
                                    **common)
    uw = underwriter("uw-1")

    not_offered = api.select_doc_type(depletion_file["id"],
                                      F.doc_type_selection_payload("BANK_STATEMENT"),
                                      uw)
    preconditions_fail = api.select_doc_type(dscr_file["id"],
                                            F.doc_type_selection_payload("DSCR"),
                                            uw)

    validate_error(not_offered, ERR_DOC_TYPE_PROGRAM_MISMATCH)
    # The same code, but because a PRIMARY residence has no market rent at all.
    validate_error(preconditions_fail, ERR_DOC_TYPE_PROGRAM_MISMATCH)
    for refused in (depletion_file, dscr_file):
        still_draft = fx.get_loan_file(api, refused["id"], LOAN_OFFICER)
        A.assert_fields(still_draft, {"status": "DRAFT"})
        A.assert_is_null(still_draft, "doc_type")

    selected = fx.select_doc_type(api, depletion_file["id"], "ASSET_DEPLETION", uw)
    A.assert_fields(selected, {"doc_type": "ASSET_DEPLETION",
                               "status": "DOC_TYPE_SELECTED"})
    fx.create_fee_item(api, depletion_file["id"], "F-ORIG",
                       "ORIGINATION_POINTS", 300000,
                       prepaid_finance_charge_flag=True)

    unseasoned = api.submit_to_underwriting(depletion_file["id"], LOAN_OFFICER)

    validate_error(unseasoned, ERR_SEASONING_NOT_SATISFIED)
    stale = fx.get_loan_file(api, depletion_file["id"], uw)
    A.assert_fields(stale, {"governing_credit_event_id": event["id"],
                            "seasoning_months_required": 36,
                            "seasoning_months_elapsed": 23,
                            "seasoning_satisfied": False})

    fx.set_clock(api, "2027-09-01T00:00:00Z", uw)
    seasoned = fx.submit_to_underwriting(api, depletion_file["id"])

    A.assert_fields(seasoned, {"status": "UNDERWRITING",
                               "seasoning_months_elapsed": 36,
                               "seasoning_satisfied": True})


def test_terminal_findings_and_a_non_member_removal_are_refused(api):
    """One 409 code from three different states, and a removal naming a stranger.

    PRD 3.10: "`UPHOLD` and `WAIVE` are accepted from either `ISSUED` or `REBUTTED`;
    `RETURN_FOR_MORE_INFO` additionally requires the finding to be `REBUTTED`, because
    there is no rebuttal to return otherwise. `UPHELD` and `WAIVED` are terminal and
    accept neither a further adjudication nor a rebuttal; every violation of any of these
    rules is `ERR_FINDING_STATE_INVALID`."

    PRD 3.10: "Findings may only be filed while the parent audit is `OPEN` or
    `FINDINGS_ISSUED`; `CLEARED` and `MATERIAL_DEFECT` are closed to new findings, and
    the refusal is `ERR_FINDING_STATE_INVALID` at 409."

    PRD 3.10: "`grade` is `A_CLEAN` when `defect_score` is 0" and "Once
    `open_finding_count` reaches zero — every finding terminal — an audit in
    `FINDINGS_ISSUED` moves to `CLEARED` if its grade is `A_CLEAN` or `B_MINOR`".

    PRD 3.8: "When a loan is named, it must currently be a member of this very pool —
    its `pool_id` must equal the pool id in the path — or the refusal is
    `ERR_LOAN_NOT_IN_POOL`."

    Design: Corner/errors/corner_terminal_finding_and_non_member_removal_codes_are_reachable
    """
    program = _dscr_program(api, name="Investor DSCR Audit")
    uw = underwriter("uw-1")
    loan_file, _state = _documented_investment_file(api, program["id"],
                                                    "Audited Ada", 700, uw)
    fx.approve(api, loan_file["id"], uw)
    closed = fx.close(api, loan_file["id"])
    audit = fx.create_audit(api, loan_file["id"], "RANDOM")
    finding = fx.create_finding(api, audit["id"], "F-RENT-DOC",
                               "INCOME_CALCULATION", "MINOR")
    pool = fx.create_pool(api, "P-2026-09-EMPTY", INVESTOR, 200000000)

    A.assert_fields(closed, {"status": "CLOSED"})
    A.assert_is_null(closed, "pool_id")

    # RETURN_FOR_MORE_INFO has no rebuttal to return on an ISSUED finding.
    premature_return = api.adjudicate_finding(
        finding["id"],
        F.adjudication_payload("RETURN_FOR_MORE_INFO", "Send more paper"),
        POST_CLOSE_AUDITOR)
    validate_error(premature_return, ERR_FINDING_STATE_INVALID)

    waived = fx.adjudicate_finding(api, finding["id"], "WAIVE",
                                   POST_CLOSE_AUDITOR, "Immaterial")
    A.assert_fields(waived, {"status": "WAIVED", "rebuttal_round": 0})
    cleared = validate_success(api.get_audit(audit["id"], POST_CLOSE_AUDITOR))
    A.assert_fields(cleared, {"defect_score": 0, "grade": "A_CLEAN",
                              "open_finding_count": 0, "status": "CLEARED"})

    # WAIVED is terminal, so even a rebuttal from a permitted role is refused.
    late_rebuttal = api.rebut_finding(finding["id"],
                                      F.rebuttal_payload("Too late to argue"), uw)
    validate_error(late_rebuttal, ERR_FINDING_STATE_INVALID)
    A.assert_fields(validate_success(api.get_audit(audit["id"], POST_CLOSE_AUDITOR)),
                    {"status": "CLEARED"})

    # A CLEARED audit is closed to new findings, and that is the same code again.
    late_finding = api.create_finding(
        F.finding_payload(audit["id"], "F-LATE-ADD", "APPRAISAL", "MINOR"),
        POST_CLOSE_AUDITOR)
    validate_error(late_finding, ERR_FINDING_STATE_INVALID)
    rows = validate_success(api.list_findings(audit["id"], POST_CLOSE_AUDITOR))
    A.assert_ids_equal(rows, [finding["id"]], "finding ids")

    # The loan exists and the pool is OPEN; it simply is not a member.
    not_a_member = api.remove_from_pool(
        pool["id"],
        F.pool_removal_payload("LOAN_INELIGIBLE", pool["version"],
                               loan_file["id"]),
        SECURITIZATION_ANALYST)
    validate_error(not_a_member, ERR_LOAN_NOT_IN_POOL)
    untouched = validate_success(api.get_pool(pool["id"], SECURITIZATION_ANALYST))
    A.assert_fields(untouched, {"member_loan_count": 0, "status": "OPEN"})
    A.assert_version(untouched, pool["version"])
