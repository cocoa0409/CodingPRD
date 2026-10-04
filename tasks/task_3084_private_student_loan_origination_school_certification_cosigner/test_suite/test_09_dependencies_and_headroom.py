"""Cross-entity state dependencies, allocation ordering and conservation."""
from test_helpers import (
    ERR_CERTIFICATION_PERIOD_CONFLICT,
    ERR_DISBURSEMENT_BLOCKED,
    ERR_INVALID_STATE,
    ERR_SCHOOL_CAPACITY_EXCEEDED,
    TEST_USERS,
    approve,
    add_application,
    build_origination,
    certify_payload,
    file_and_certify,
    file_certification,
    forbearance_payload,
    get_success_data,
    schedule_disbursement,
    schedule_and_release,
    setup_certified_loan,
    validate_error,
    validate_success,
)
from test_helpers import api_client as client


def _loan(orig):
    return validate_success(client.get_loan(orig.loan["id"], TEST_USERS["servicer_headers"]))


def _two_period_orig(**overrides):
    defaults = {
        "requested_amount_cents": 400000,
        "cost_of_attendance_cents": 480000,
        "other_aid_cents": 80000,
    }
    defaults.update(overrides)
    orig = build_origination(
        borrower_score=705, cosigner_score=765,
        application_overrides=defaults,
    )
    approve(orig)
    return orig


# ---------------------------------------------------------------------------
# cross_entity_state_dependency / certification_transition_gated_by_the_parent_application_state
# ---------------------------------------------------------------------------

def test_a_rejected_certification_reverts_its_parent_application(api):
    """PRD §3.3: "A rejected certification reverts the application so that a fresh
    request may be filed... When every sibling certification on the application is
    `REJECTED` or `EXPIRED`, the application reverts from `SCHOOL_CERT_PENDING` to
    `APPROVED`."

    Design: Difficulty/cross_entity_state_dependency/certification_transition_gated_by_the_parent_application_state
    """
    orig = _two_period_orig()
    first = file_certification(orig, academic_period_label="2026-FALL",
                               certified_amount_cents=400000)
    second = file_certification(orig, academic_period_label="2027-SPRING",
                                certified_amount_cents=400000,
                                period_end_date="2027-05-15T00:00:00Z")
    rejected = get_success_data(
        client.reject_certification(second["id"], {"rejection_reason": "COST_EXCEEDED"},
                                    orig.school_headers)
    )
    assert rejected["certification_status"] == "REJECTED"
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "SCHOOL_CERT_PENDING"

    get_success_data(
        client.reject_certification(first["id"], {"rejection_reason": "NOT_ENROLLED"},
                                    orig.school_headers)
    )
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "APPROVED"


def test_a_rejected_certification_may_be_re_filed_against_its_approved_parent(api):
    """PRD §3.3: "A rejected certification may be re-filed: the request returns it to
    `REQUESTED`, clears its `rejection_reason` to null, and resets its
    `certified_amount_cents` to 0."

    Design: Difficulty/cross_entity_state_dependency/certification_transition_gated_by_the_parent_application_state
    """
    orig = _two_period_orig()
    first = file_certification(orig, academic_period_label="2026-FALL",
                               certified_amount_cents=400000)
    get_success_data(
        client.reject_certification(first["id"], {"rejection_reason": "COST_EXCEEDED"},
                                    orig.school_headers)
    )
    refiled = validate_success(
        client.refile_certification(first["id"], orig.school_headers)
    )
    assert refiled["certification_status"] == "REQUESTED"
    assert refiled["rejection_reason"] is None
    assert refiled["certified_amount_cents"] == 0

    recertified = validate_success(
        client.certify(first["id"], certify_payload(certified_amount_cents=400000),
                       orig.school_headers)
    )
    assert recertified["certification_status"] == "CERTIFIED"


# ---------------------------------------------------------------------------
# boundary_precision_check / school_capacity_boundary_on_an_exact_fit_and_an_empty_population
# ---------------------------------------------------------------------------

def test_a_first_certification_that_exactly_fills_the_school_period_is_accepted(api):
    """PRD §3.3: "the certified amount, added to the amounts already certified for
    that same period, must not exceed the school's
    `certification_capacity_per_period_cents`."

    Design: Difficulty/boundary_precision_check/school_capacity_boundary_on_an_exact_fit_and_an_empty_population
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=760,
        school_overrides={"certification_capacity_per_period_cents": 400000},
        application_overrides={
            "requested_amount_cents": 400000,
            "cost_of_attendance_cents": 500000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    certification = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    assert certification["certification_status"] == "CERTIFIED"
    assert validate_success(
        client.get_certification(certification["id"], TEST_USERS["school_headers"])
    )["certified_amount_cents"] == 400000


def test_the_next_certification_at_a_full_school_period_is_refused(api):
    """PRD §3.3: "the sum of certified amounts across all of one school's `CERTIFIED`
    and `PARTIAL_CERTIFIED` certifications sharing an `academic_period_label` may not
    exceed that school's `certification_capacity_per_period_cents`; breaching it is
    `ERR_SCHOOL_CAPACITY_EXCEEDED`."

    Design: Difficulty/boundary_precision_check/school_capacity_boundary_on_an_exact_fit_and_an_empty_population
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=760,
        school_overrides={"certification_capacity_per_period_cents": 400000},
        application_overrides={
            "requested_amount_cents": 400000,
            "cost_of_attendance_cents": 500000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    first = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=400000
    )
    assert first["certification_status"] == "CERTIFIED"

    # A second borrower's application at the same school and period, and no room left.
    second_orig = add_application(
        orig, cosigner_score=770,
        application_overrides={
            "requested_amount_cents": 120000,
            "cost_of_attendance_cents": 200000,
            "other_aid_cents": 80000,
        },
    )
    approve(second_orig)
    second = file_certification(
        second_orig, academic_period_label="2026-FALL", certified_amount_cents=120000
    )
    response = client.certify(
        second["id"], certify_payload(certified_amount_cents=120000),
        second_orig.school_headers,
    )
    validate_error(response, ERR_SCHOOL_CAPACITY_EXCEEDED)
    assert validate_success(
        client.get_certification(second["id"], TEST_USERS["school_headers"])
    )["certification_status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# resource_temporal_overlap / school_period_capacity_is_aggregate_not_row_local
# ---------------------------------------------------------------------------

def test_period_capacity_is_aggregated_across_two_applications_at_one_school(api):
    """PRD §3.3: "the sum of certified amounts across all of one school's `CERTIFIED`
    and `PARTIAL_CERTIFIED` certifications sharing an `academic_period_label` may not
    exceed that school's `certification_capacity_per_period_cents`."

    Design: Difficulty/resource_temporal_overlap/school_period_capacity_is_aggregate_not_row_local
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=765,
        school_overrides={"certification_capacity_per_period_cents": 1000000},
        application_overrides={
            "requested_amount_cents": 600000,
            "cost_of_attendance_cents": 700000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    first = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=600000
    )
    assert first["certification_status"] == "CERTIFIED"

    second_orig = add_application(
        orig, cosigner_score=770,
        application_overrides={
            "requested_amount_cents": 500000,
            "cost_of_attendance_cents": 600000,
            "other_aid_cents": 100000,
        },
    )
    approve(second_orig)
    second = file_certification(
        second_orig, academic_period_label="2026-FALL", certified_amount_cents=500000
    )
    response = client.certify(
        second["id"], certify_payload(certified_amount_cents=500000),
        second_orig.school_headers,
    )
    validate_error(response, ERR_SCHOOL_CAPACITY_EXCEEDED)
    assert validate_success(
        client.get_certification(second["id"], TEST_USERS["school_headers"])
    )["certification_status"] == "REQUESTED"


# ---------------------------------------------------------------------------
# compensating_invariant / headroom_is_conserved_across_release_and_school_refund
# ---------------------------------------------------------------------------

def test_certification_headroom_spans_the_full_ceiling_before_any_release(api):
    """PRD §3.3: "the loan's remaining headroom is the certified total minus the
    disbursed total, floored at zero."
    PRD §3.2: "its `certification_limit_cents` is fixed at this point as the cost of
    attendance minus other aid, floored at zero."

    Design: Difficulty/compensating_invariant/headroom_is_conserved_across_release_and_school_refund
    """
    orig = setup_certified_loan(
        certified_amount_cents=805000,
        policy_overrides={},
    )
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 805000

    schedule_and_release(orig.loan["id"], amount_cents=805000)
    drawn = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert drawn["certified_headroom_cents"] == 0, "the whole certification is drawn"


def test_a_school_refund_moves_the_disbursed_total_and_re_opens_headroom(api):
    """PRD §3.4: "The recorded certification is deliberately *not* reduced by the
    returned amount — the excess is credited against principal without shrinking the
    certified ceiling."
    PRD §3.4: "recomputes the loan's `disbursed_amount_cents` net of the refund"

    Design: Difficulty/compensating_invariant/headroom_is_conserved_across_release_and_school_refund
    """
    orig = setup_certified_loan(
        certified_amount_cents=700000,
        disbursement_amount_cents=700000,
        disburse=True,
    )
    before = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert before["certified_headroom_cents"] == 0

    get_success_data(
        client.school_refund(orig.disbursement["id"], {"remainder_credited_cents": 50000},
                             orig.school_headers)
    )
    loan = _loan(orig)
    assert loan["certified_amount_cents"] == 700000, "the ceiling is not shrunk"
    assert loan["disbursed_amount_cents"] == 650000
    summary = validate_success(
        client.loan_summary(orig.loan["id"], TEST_USERS["servicer_headers"])
    )
    assert summary["certified_headroom_cents"] == 50000


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / state_precondition_outranks_fiscal_decline
# ---------------------------------------------------------------------------

def test_a_denied_application_records_the_failing_credit_gate(api):
    """PRD §3.2: "Choosing `DENY` instead records the first failing underwriting gate
    in `denial_reason`, one of `CREDIT_SCORE`, `DTI`, `INSUFFICIENT_HISTORY` or
    `POLICY_ERROR`, and — when the file carried a cosigner — sets that cosigner's
    `underwriting_status` to `INELIGIBLE`."

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_decline
    """
    orig = build_origination(
        borrower_score=560, cosigner_score=600, cosigner_dti=0.40,
    )
    assert orig.cosigner["underwriting_status"] == "ELIGIBLE", "600 clears 660 - 60"

    denied = get_success_data(
        client.decide_application(
            orig.application["id"], {"decision": "DENY"}, TEST_USERS["underwriter_headers"]
        )
    )
    assert denied["application_status"] == "DENIED"
    assert denied["denial_reason"] == "CREDIT_SCORE"
    assert validate_success(
        client.get_cosigner(orig.cosigner["id"], TEST_USERS["servicer_headers"])
    )["underwriting_status"] == "INELIGIBLE"


def test_a_state_failure_outranks_the_fiscal_credit_decline(api):
    """PRD §2.12: "State preconditions then apply: an operation that is not a declared
    transition out of the resource's current state, including any operation attempted
    on a resource already in a terminal state, yields `ERR_INVALID_STATE`"
    PRD §2.12: "Business-safety and compliance checks follow the state checks, and
    they run before all fiscal checks"
    PRD §2.12: "Fiscal checks are evaluated last. They include a declined credit
    outcome (`ERR_CREDIT_DECLINED`), an out-of-range money amount
    (`ERR_AMOUNT_OUT_OF_RANGE`)"

    Design: Difficulty/priority_pair_validation_conflict/state_precondition_outranks_fiscal_decline
    """
    orig = build_origination(
        borrower_score=560, cosigner_score=600, cosigner_dti=0.40,
    )
    get_success_data(
        client.decide_application(
            orig.application["id"], {"decision": "DENY"}, TEST_USERS["underwriter_headers"]
        )
    )
    # The blended final score is also in tier DECLINED, so both rules could apply.
    response = client.decide_application(
        orig.application["id"], {"decision": "APPROVE"}, TEST_USERS["underwriter_headers"]
    )
    validate_error(response, ERR_INVALID_STATE)
    assert validate_success(
        client.get_application(orig.application["id"], TEST_USERS["underwriter_headers"])
    )["application_status"] == "DENIED"


# ---------------------------------------------------------------------------
# priority_pair_validation_conflict / disbursement_block_safety_outranks_delinquent_loan_referential_check
# ---------------------------------------------------------------------------

def test_forbearance_sets_the_disbursement_block_on_a_current_loan(api):
    """PRD §3.4: "which it is whenever any disbursement child carries `refund_status`
    of `REFUND_DUE` or whenever the loan is `DEFAULT` or `FORBEARANCE_DEFERMENT`"

    Design: Difficulty/priority_pair_validation_conflict/disbursement_block_safety_outranks_delinquent_loan_referential_check
    """
    orig = setup_certified_loan(disburse=True)
    granted = get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(months_requested=3, start_date="2026-11-01T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    assert granted["relief_status"] == "GRANTED"
    loan = _loan(orig)
    assert loan["loan_status"] == "FORBEARANCE_DEFERMENT"
    assert loan["disburse_blocked"] is True
    assert loan["delinquency_stage"] == "CURRENT", "the loan is provably not delinquent"


def test_the_safety_block_error_outranks_the_delinquent_referential_check(api):
    """PRD §2.12: "Business-safety and compliance checks follow the state checks, and
    they run before all fiscal checks: a blocked disbursement yields
    `ERR_DISBURSEMENT_BLOCKED`"
    PRD §3.4: "A disbursement may not be scheduled or released while the loan's
    `disburse_blocked` flag is true... a blocked attempt is refused with
    `ERR_DISBURSEMENT_BLOCKED`."

    Design: Difficulty/priority_pair_validation_conflict/disbursement_block_safety_outranks_delinquent_loan_referential_check
    """
    orig = setup_certified_loan(disburse=True)
    get_success_data(
        client.request_forbearance(
            orig.loan["id"],
            forbearance_payload(months_requested=3, start_date="2026-11-01T00:00:00Z"),
            TEST_USERS["servicer_headers"],
        )
    )
    version = _loan(orig)["version"]
    response = client.schedule_disbursement(
        orig.loan["id"],
        {
            "academic_period_label": "2027-SPRING",
            "period_start_date": "2027-01-05T00:00:00Z",
            "period_end_date": "2027-05-15T00:00:00Z",
            "scheduled_date": "2027-02-15T00:00:00Z",
            "amount_cents": 100000,
            "expected_loan_version": version,
        },
        TEST_USERS["servicer_headers"],
    )
    validate_error(response, ERR_DISBURSEMENT_BLOCKED)

def test_the_period_capacity_bucket_is_keyed_by_academic_period_label(api):
    """PRD §3.3: "the sum of certified amounts across all of one school's `CERTIFIED`
    and `PARTIAL_CERTIFIED` certifications sharing an `academic_period_label` may not
    exceed that school's `certification_capacity_per_period_cents`."

    Design: Difficulty/resource_temporal_overlap/school_period_capacity_is_aggregate_not_row_local
    """
    orig = build_origination(
        borrower_score=700, cosigner_score=765,
        school_overrides={"certification_capacity_per_period_cents": 1000000},
        application_overrides={
            "requested_amount_cents": 900000,
            "cost_of_attendance_cents": 1000000,
            "other_aid_cents": 100000,
        },
    )
    approve(orig)
    fall = file_and_certify(
        orig, academic_period_label="2026-FALL", certified_amount_cents=900000
    )
    assert fall["certification_status"] == "CERTIFIED"

    # A second application at the same school, but a different academic period: the
    # 1000000 bucket that FALL filled is not shared with SPRING.
    second_orig = add_application(
        orig, cosigner_score=770,
        application_overrides={
            "requested_amount_cents": 800000,
            "cost_of_attendance_cents": 900000,
            "other_aid_cents": 100000,
        },
    )
    approve(second_orig)
    spring = file_certification(
        second_orig, academic_period_label="2027-SPRING", certified_amount_cents=800000,
        period_end_date="2027-05-15T00:00:00Z",
    )
    certified = validate_success(
        client.certify(
            spring["id"], certify_payload(certified_amount_cents=800000),
            second_orig.school_headers,
        )
    )
    assert certified["certification_status"] == "CERTIFIED"
    assert certified["certified_amount_cents"] == 800000
