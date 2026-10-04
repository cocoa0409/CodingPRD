"""Authentication, ownership, the logical clock and optimistic concurrency."""
from test_helpers import (
    DEFAULT_CLOCK_ISO,
    ERR_FORBIDDEN,
    ERR_INVALID_CLOCK,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_UNAUTHENTICATED,
    NON_EXISTENT_UUID,
    TEST_USERS,
    add_application,
    add_days,
    approve,
    build_user_headers,
    build_origination,
    certify_payload,
    file_and_certify,
    file_certification,
    forbearance_payload,
    get_success_data,
    period_due_date,
    release_application_payload,
    schedule_disbursement,
    schedule_and_release,
    setup_certified_loan,
    setup_loan_in_repayment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


# ---------------------------------------------------------------------------
# authentication and ownership
# ---------------------------------------------------------------------------

def test_an_undeclared_role_is_rejected_before_any_business_validation(api):
    """PRD §2.1: "A request that omits either header, or that presents an
    `X-User-Role` value that is not one of the six declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/errors/unrecognised_role_header_returns_unauthenticated
    """
    baseline = validate_paginated(
        client.list_schools(TEST_USERS["admin_headers"])
    )[1]["total_count"]
    response = client.create_school(
        {"name": "Ghost College", "school_code": "009994", "state_code": "OH",
         "certification_capacity_per_period_cents": 1000},
        build_user_headers("test-loanshark-1", "LoanShark"),
    )
    validate_error(response, ERR_UNAUTHENTICATED)
    _, meta = validate_paginated(client.list_schools(TEST_USERS["admin_headers"]))
    assert meta["total_count"] == baseline, "the undeclared role persisted nothing"


def test_a_cosigner_role_cannot_read_a_loan_as_another_cosigner(api):
    """PRD §2.1: "When `X-User-Role` is `Cosigner`, `X-User-ID` is the `id` of the
    acting `Cosigner`; ownership checks on any resource that references a `Cosigner`
    — including a re-underwriting request and a release application filed on that
    cosigner's behalf — compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/rbac/school_cannot_certify_an_application_it_does_not_own
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    other = add_application(orig, cosigner_score=770)
    response = client.reunderwrite_cosigner(
        orig.cosigner["id"], {"credit_score": 770, "dti_ratio": 0.19},
        build_user_headers(other.cosigner["id"], "Cosigner"),
    )
    validate_error(response, ERR_FORBIDDEN)


def test_a_borrower_cannot_underwrite_its_own_application(api):
    """PRD §2.1: "When the acting role is not permitted to perform the requested
    operation, the request is rejected with `ERR_FORBIDDEN` (HTTP 403)."
    PRD §4: the decision operation is authorized for `Underwriter` only.

    Design: Corner/rbac/borrower_cannot_decide_an_application
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    assert orig.application["application_status"] == "UNDER_REVIEW"

    response = client.decide_application(
        orig.application["id"], {"decision": "APPROVE"}, orig.applicant_headers
    )
    validate_error(response, ERR_FORBIDDEN)
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "UNDER_REVIEW"


def test_a_school_cannot_certify_another_schools_certification(api):
    """PRD §2.1: "When `X-User-Role` is `School`, `X-User-ID` is the `id` of the
    acting `School`; ownership checks on any resource that references a `School` —
    such as filing or re-filing a certification, recording an enrollment change,
    certifying an amount, rejecting a request, or returning an over-disbursement —
    compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/rbac/school_cannot_certify_an_application_it_does_not_own
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    approve(orig)
    certification = file_certification(
        orig, academic_period_label="2026-FALL", certified_amount_cents=805000
    )
    from test_helpers import create_school

    other_school = create_school()
    response = client.certify(
        certification["id"], certify_payload(certified_amount_cents=805000),
        build_user_headers(other_school["id"], "School"),
    )
    validate_error(response, ERR_FORBIDDEN)
    stored = validate_success(
        client.get_certification(certification["id"], orig.school_headers)
    )
    assert stored["certification_status"] == "REQUESTED"
    assert stored["certified_amount_cents"] == 0


def test_a_borrower_cannot_cancel_another_borrowers_application(api):
    """PRD §2.4: "an application may be re-considered or cancelled only by the
    borrower who owns it, a cosigner release application may be re-applied for or
    withdrawn only by the borrower who owns the underlying loan, and a cosigner may
    refresh its own figures only when the acting cosigner is the record addressed.
    When the acting identity does not match the owning entity, the request fails
    with `ERR_FORBIDDEN`."

    Design: Corner/rbac/borrower_cannot_decide_an_application
    """
    orig = build_origination(borrower_score=700, cosigner_score=760)
    other = add_application(orig, cosigner_score=770)
    response = client.cancel_application(orig.application["id"], other.applicant_headers)
    validate_error(response, ERR_FORBIDDEN)
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "UNDER_REVIEW"


# ---------------------------------------------------------------------------
# the logical clock
# ---------------------------------------------------------------------------

def test_an_instant_before_the_fixed_default_is_refused(api):
    """PRD §2.5: "The supplied value must be a well-formed ISO 8601 UTC instant that
    is not earlier than the fixed start-of-time default `2026-09-01T00:00:00Z`; a
    malformed value, or one that precedes that default, is rejected with
    `ERR_INVALID_CLOCK` (HTTP 400)."

    Design: Corner/errors/clock_rejects_a_malformed_instant
    """
    response = client.set_clock("2026-08-01T00:00:00Z", TEST_USERS["admin_headers"])
    validate_error(response, ERR_INVALID_CLOCK)

    accepted = validate_success(client.set_clock(DEFAULT_CLOCK_ISO, TEST_USERS["admin_headers"]))
    assert accepted["current_utc"] == "2026-09-01T00:00:00.000Z", "the clock never moved"


def test_advancing_the_clock_matures_a_certification_to_expired(api):
    """PRD §2.5: "advancing past a certification's period end plus thirty days
    matures the certification to `EXPIRED`"
    PRD §3.3: "When the logical clock passes the certification's period end plus
    thirty days, a `CERTIFIED` or `PARTIAL_CERTIFIED` certification becomes
    `EXPIRED`, and the loan's certified total is recomputed to exclude it."

    Design: Corner/state_machines/expired_certification_can_no_longer_be_certified
    """
    orig = setup_certified_loan(disburse=False, period_end_date="2026-12-20T00:00:00Z")
    set_clock("2027-02-15T00:00:00Z")
    stored = validate_success(
        client.get_certification(orig.certification["id"], orig.school_headers)
    )
    assert stored["certification_status"] == "EXPIRED"
    assert _loan(orig)["certified_amount_cents"] == 0, "the expired child is excluded"


def test_an_expired_certification_is_locked_down(api):
    """PRD §3.3: "Certification requests in `REQUESTED` may subsequently be expired,
    and `EXPIRED` is the terminal certification state."
    PRD §2.12: "an operation that is not a declared transition out of the resource's
    current state, including any operation attempted on a resource already in a
    terminal state, yields `ERR_INVALID_STATE`"

    Design: Corner/state_machines/expired_certification_can_no_longer_be_certified
    """
    orig = setup_certified_loan(disburse=False, period_end_date="2026-12-20T00:00:00Z")
    set_clock("2027-02-15T00:00:00Z")
    assert validate_success(
        client.get_certification(orig.certification["id"], orig.school_headers)
    )["certification_status"] == "EXPIRED"

    response = client.certify(
        orig.certification["id"], certify_payload(certified_amount_cents=500000),
        orig.school_headers,
    )
    validate_error(response, ERR_INVALID_STATE)


# ---------------------------------------------------------------------------
# optimistic concurrency control
# ---------------------------------------------------------------------------

def test_a_stale_loan_version_rejects_a_disbursement_schedule(api):
    """PRD §2.8: "Submitting a repayment plan against a loan and scheduling a
    disbursement against a loan each require the request body to carry
    `expected_loan_version`... If the supplied `expected_loan_version` no longer
    equals the loan's current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412), and no part of the operation is applied."

    Design: Corner/errors/stale_loan_version_is_reported_before_the_headroom_check
    """
    orig = setup_certified_loan(disburse=False)
    live_version = _loan(orig)["version"]
    response = client.schedule_disbursement(
        orig.loan["id"],
        {
            "academic_period_label": "2026-FALL",
            "period_start_date": "2026-09-02T00:00:00Z",
            "period_end_date": "2026-12-20T00:00:00Z",
            "scheduled_date": "2026-09-15T00:00:00Z",
            "amount_cents": 900000,
            "expected_loan_version": live_version - 1,
        },
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_STALE_VERSION)
    assert _loan(orig)["version"] == live_version
    assert validate_success(
        client.list_disbursements(orig.loan["id"], TEST_USERS["servicer_headers"])
    ) == []


def test_a_stale_loan_version_rejects_a_repayment_plan(api):
    """PRD §2.8: "This field is required — it is not optional — on both operations."
    PRD §2.8: "a disbursement scheduled against a stale view might be sized against
    certification headroom that a release or a school refund has already consumed."

    Design: Corner/cross_cutting_layers/stale_plan_submission_is_rejected_on_the_loans_version
    """
    orig = setup_loan_in_repayment(periods=30)
    stale_version = _loan(orig)["version"]

    first = get_success_data(
        client.create_repayment_plan(
            orig.loan["id"],
            {"plan_type": "GRADUATED", "term_months": 120,
             "expected_loan_version": stale_version},
            orig.applicant_headers,
        )
    )
    assert _loan(orig)["version"] > stale_version, "the first write advanced the version"

    response = client.create_repayment_plan(
        orig.loan["id"],
        {"plan_type": "EXTENDED", "term_months": 180,
         "expected_loan_version": stale_version},
        orig.applicant_headers,
    )
    validate_error(response, ERR_STALE_VERSION)

    plans = validate_success(
        client.list_repayment_plans(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert {plan["id"] for plan in plans} == {orig.plan["id"], first["id"]}, (
        "the stale call wrote nothing"
    )


# ---------------------------------------------------------------------------
# cross-entity state dependency
# ---------------------------------------------------------------------------

def test_the_same_relief_request_succeeds_once_the_loan_reaches_in_school(api):
    """PRD §3.7: "A relief grant is permitted only when the requested window is at
    least one month long, when the loan's current status admits relief — `IN_SCHOOL`,
    `GRACE`, `REPAYMENT` or `FORBEARANCE_DEFERMENT`"

    Design: Difficulty/cross_entity_state_dependency/loan_relief_transition_gated_by_the_loans_own_origination_state
    """
    orig = build_origination(
        borrower_score=700, with_cosigner=False,
        policy_overrides={"allows_standalone_borrower": True},
        application_overrides={
            "requested_amount_cents": 500000,
            "cost_of_attendance_cents": 600000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    certification = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=500000
    )
    disbursement = schedule_disbursement(orig.loan["id"], amount_cents=500000)
    released = get_success_data(
        client.release_disbursement(disbursement["id"], TEST_USERS["servicer_headers"])
    )
    assert released["disbursement_status"] == "RELEASED"
    assert _loan(orig)["loan_status"] == "IN_SCHOOL"

    granted = get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(months_requested=3, start_date="2026-10-01T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    assert granted["relief_status"] == "GRANTED"
    assert granted["months_granted"] == 3
    loan = _loan(orig)
    assert loan["cumulative_deferment_months"] == 3
    assert loan["loan_status"] == "FORBEARANCE_DEFERMENT"


# ---------------------------------------------------------------------------
# consistency and reconciliation
# ---------------------------------------------------------------------------

def test_the_release_response_carries_the_effects_without_a_read_back(api):
    """PRD §3.4: "A release stamps `released_date` from the logical clock, recomputes
    the loan's `disbursed_amount_cents` over released children net of refunds, and
    re-derives the loan's `principal_cents` and `current_balance_cents`."
    PRD §3.4: "The very first release on a loan is also the event that advances the
    loan from `APPROVED` to `IN_SCHOOL`"

    Design: Corner/consistency_model/immediate_consistency_surfaces_side_effects_in_the_trigger_response
    """
    orig = setup_certified_loan(disburse=False)
    disbursement = schedule_disbursement(orig.loan["id"], amount_cents=805000)
    released = validate_success(
        client.release_disbursement(disbursement["id"], TEST_USERS["servicer_headers"])
    )
    assert released["disbursement_status"] == "RELEASED"
    assert released["released_date"] is not None

    loan = _loan(orig)
    assert loan["loan_status"] == "IN_SCHOOL"
    assert loan["disbursed_amount_cents"] == 805000
    assert loan["principal_cents"] == 805000


def test_a_scheduled_row_does_not_move_the_disbursed_total_until_released(api):
    """PRD §2.10: "the loan's `disbursed_amount_cents` is the running total of
    released disbursements net of any school refund credited back"

    Design: Corner/cross_cutting_layers/doubling_a_disbursement_without_filtering_shows_both_states
    """
    orig = setup_certified_loan(
        certified_amount_cents=1000000,
        requested_amount_cents=1000000,
        cost_of_attendance_cents=1100000,
        other_aid_cents=100000,
        disburse=False,
        disbursement_amount_cents=805000,
    )
    # The scheduled sibling release needs a live certification for its own period
    # label, and filing is only admitted before the FALL release moves the
    # application on, so the SPRING row is recorded first.
    file_and_certify(
        orig, academic_period_label="2027-SPRING", certified_amount_cents=100000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    released_fall = schedule_and_release(orig.loan["id"], amount_cents=805000)
    assert released_fall["disbursement_status"] == "RELEASED"
    assert _loan(orig)["disbursed_amount_cents"] == 805000

    pending = schedule_disbursement(
        orig.loan["id"], amount_cents=100000, academic_period_label="2027-SPRING",
        period_start_date="2027-01-05T00:00:00Z", period_end_date="2027-05-15T00:00:00Z",
        scheduled_date="2027-02-15T00:00:00Z",
    )
    assert _loan(orig)["disbursed_amount_cents"] == 805000, "scheduling alone moves nothing"

    released = get_success_data(
        client.release_disbursement(pending["id"], TEST_USERS["servicer_headers"])
    )
    assert released["amount_cents"] == 100000
    assert released["disbursement_status"] == "RELEASED"
    assert _loan(orig)["disbursed_amount_cents"] == 905000


def test_borrower_scoped_loan_lists_do_not_leak_across_borrowers(api):
    """PRD §3.9: "Lists of borrowers, cosigners, schools and applications support
    optional filtering by `borrower_id`, `school_id`, `policy_id`, `application_id`
    and `cosigner_id` as applicable"
    PRD §2.1: "When `X-User-Role` is `Borrower`, `X-User-ID` is the `id` of the
    acting `Borrower`; ownership checks on any resource that references a `Borrower`
    compare the resource's foreign-key field to `X-User-ID`."

    Design: Corner/cross_cutting_layers/borrower_soft_scope_does_not_leak_across_borrowers
    """
    orig = setup_certified_loan(disburse=True)
    other = add_application(orig, cosigner_score=770)
    approve(other)

    mine = validate_success(
        client.list_borrower_loans(orig.borrower["id"], orig.applicant_headers)
    )
    theirs = validate_success(
        client.list_borrower_loans(other.borrower["id"], other.applicant_headers)
    )
    assert len(mine) == 1 and mine[0]["borrower_id"] == orig.borrower["id"]
    assert len(theirs) == 1 and theirs[0]["borrower_id"] == other.borrower["id"]
    assert mine[0]["id"] != theirs[0]["id"]

def test_an_anonymous_caller_cannot_read_a_loan(api):
    """PRD §2.1: "Every request to the API must carry two headers: `X-User-ID`,
    identifying the acting party, and `X-User-Role`, naming that party's operational
    capacity. A request that omits either header, or that presents an `X-User-Role`
    value that is not one of the six declared roles, is rejected with
    `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/anonymous_caller_cannot_read_a_loan
    """
    orig = setup_certified_loan(disburse=True)
    response = client.get_loan(orig.loan["id"], build_user_headers("test-anon-1", "Anonymous"))
    validate_error(response, ERR_UNAUTHENTICATED)

    # Every declared role may read the same loan.
    for role in ("Borrower", "Cosigner", "School", "Underwriter", "Servicer"):
        user_id = "test-reader-1"
        if role == "Borrower":
            user_id = orig.borrower["id"]
        elif role == "Cosigner":
            user_id = orig.cosigner["id"]
        elif role == "School":
            user_id = orig.school["id"]
        read = client.get_loan(orig.loan["id"], build_user_headers(user_id, role))
        assert read.status_code == 200, f"{role} should be able to read the loan"
