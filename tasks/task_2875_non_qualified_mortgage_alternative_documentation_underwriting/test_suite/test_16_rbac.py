"""Role-based access corners: one shared read surface, twenty exclusive operations
attempted by the wrong role, and the acting-user separations that outlive the role check.
"""

from test_helpers import assertions as A
from test_helpers import factories as F
from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_success
from test_helpers.api_errors import (
    ERR_EXCEPTION_AUTHORITY_INSUFFICIENT,
    ERR_EXCEPTION_STATE_INVALID,
    ERR_POOL_NOT_FOUND,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_UNAUTHORIZED,
)
from test_helpers.test_users import (
    ADMIN,
    APPRAISAL_REVIEWER,
    CHIEF_CREDIT_OFFICER,
    CREDIT_COMMITTEE,
    LOAN_OFFICER,
    POST_CLOSE_AUDITOR,
    SECURITIZATION_ANALYST,
    UNDERWRITER,
    chief_credit_officer,
    credit_committee,
    underwriter,
)

INVESTOR = "INV-ALPHA"
MISSING_ID = "00000000-0000-4000-8000-000000000000"


def _dscr_program(api, **overrides):
    payload = dict(
        name="Investor DSCR Read", min_dscr=1.1000, max_ltv_pct=85.00,
        min_fico=660, min_reserves_months=6, min_residual_income_cents=0,
        second_valuation_ltv_threshold_pct=90.00,
        second_valuation_loan_amount_threshold_cents=150000000,
        atr_exempt_flag=True,
    )
    payload.update(overrides)
    return fx.create_program(api, "DSCR", **payload)


def _investment_file(api, program_id, legal_name, fico_score, **overrides):
    borrower = fx.create_borrower(api, legal_name=legal_name,
                                  fico_score=fico_score,
                                  monthly_debt_obligations_cents=0,
                                  verified_liquid_assets_cents=5000000,
                                  age_years=50)
    payload = dict(
        loan_amount_cents=60000000, purchase_price_cents=80000000,
        property_value_cents=80000000, occupancy="INVESTMENT",
        purpose="PURCHASE", lien_position="FIRST", note_rate_pct=8.750,
        apor_pct=6.100, term_months=360, amortization_type="INTEREST_ONLY",
        monthly_taxes_cents=60000, monthly_insurance_cents=20000,
        gross_market_rent_cents=620000, lease_rent_cents=640000,
    )
    payload.update(overrides)
    return fx.create_loan_file(api, borrower["id"], program_id, INVESTOR,
                               **payload)


def test_seven_roles_read_the_same_file_and_the_program_admin_cannot(api):
    """The read surface is shared verbatim, yet the clock is shared more widely.

    PRD 4: "| GET | `/loan-files/{id}` | Read one loan file with its full computed
    determination snapshot. | LoanOfficer, Underwriter, CreditCommittee,
    ChiefCreditOfficer, AppraisalReviewer, PostCloseAuditor, SecuritizationAnalyst |"

    PRD 4: "the roles listed below are the complete authorised set for each route — any
    other role is refused with `ERR_UNAUTHORIZED`."

    PRD 4: "| POST | `/_clock/set_current_utc` | Set the server's logical UTC clock,
    which every seasoning, validity-window, lookback and re-order-buffer rule reads. |
    ProgramAdmin, LoanOfficer, Underwriter, CreditCommittee, ChiefCreditOfficer,
    AppraisalReviewer, PostCloseAuditor, SecuritizationAnalyst |"

    PRD 2.8: "`ERR_SEGREGATION_OF_DUTIES` — on exactly eight operations", none of which
    is a read, so an underwriter who is not the assigned underwriter still reads freely.

    Design: Corner/rbac/corner_shared_read_surface_open_to_seven_roles_but_closed_to_program_admin
    """
    program = _dscr_program(api)
    loan_file = _investment_file(api, program["id"], "Readable Rita", 700)

    permitted = [
        validate_success(api.get_loan_file(loan_file["id"], LOAN_OFFICER)),
        validate_success(api.get_loan_file(loan_file["id"], underwriter("uw-2"))),
        validate_success(api.get_loan_file(loan_file["id"], CREDIT_COMMITTEE)),
        validate_success(api.get_loan_file(loan_file["id"], CHIEF_CREDIT_OFFICER)),
        validate_success(api.get_loan_file(loan_file["id"], APPRAISAL_REVIEWER)),
        validate_success(api.get_loan_file(loan_file["id"], POST_CLOSE_AUDITOR)),
        validate_success(api.get_loan_file(loan_file["id"],
                                           SECURITIZATION_ANALYST)),
    ]
    refused = api.get_loan_file(loan_file["id"], ADMIN)

    # No role sees a redacted or role-scoped view of the same row.
    for row in permitted:
        A.assert_fields(row, {"id": loan_file["id"], "status": "DRAFT"})
        A.assert_pct_2dp(row["ltv_pct"], "75.00", "ltv_pct")
        A.assert_money(row["pitia_monthly_cents"], 517500, "pitia_monthly_cents")
        # PRD 3.3: `dscr_ratio` "stays null on any file whose `doc_type` is not
        # `DSCR`", and this file has never taken a doc-type selection.
        A.assert_is_null(row, "dscr_ratio")
    assert all(row == permitted[0] for row in permitted)
    validate_error(refused, ERR_UNAUTHORIZED)

    # The clock is the wider surface: the role locked out of the file may set it,
    # and both of these calls are accepted rather than refused.
    fx.set_clock(api, "2026-08-02T00:00:00Z", ADMIN)
    fx.set_clock(api, "2026-08-01T00:00:00Z", SECURITIZATION_ANALYST)


def test_every_exclusive_operation_refuses_the_wrong_role_before_anything_else(api):
    """Twenty wrong-role calls with unknown ids and empty bodies, one code throughout.

    PRD 2.1: "Only once both headers are accepted does the platform consider whether the
    role is permitted to perform the requested operation; a role that is not listed for
    the endpoint is rejected with `ERR_UNAUTHORIZED` (HTTP 403)."

    PRD 2.8: "4. `ERR_UNAUTHORIZED` — on every endpoint." and "5. Existence of every
    referenced resource, on every endpoint that has a path parameter or a foreign-key
    input." and "6. `ERR_INVALID_REQUEST` — on every POST endpoint: a non-optional input
    field is missing".

    Authorization at priority 4 precedes existence at 5 and shape at 6, so no call may
    answer 404 for the never-issued path id or complain about the empty body.

    Design: Corner/rbac/corner_cross_role_exclusive_operations_are_forbidden
    """
    attempts = [
        api.create_program({}, LOAN_OFFICER),
        api.create_overlay({}, UNDERWRITER),
        api.create_borrower({}, UNDERWRITER),
        api.create_loan_file({}, CREDIT_COMMITTEE),
        api.select_doc_type(MISSING_ID, {}, LOAN_OFFICER),
        api.submit_to_underwriting(MISSING_ID, UNDERWRITER),
        api.suspend_loan_file(MISSING_ID, {}, ADMIN),
        api.run_atr_determination(MISSING_ID, APPRAISAL_REVIEWER),
        api.approve_loan_file(MISSING_ID, CHIEF_CREDIT_OFFICER),
        api.deny_loan_file(MISSING_ID, {}, SECURITIZATION_ANALYST),
        api.close_loan_file(MISSING_ID, UNDERWRITER),
        api.create_worksheet({}, LOAN_OFFICER),
        api.receive_valuation(MISSING_ID, {}, UNDERWRITER),
        api.override_escalation(MISSING_ID, {}, UNDERWRITER),
        api.create_exception_request({}, CREDIT_COMMITTEE),
        api.decide_exception_request(MISSING_ID, {}, UNDERWRITER),
        api.create_audit({}, UNDERWRITER),
        api.adjudicate_finding(MISSING_ID, {}, LOAN_OFFICER),
        api.create_pool({}, CHIEF_CREDIT_OFFICER),
        api.assign_loan_to_pool(MISSING_ID, {}, POST_CLOSE_AUDITOR),
    ]

    assert len(attempts) == 20
    for attempt in attempts:
        validate_error(attempt, ERR_UNAUTHORIZED)

    # Nothing was created and nothing was resolved behind the role gate.
    listed = api.list_loan_files(LOAN_OFFICER)
    validate_success(listed)
    A.assert_meta_pagination(listed.json()["meta"], 10, 0, 0, False)
    validate_error(api.get_pool(MISSING_ID, SECURITIZATION_ANALYST),
                   ERR_POOL_NOT_FOUND)


def test_no_single_operator_can_request_and_fully_grant_a_waiver(api):
    """Five refusals decided by the acting user rather than by the role alone.

    PRD 3.7: "a tier-2 request needs a `CreditCommittee` first signoff followed by a
    `ChiefCreditOfficer` second signature — so a `ChiefCreditOfficer` may not supply both
    tier-2 signatures and a `CreditCommittee` member may not supply the second one. A role
    acting outside that authority is refused with
    `ERR_EXCEPTION_AUTHORITY_INSUFFICIENT`. Independently, the acting `X-User-ID` must
    differ from `requested_by_user_id`, and on a tier-2 second signature it must also
    differ from `first_signoff_user_id`; either violation is refused with
    `ERR_SEGREGATION_OF_DUTIES`, so no single operator can both request and fully grant a
    guideline waiver."

    PRD 3.7: "Once a request has reached `APPROVED`, `DENIED` or `VOIDED`, no further
    decision is accepted and any attempt is refused with `ERR_EXCEPTION_STATE_INVALID`."

    PRD 2.8: "`ERR_SEGREGATION_OF_DUTIES` — on exactly eight operations: `POST
    /loan-files/{id}/points-and-fees-test`".

    Design: Corner/rbac/corner_segregation_of_duties_cannot_be_self_served_by_one_operator
    """
    program = _dscr_program(api, name="Investor DSCR SoD")
    overlay = fx.create_overlay(api, INVESTOR, "OV-FICO-740", "MIN_FICO", "GTE",
                                740, applies_to_program_code="DSCR",
                                waivable_flag=True, required_authority_tier=2,
                                severity="MINOR")
    loan_file = _investment_file(api, program["id"], "Waiver Wanda", 700)
    uw_one = underwriter("uw-1")
    fx.select_doc_type(api, loan_file["id"], "DSCR", uw_one)
    fx.create_fee_item(api, loan_file["id"], "F-ORIG", "ORIGINATION_POINTS",
                       600000, prepaid_finance_charge_flag=True)
    fx.submit_to_underwriting(api, loan_file["id"])
    request = fx.create_exception_request(
        api, loan_file["id"], overlay["id"], uw_one,
        justification="Reserves of 9.66 months and 25 percent equity compensate for the 700 score",
        compensating_factors=["RESERVES", "EQUITY"])

    A.assert_fields(request, {"required_authority_tier": 2,
                              "requested_by_user_id": "uw-1",
                              "status": "PENDING_REVIEW"})
    assert A.as_decimal(request["pinned_metric_value"]) == A.as_decimal(700)

    # 1. The right role on someone else's file is still the wrong operator.
    wrong_underwriter = api.run_points_and_fees_test(loan_file["id"],
                                                    underwriter("uw-2"))
    validate_error(wrong_underwriter, ERR_SEGREGATION_OF_DUTIES)

    # 2. The requester wearing a signing role is refused on the user, not the role.
    self_approval = api.decide_exception_request(
        request["id"],
        F.exception_approve_payload("Approving my own request"),
        credit_committee("uw-1"))
    validate_error(self_approval, ERR_SEGREGATION_OF_DUTIES)

    # 3. A ChiefCreditOfficer may not supply the tier-2 first signature.
    cco_first = api.decide_exception_request(
        request["id"], F.exception_approve_payload("Skipping the committee"),
        chief_credit_officer("cco-1"))
    validate_error(cco_first, ERR_EXCEPTION_AUTHORITY_INSUFFICIENT)

    forked = fx.approve_exception(api, request["id"], credit_committee("cc-1"),
                                 "Committee signoff")
    A.assert_fields(forked, {"status": "AWAITING_SECOND_SIGNATURE",
                             "first_signoff_user_id": "cc-1"})
    A.assert_is_null(forked, "second_signoff_user_id")
    half_signed = fx.get_loan_file(api, loan_file["id"], uw_one)
    A.assert_codes_in_order(half_signed["overlay_breach_codes"], ["OV-FICO-740"],
                            "overlay_breach_codes")
    A.assert_fields(half_signed, {"unresolved_overlay_breach_count": 1})

    # 4. A different committee member is still only committee authority.
    cc_second = api.decide_exception_request(
        request["id"],
        F.exception_approve_payload("Second committee member"),
        credit_committee("cc-2"))
    validate_error(cc_second, ERR_EXCEPTION_AUTHORITY_INSUFFICIENT)

    # 5. The first signer with a bigger hat has authority and still cannot sign.
    same_signer = api.decide_exception_request(
        request["id"], F.exception_approve_payload("Same person, bigger hat"),
        chief_credit_officer("cc-1"))
    validate_error(same_signer, ERR_SEGREGATION_OF_DUTIES)

    joined = fx.approve_exception(api, request["id"],
                                 chief_credit_officer("cco-1"),
                                 "Second signature")
    A.assert_fields(joined, {"status": "APPROVED",
                             "first_signoff_user_id": "cc-1",
                             "second_signoff_user_id": "cco-1",
                             "decision_reason": "Second signature"})
    waived = fx.get_loan_file(api, loan_file["id"], uw_one)
    A.assert_fields(waived, {"unresolved_overlay_breach_count": 0,
                             "investor_notification_required": True})

    already_decided = api.decide_exception_request(
        request["id"], F.exception_deny_payload("Changed my mind"),
        chief_credit_officer("cco-1"))
    validate_error(already_decided, ERR_EXCEPTION_STATE_INVALID)
    settled = validate_success(api.get_exception_request(request["id"], uw_one))
    A.assert_fields(settled, {"status": "APPROVED",
                              "decision_reason": "Second signature"})

    # The call refused first succeeds untouched for the assigned underwriter.
    allowed = fx.run_points_and_fees_test(api, loan_file["id"], uw_one)
    A.assert_fields(allowed, {"id": loan_file["id"]})
