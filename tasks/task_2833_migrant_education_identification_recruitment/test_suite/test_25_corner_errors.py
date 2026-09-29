"""Each declared error code triggered on its own path, with the post-state pinned down."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_decimal_equals,
    assert_error_envelope,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
    assert_student_ledgers,
    assert_version,
    assert_version_advanced_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_CANCELLED,
    ASSIGNMENT_STATUS_PLANNED,
    CLOCK_START_INSTANT,
    CLOSE_OUTCOME_CANCELLED,
    CLOSE_OUTCOME_COMPLETED,
    CLOSURE_REASON_COMPLETED,
    CLOSURE_REASON_COORDINATOR_CLOSED,
    COE_APPROVED,
    COE_DRAFT,
    COE_INVALIDATED,
    COE_QC_PASSED,
    COE_SUBMITTED,
    CREDENTIAL_BASIC,
    CREDENTIAL_QC_CERTIFIED,
    DELIVERY_MODE_IN_PERSON,
    DELIVERY_MODE_WORKSITE,
    ELIGIBILITY_NOT_ELIGIBLE,
    ELIGIBILITY_PENDING_DETERMINATION,
    ELIGIBILITY_TERM_EXPIRED,
    PFS_VARIANT_OSY_PATHWAY,
    PLAN_CLOSED,
    PLAN_DRAFT,
    PLAN_TYPE_OSY_ALTERNATIVE,
    PLAN_TYPE_SUPPLEMENTAL,
    QC_DECISION_PASS,
    REVIEW_OPEN,
    REVIEW_PASSED,
    SCHOOLING_OUT_OF_SCHOOL,
    SELECTION_REASON_QUOTA,
    SERVICE_CATEGORY_INSTRUCTION,
    SERVICE_STATUS_EXITED,
    SERVICE_STATUS_PLAN_DRAFTED,
    TERM_EXPIRED,
    TERM_LAPSED,
    TRANSFER_INITIATED,
    TRANSFER_REJECTED,
    UNKNOWN_UUID,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_liaison_headers,
    make_qc_reviewer_headers,
    make_recruiter_headers,
    headers_without_identity,
)

CANCEL_REASON = "Recruiter reassigned before the season opened."
REJECT_REASON = "Holding state reports no record under the supplied exchange reference."


def test_every_entity_path_id_returns_its_own_not_found_code(client):
    """Twelve GET-by-id routes answer twelve different codes for the same unknown id.

    "The code names the missing resource type: `ERR_AREA_NOT_FOUND` for `area_id`,
    `ERR_RECRUITER_NOT_FOUND` for `recruiter_id`, `ERR_ASSIGNMENT_NOT_FOUND` for
    `assignment_id`, `ERR_STUDENT_NOT_FOUND` for `student_id`, `ERR_MOVE_NOT_FOUND` for
    `move_id`, `ERR_INTERVIEW_NOT_FOUND` for `interview_id`, `ERR_COE_NOT_FOUND` for `coe_id`,
    `ERR_QC_REVIEW_NOT_FOUND` for `review_id`, `ERR_TERM_NOT_FOUND` for `term_id`,
    `ERR_TRANSFER_NOT_FOUND` for `request_id`, `ERR_PLAN_NOT_FOUND` for `plan_id`, and
    `ERR_DELIVERY_NOT_FOUND` for `delivery_id` - all HTTP 404."

    Design: Corner/errors/corner_every_entity_path_id_returns_its_own_not_found_code
    """
    headers = make_admin_headers()
    probes = (
        (client.get_area, api_errors.ERR_AREA_NOT_FOUND),
        (client.get_recruiter, api_errors.ERR_RECRUITER_NOT_FOUND),
        (client.get_assignment, api_errors.ERR_ASSIGNMENT_NOT_FOUND),
        (client.get_student, api_errors.ERR_STUDENT_NOT_FOUND),
        (client.get_move, api_errors.ERR_MOVE_NOT_FOUND),
        (client.get_interview, api_errors.ERR_INTERVIEW_NOT_FOUND),
        (client.get_coe, api_errors.ERR_COE_NOT_FOUND),
        (client.get_qc_review, api_errors.ERR_QC_REVIEW_NOT_FOUND),
        (client.get_term, api_errors.ERR_TERM_NOT_FOUND),
        (client.get_transfer_request, api_errors.ERR_TRANSFER_NOT_FOUND),
        (client.get_plan, api_errors.ERR_PLAN_NOT_FOUND),
        (client.get_delivery, api_errors.ERR_DELIVERY_NOT_FOUND),
    )

    seen = []
    for read, expected in probes:
        response = read(UNKNOWN_UUID, headers)
        validate_error(response, expected, 404)
        assert_error_envelope(response, expected, expected)
        seen.append(expected)

    assert_int_equals(len(set(seen)), 12, "distinct path-existence codes")


def test_call_without_credentials_returns_unauthenticated(client):
    """The identity rung answers first, ahead of both the body and the path lookup.

    "1. **Caller identity** - headers present, role recognised, and for `Recruiter` and
    `QualityControlReviewer` the `X-User-ID` resolves to a recruiter row:
    `ERR_UNAUTHENTICATED` (401)." "The ladder is total: rungs that share a position guard
    disjoint sets of endpoints, so exactly one error is possible for any given call."

    Design: Corner/errors/corner_call_without_credentials_returns_unauthenticated
    """
    area = fixtures.create_area(client)
    anonymous = headers_without_identity()

    known = client.get_area(area["id"], anonymous)
    validate_error(known, api_errors.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(known, api_errors.ERR_UNAUTHENTICATED, "read of a real area")

    empty_body = client.create_area({}, anonymous)
    validate_error(empty_body, api_errors.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(
        empty_body, api_errors.ERR_UNAUTHENTICATED, "create with an empty body"
    )

    unknown = client.get_area(UNKNOWN_UUID, anonymous)
    validate_error(unknown, api_errors.ERR_UNAUTHENTICATED, 401)
    assert_error_envelope(
        unknown, api_errors.ERR_UNAUTHENTICATED, "read of an unknown area"
    )

    survivor = fixtures.read_area(client, area["id"])
    assert_version(survivor, 1, "area")
    assert_int_equals(survivor["name"], area["name"], "area.name")


def test_qc_decision_needs_credentials_and_cannot_be_repeated(client):
    """A BASIC reviewer is turned away, and the certified one may only decide once.

    "The acting recruiter's `credential_level` must be `QC_CERTIFIED`, and a `BASIC` or
    `CERTIFIED` reviewer is refused with `ERR_QC_CREDENTIAL_REQUIRED` (403)." "The review must
    still be `OPEN`; a review that has already been decided is refused with
    `ERR_QC_REVIEW_ALREADY_DECIDED`, so the operation is deliberately not idempotent."

    Design: Corner/errors/corner_qc_decision_needs_credentials_and_cannot_be_repeated
    """
    base = fixtures.area_and_recruiter(client)
    author_id = base.recruiter["id"]
    certified = fixtures.create_recruiter(
        client, full_name="Paula Vega", credential_level=CREDENTIAL_QC_CERTIFIED
    )
    plain = fixtures.create_recruiter(
        client, full_name="Luis Moreno", credential_level=CREDENTIAL_BASIC
    )
    student = fixtures.create_student(client, author_id, base.area["id"])
    move = fixtures.verified_move(client, author_id, student["id"])
    fixtures.file_interview(client, author_id, student["id"], move["id"])
    coe = fixtures.draft_coe(
        client, author_id, student["id"], move["id"], qc_hold_exempt=False
    )
    fixtures.submit_coe(client, author_id, coe["id"])

    run = fixtures.run_qc_selection(client)
    assert_int_equals(run["candidate_count"], 1, "run.candidate_count")
    review = fixtures.open_review_for(client, coe["id"])
    assert_int_equals(review["status"], REVIEW_OPEN, "review.status")
    assert_int_equals(
        review["selection_reason"], SELECTION_REASON_QUOTA, "review.selection_reason"
    )
    reinterview = fixtures.file_reinterview(
        client, certified["id"], student["id"], move["id"], coe["id"]
    )
    payload = factories.qc_decision_payload(QC_DECISION_PASS, reinterview["id"])

    validate_error(
        client.decide_qc_review(
            review["id"], payload, make_qc_reviewer_headers(plain["id"])
        ),
        api_errors.ERR_QC_CREDENTIAL_REQUIRED,
        403,
    )
    held = fixtures.read_qc_review(client, review["id"])
    assert_int_equals(held["status"], REVIEW_OPEN, "review.status")
    assert_is_null(held["reviewer_recruiter_id"], "review.reviewer_recruiter_id")

    decided = validate_success(
        client.decide_qc_review(
            review["id"], payload, make_qc_reviewer_headers(certified["id"])
        ),
        200,
    )
    assert_int_equals(decided["status"], REVIEW_PASSED, "review.status")
    assert_int_equals(
        decided["reviewer_recruiter_id"], certified["id"], "review.reviewer_recruiter_id"
    )
    assert_instant_equals(decided["decided_on"], CLOCK_START_INSTANT, "review.decided_on")
    passed_coe = fixtures.read_coe(client, coe["id"])
    assert_int_equals(passed_coe["status"], COE_QC_PASSED, "coe.status")
    assert_int_equals(passed_coe["correction_round_count"], 0, "coe.correction_round_count")

    validate_error(
        client.decide_qc_review(
            review["id"], payload, make_qc_reviewer_headers(certified["id"])
        ),
        api_errors.ERR_QC_REVIEW_ALREADY_DECIDED,
        409,
    )
    frozen = fixtures.read_qc_review(client, review["id"])
    assert_int_equals(frozen["status"], REVIEW_PASSED, "review.status")
    assert_int_equals(frozen["discrepancy_codes"], [], "review.discrepancy_codes")
    assert_instant_equals(
        frozen["decided_on"], decided["decided_on"], "review.decided_on"
    )
    assert_int_equals(
        fixtures.read_coe(client, coe["id"])["status"], COE_QC_PASSED, "coe.status"
    )


def test_assignment_close_and_activate_guard_the_assignment_state(client):
    """One code covers three state mistakes, and the slot is released exactly once.

    "Attempting `COMPLETED` on a `PLANNED` assignment, or any closure of an assignment already
    `COMPLETED` or `CANCELLED`, is refused with `ERR_ASSIGNMENT_INVALID_STATE`." "Only the
    state office may do it, the assignment must currently be `PLANNED` (otherwise
    `ERR_ASSIGNMENT_INVALID_STATE`)."

    Design: Corner/errors/corner_assignment_close_and_activate_guard_the_assignment_state
    """
    area = fixtures.create_area(client, recruiter_capacity=3)
    recruiter = fixtures.create_recruiter(client)
    assignment = fixtures.create_assignment(client, recruiter["id"], area["id"])
    assert_int_equals(assignment["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_int_equals(
        fixtures.read_area(client, area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )

    validate_error(
        client.close_assignment(
            assignment["id"],
            factories.assignment_close_payload(CLOSE_OUTCOME_COMPLETED),
            make_admin_headers(),
        ),
        api_errors.ERR_ASSIGNMENT_INVALID_STATE,
        409,
    )
    assert_int_equals(
        validate_success(
            client.get_assignment(assignment["id"], make_admin_headers()), 200
        )["status"],
        ASSIGNMENT_STATUS_PLANNED,
        "assignment.status",
    )
    assert_int_equals(
        fixtures.read_area(client, area["id"])["assigned_primary_slots_used"],
        1,
        "area.assigned_primary_slots_used",
    )

    cancelled = validate_success(
        client.close_assignment(
            assignment["id"],
            factories.assignment_close_payload(
                CLOSE_OUTCOME_CANCELLED, cancelled_reason=CANCEL_REASON
            ),
            make_admin_headers(),
        ),
        200,
    )
    assert_int_equals(cancelled["status"], ASSIGNMENT_STATUS_CANCELLED, "assignment.status")
    assert_int_equals(
        cancelled["cancelled_reason"], CANCEL_REASON, "assignment.cancelled_reason"
    )
    assert_int_equals(
        fixtures.read_area(client, area["id"])["assigned_primary_slots_used"],
        0,
        "area.assigned_primary_slots_used",
    )
    assert_int_equals(
        fixtures.read_recruiter(client, recruiter["id"])["active_assignment_count"],
        0,
        "recruiter.active_assignment_count",
    )

    validate_error(
        client.close_assignment(
            assignment["id"],
            factories.assignment_close_payload(
                CLOSE_OUTCOME_CANCELLED, cancelled_reason="Second attempt."
            ),
            make_admin_headers(),
        ),
        api_errors.ERR_ASSIGNMENT_INVALID_STATE,
        409,
    )
    validate_error(
        client.activate_assignment(assignment["id"], make_admin_headers()),
        api_errors.ERR_ASSIGNMENT_INVALID_STATE,
        409,
    )

    settled = validate_success(
        client.get_assignment(assignment["id"], make_admin_headers()), 200
    )
    assert_int_equals(settled["status"], ASSIGNMENT_STATUS_CANCELLED, "assignment.status")
    assert_int_equals(
        settled["cancelled_reason"], CANCEL_REASON, "assignment.cancelled_reason"
    )
    assert_int_equals(
        fixtures.read_area(client, area["id"])["assigned_primary_slots_used"],
        0,
        "area.assigned_primary_slots_used",
    )


def test_closed_plan_refuses_activate_and_a_second_close(client):
    """The state rung answers before the eligibility rung on an uncertified child.

    "The plan itself must be `DRAFT`, or the attempt is refused with
    `ERR_PLAN_INVALID_STATE`." "The plan must be in `DRAFT` or `ACTIVE`, producing `DRAFT ->
    CLOSED` or `ACTIVE -> CLOSED`; a plan already `SUPERSEDED` or `CLOSED` is refused with
    `ERR_PLAN_INVALID_STATE`."

    Design: Corner/errors/corner_closed_plan_refuses_activate_and_a_second_close
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(client, base.recruiter["id"], base.area["id"])
    plan = fixtures.draft_plan(client, student["id"], plan_type=PLAN_TYPE_SUPPLEMENTAL)
    closed = validate_success(
        client.close_plan(
            plan["id"],
            factories.plan_close_payload(CLOSURE_REASON_COORDINATOR_CLOSED),
            make_coordinator_headers(),
        ),
        200,
    )
    assert_int_equals(closed["status"], PLAN_CLOSED, "plan.status")
    assert_int_equals(
        closed["closure_reason"], CLOSURE_REASON_COORDINATOR_CLOSED, "plan.closure_reason"
    )
    assert_int_equals(
        fixtures.read_student(client, student["id"])["eligibility_status"],
        ELIGIBILITY_NOT_ELIGIBLE,
        "student.eligibility_status",
    )

    validate_error(
        client.activate_plan(plan["id"], make_coordinator_headers()),
        api_errors.ERR_PLAN_INVALID_STATE,
        409,
    )
    validate_error(
        client.close_plan(
            plan["id"],
            factories.plan_close_payload(CLOSURE_REASON_COMPLETED),
            make_coordinator_headers(),
        ),
        api_errors.ERR_PLAN_INVALID_STATE,
        409,
    )

    frozen = fixtures.read_plan(client, plan["id"])
    assert_int_equals(frozen["status"], PLAN_CLOSED, "plan.status")
    assert_int_equals(
        frozen["closure_reason"], CLOSURE_REASON_COORDINATOR_CLOSED, "plan.closure_reason"
    )
    assert_version_unchanged(frozen, closed["version"], "plan")
    assert_int_equals(
        fixtures.read_student(client, student["id"])["service_status"],
        SERVICE_STATUS_EXITED,
        "student.service_status",
    )


def test_reidentification_window_closes_then_the_term_locks(client):
    """The same call is refused for the closed grace period, then for the terminal state.

    "Four conditions apply: the term must be `EXPIRED`, and a term that is `ACTIVE`,
    `EXPIRING`, `REIDENTIFIED`, `LAPSED` or `TERMINATED` is refused with
    `ERR_TERM_INVALID_STATE`; the logical clock date must be on or before the term's
    `reidentification_due_on`, and a later clock is refused with
    `ERR_REIDENTIFICATION_WINDOW_CLOSED`; the move named by `new_move_id` must belong to the
    same child and already be in `VERIFIED` status, otherwise `ERR_MOVE_NOT_VERIFIED`; and the
    supplied `residency_date` must be on or after that move's `move_date`, otherwise
    `ERR_RESIDENCY_DATE_BEFORE_MOVE`."

    Design: Corner/errors/corner_reidentification_window_closes_then_the_term_locks
    """
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    recruiter_id = bundle.recruiter["id"]
    term_id = bundle.term["id"]
    assert_date_equals(bundle.term["term_end_on"], "2029-06-30", "term.term_end_on")

    fixtures.set_clock(client, "2029-09-01T00:00:00Z")
    first_sweep = fixtures.sweep(client)
    assert_int_equals(first_sweep["expired_count"], 1, "first sweep.expired_count")
    expired = fixtures.read_term(client, term_id)
    assert_int_equals(expired["status"], TERM_EXPIRED, "term.status")
    assert_date_equals(
        expired["reidentification_due_on"], "2029-08-14", "term.reidentification_due_on"
    )

    fresh_move = fixtures.verified_move(
        client,
        recruiter_id,
        bundle.student["id"],
        from_state_code="OR",
        move_date="2029-08-20",
        distance_miles=305.00,
    )
    payload = factories.reidentify_payload(fresh_move["id"], "2029-08-25")

    validate_error(
        client.reidentify_term(term_id, payload, make_recruiter_headers(recruiter_id)),
        api_errors.ERR_REIDENTIFICATION_WINDOW_CLOSED,
        409,
    )
    untouched = fixtures.read_term(client, term_id)
    assert_int_equals(untouched["status"], TERM_EXPIRED, "term.status")
    assert_is_null(untouched["superseded_by_term_id"], "term.superseded_by_term_id")
    rows, _meta = fixtures.list_rows(
        client.list_terms(make_admin_headers(), {"student_id": bundle.student["id"]})
    )
    assert_row_count(rows, 1, "eligibility terms on file for the child")

    second_sweep = fixtures.sweep(client)
    assert_int_equals(second_sweep["lapsed_count"], 1, "second sweep.lapsed_count")
    assert_int_equals(
        fixtures.read_term(client, term_id)["status"], TERM_LAPSED, "term.status"
    )

    validate_error(
        client.reidentify_term(term_id, payload, make_recruiter_headers(recruiter_id)),
        api_errors.ERR_TERM_INVALID_STATE,
        409,
    )
    child = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        child["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student.eligibility_status",
    )
    assert_is_null(child["eligibility_expires_on"], "student.eligibility_expires_on")


def test_transfer_self_match_is_refused_and_a_rejected_request_locks(client):
    """A record cannot be its own predecessor, and rejection closes the request for good.

    "Three guards apply: the request must be `INITIATED`, otherwise
    `ERR_TRANSFER_INVALID_STATE`; a supplied `matched_prior_student_id` must resolve to an
    existing child, otherwise `ERR_STUDENT_NOT_FOUND`; and it must differ from the request's
    own `student_id`, because a record cannot be its own predecessor - a self-match is refused
    with `ERR_TRANSFER_SELF_MATCH`."

    Design: Corner/errors/corner_transfer_self_match_is_refused_and_a_rejected_request_locks
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    newcomer = fixtures.create_student(client, recruiter_id, base.area["id"])
    predecessor = fixtures.create_student(
        client,
        recruiter_id,
        base.area["id"],
        full_name="Mateo R Reyes",
        current_state_code="CA",
    )
    request = fixtures.open_transfer_request(
        client, newcomer["id"], reported_prior_credits=8.00
    )
    assert_int_equals(request["status"], TRANSFER_INITIATED, "request.status")
    headers = make_liaison_headers()

    validate_error(
        client.match_transfer_request(
            request["id"], factories.match_payload(newcomer["id"]), headers
        ),
        api_errors.ERR_TRANSFER_SELF_MATCH,
        422,
    )
    held = validate_success(client.get_transfer_request(request["id"], headers), 200)
    assert_int_equals(held["status"], TRANSFER_INITIATED, "request.status")
    assert_is_null(held["matched_prior_student_id"], "request.matched_prior_student_id")
    assert_is_null(
        fixtures.read_student(client, newcomer["id"])["prior_record_student_id"],
        "student.prior_record_student_id",
    )

    # "Rejecting the exchange result is permitted from `RECEIVED` and from `RECONCILED`",
    # so the request is first matched against the genuine predecessor and received.
    fixtures.carry_transfer_to_received(client, request["id"], predecessor["id"])

    rejected = validate_success(
        client.reject_transfer_request(
            request["id"], factories.reject_payload(REJECT_REASON), headers
        ),
        200,
    )
    assert_int_equals(rejected["status"], TRANSFER_REJECTED, "request.status")
    assert_int_equals(
        rejected["rejection_reason"], REJECT_REASON, "request.rejection_reason"
    )

    validate_error(
        client.match_transfer_request(
            request["id"], factories.match_payload(predecessor["id"]), headers
        ),
        api_errors.ERR_TRANSFER_INVALID_STATE,
        409,
    )
    validate_error(
        client.receive_transfer_request(request["id"], headers),
        api_errors.ERR_TRANSFER_INVALID_STATE,
        409,
    )
    validate_error(
        client.reconcile_transfer_request(request["id"], headers),
        api_errors.ERR_TRANSFER_INVALID_STATE,
        409,
    )

    settled = validate_success(client.get_transfer_request(request["id"], headers), 200)
    assert_int_equals(settled["status"], TRANSFER_REJECTED, "request.status")
    assert_decimal_equals(
        settled["applied_transferred_credits"],
        "0.00",
        "request.applied_transferred_credits",
    )
    assert_student_ledgers(
        fixtures.read_student(client, newcomer["id"]), transferred="0.00", awarded="0.00"
    )


def test_second_certificate_submit_hits_the_duplicate_active_coe_guard(client):
    """The duplicate guard bites at submit, and invalidating the sibling clears it.

    "Finally, no sibling certificate for the same pairing of `student_id` and `move_id` may sit
    in `SUBMITTED`, `QC_SELECTED`, `QC_PASSED` or `APPROVED`; a second live certificate over
    the same move is refused with `ERR_DUPLICATE_ACTIVE_COE`."

    Design: Corner/errors/corner_second_certificate_submit_hits_the_duplicate_active_coe_guard
    """
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    recruiter_id = bundle.recruiter["id"]
    student_id = bundle.student["id"]
    assert_int_equals(bundle.coe["status"], COE_APPROVED, "first certificate.status")

    # The guard is keyed on "the same pairing of `student_id` and `move_id`", so the
    # sibling certificate has to rest on the very move the approved one rests on.
    second = fixtures.draft_coe(
        client,
        recruiter_id,
        student_id,
        bundle.move["id"],
        residency_date="2026-07-20",
        qc_hold_exempt=True,
    )
    assert_int_equals(second["status"], COE_DRAFT, "second certificate.status")

    validate_error(
        client.submit_coe(second["id"], make_recruiter_headers(recruiter_id)),
        api_errors.ERR_DUPLICATE_ACTIVE_COE,
        409,
    )
    blocked = fixtures.read_coe(client, second["id"])
    assert_int_equals(blocked["status"], COE_DRAFT, "second certificate.status")
    assert_is_null(
        blocked["provisional_eligibility_end_on"],
        "second certificate.provisional_eligibility_end_on",
    )

    invalidated = validate_success(
        client.invalidate_coe(
            bundle.coe["id"],
            factories.invalidate_payload("Superseded by a later qualifying move."),
            make_admin_headers(),
        ),
        200,
    )
    assert_int_equals(invalidated["status"], COE_INVALIDATED, "first certificate.status")

    submitted = validate_success(
        client.submit_coe(second["id"], make_recruiter_headers(recruiter_id)), 200
    )
    assert_int_equals(submitted["status"], COE_SUBMITTED, "second certificate.status")
    assert_date_equals(
        submitted["provisional_eligibility_end_on"],
        "2029-06-14",
        "second certificate.provisional_eligibility_end_on",
    )
    assert_int_equals(
        fixtures.read_student(client, student_id)["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )


def test_credits_are_refused_on_a_non_credit_accrual_plan(client):
    """Dropping the credit figure turns the refusal into an accepted hours-only session.

    "Credits are permitted only on a `CREDIT_ACCRUAL` plan: any `credits_awarded` greater than
    0.00 against a `SUPPLEMENTAL_INSTRUCTION`, `SUMMER_PROGRAM` or `OSY_ALTERNATIVE` plan is
    refused with `ERR_CREDITS_NOT_ALLOWED_FOR_PLAN_TYPE`."

    Design: Corner/errors/corner_credits_are_refused_on_a_non_credit_accrual_plan
    """
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    plan = fixtures.active_plan(
        client, bundle.student["id"], plan_type=PLAN_TYPE_SUPPLEMENTAL
    )
    session = factories.delivery_payload(
        plan["id"],
        delivered_on="2026-08-01",
        hours=1.50,
        service_category=SERVICE_CATEGORY_INSTRUCTION,
    )

    validate_error(
        client.create_delivery(
            dict(session, credits_awarded=0.50), make_coordinator_headers()
        ),
        api_errors.ERR_CREDITS_NOT_ALLOWED_FOR_PLAN_TYPE,
        422,
    )
    rows, _meta = fixtures.list_rows(
        client.list_deliveries(make_coordinator_headers(), {"plan_id": plan["id"]})
    )
    assert_row_count(rows, 0, "delivery records after the refusal")
    assert_decimal_equals(
        fixtures.read_plan(client, plan["id"])["delivered_hours"],
        "0.00",
        "plan.delivered_hours",
    )

    posted = validate_success(
        client.create_delivery(session, make_coordinator_headers()), 201
    )
    assert_decimal_equals(posted["hours"], "1.50", "delivery.hours")
    assert_int_equals(
        posted["service_category"], SERVICE_CATEGORY_INSTRUCTION, "delivery.service_category"
    )
    assert_decimal_equals(posted["credits_awarded"], "0.00", "delivery.credits_awarded")

    assert_decimal_equals(
        fixtures.read_plan(client, plan["id"])["delivered_hours"],
        "1.50",
        "plan.delivered_hours",
    )
    assert_student_ledgers(
        fixtures.read_student(client, bundle.student["id"]),
        hours="1.50",
        locally="0.00",
        awarded="0.00",
    )


def test_plan_type_must_agree_with_the_schooling_status(client):
    """Two mirror-image gates read the live schooling status, and refusals cost no version.

    "Two plan types are gated on the child's `schooling_status`: an `OSY_ALTERNATIVE` plan
    requires `OUT_OF_SCHOOL` and is otherwise refused with
    `ERR_OSY_PLAN_REQUIRES_OUT_OF_SCHOOL`, while a `SUPPLEMENTAL_INSTRUCTION` plan requires
    `ENROLLED` and is otherwise refused with `ERR_SUPPLEMENTAL_REQUIRES_ENROLLED`."

    Design: Corner/errors/corner_plan_type_must_agree_with_the_schooling_status
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(
        client, base.recruiter["id"], base.area["id"], grade_level=9
    )
    first_version = student["version"]

    validate_error(
        client.create_plan(
            factories.plan_payload(
                student["id"],
                first_version,
                plan_type=PLAN_TYPE_OSY_ALTERNATIVE,
                delivery_mode=DELIVERY_MODE_WORKSITE,
            ),
            make_coordinator_headers(),
        ),
        api_errors.ERR_OSY_PLAN_REQUIRES_OUT_OF_SCHOOL,
        422,
    )
    rows, _meta = fixtures.list_rows(
        client.list_plans(make_coordinator_headers(), {"student_id": student["id"]})
    )
    assert_row_count(rows, 0, "plans drafted for the enrolled child")
    assert_version_unchanged(
        fixtures.read_student(client, student["id"]), first_version, "student"
    )

    amended = validate_success(
        client.patch_student(
            student["id"],
            {
                "schooling_status": SCHOOLING_OUT_OF_SCHOOL,
                "has_hs_credential": False,
                "primary_language_not_english": True,
            },
            make_coordinator_headers(),
        ),
        200,
    )
    assert_int_equals(
        amended["schooling_status"], SCHOOLING_OUT_OF_SCHOOL, "student.schooling_status"
    )
    assert_int_equals(
        amended["pfs_variant"], PFS_VARIANT_OSY_PATHWAY, "student.pfs_variant"
    )
    assert_version_advanced_by(amended, first_version, 1, "student")
    second_version = amended["version"]

    validate_error(
        client.create_plan(
            factories.plan_payload(
                student["id"],
                second_version,
                plan_type=PLAN_TYPE_SUPPLEMENTAL,
                delivery_mode=DELIVERY_MODE_IN_PERSON,
            ),
            make_coordinator_headers(),
        ),
        api_errors.ERR_SUPPLEMENTAL_REQUIRES_ENROLLED,
        422,
    )
    assert_version_unchanged(
        fixtures.read_student(client, student["id"]), second_version, "student"
    )

    drafted = validate_success(
        client.create_plan(
            factories.plan_payload(
                student["id"],
                second_version,
                plan_type=PLAN_TYPE_OSY_ALTERNATIVE,
                delivery_mode=DELIVERY_MODE_WORKSITE,
            ),
            make_coordinator_headers(),
        ),
        201,
    )
    assert_int_equals(drafted["plan_type"], PLAN_TYPE_OSY_ALTERNATIVE, "plan.plan_type")
    assert_int_equals(
        drafted["delivery_mode"], DELIVERY_MODE_WORKSITE, "plan.delivery_mode"
    )
    assert_int_equals(drafted["status"], PLAN_DRAFT, "plan.status")

    child = fixtures.read_student(client, student["id"])
    assert_int_equals(
        child["service_status"], SERVICE_STATUS_PLAN_DRAFTED, "student.service_status"
    )
    assert_version_advanced_by(child, second_version, 1, "student")
