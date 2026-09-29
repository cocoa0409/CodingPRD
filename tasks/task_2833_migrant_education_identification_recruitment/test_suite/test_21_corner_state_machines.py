"""Declared initial states, repeated-transition refusals and the two independent dimensions."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_decimal_equals,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
    assert_plan_allocation,
    assert_row_count,
    assert_student_ledgers,
    assert_version,
    assert_version_advanced_by,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    CLOCK_START_INSTANT,
    COE_DRAFT,
    COE_INVALIDATED,
    COE_SUBMITTED,
    CLOSURE_REASON_SUPERSEDED,
    DECISION_VERIFIED,
    DELIVERY_MODE_VIRTUAL,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_NOT_ELIGIBLE,
    ELIGIBILITY_PENDING_DETERMINATION,
    MOVE_STATUS_RECORDED,
    MOVE_STATUS_VERIFIED,
    OUTCOME_INCONCLUSIVE,
    OUTCOME_SUPPORTS,
    PLAN_DRAFT,
    PLAN_SUPERSEDED,
    PRIORITY_TIER_NON_PFS,
    SERVICE_STATUS_PLAN_DRAFTED,
    SERVICE_STATUS_RECEIVING_SERVICES,
    SERVICE_STATUS_UNSERVED,
    TERM_ACTIVE,
    TRANSFER_INITIATED,
    TRANSFER_RECONCILED,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_liaison_headers,
    make_recruiter_headers,
)


def test_new_rows_start_in_their_declared_initial_state(client):
    """Five freshly created rows each read the initial state their own rule declares.

    "A newly identified child therefore reads `NOT_ELIGIBLE` and `UNSERVED` simultaneously,
    and each dimension advances on its own triggers - a child can be `RECEIVING_SERVICES`
    while their eligibility reads `CONTINUATION`, and the two are never reconciled against
    each other." "A new assignment always begins in `PLANNED` status, and `cancelled_reason`
    - a free-text field of up to 240 characters - starts null." "A new request begins in
    `INITIATED` status with `matched_prior_student_id` null, `applied_transferred_credits`
    at 0.00 and `rejection_reason` null."

    Design: Corner/state_machines/corner_new_rows_start_in_their_declared_initial_state
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]

    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    assert_int_equals(
        student["eligibility_status"], ELIGIBILITY_NOT_ELIGIBLE, "student.eligibility_status"
    )
    assert_int_equals(
        student["service_status"], SERVICE_STATUS_UNSERVED, "student.service_status"
    )

    move = fixtures.create_move(client, recruiter_id, student["id"])
    assert_int_equals(move["status"], MOVE_STATUS_RECORDED, "move.status")
    assert_is_null(move["adjudicated_on"], "move.adjudicated_on")

    coe = fixtures.draft_coe(client, recruiter_id, student["id"], move["id"])
    assert_int_equals(coe["status"], COE_DRAFT, "coe.status")
    assert_int_equals(coe["correction_round_count"], 0, "coe.correction_round_count")
    assert_int_equals(coe["risk_flag_count"], 0, "coe.risk_flag_count")
    assert_is_null(coe["provisional_eligibility_end_on"], "coe.provisional_eligibility_end_on")
    assert_is_null(coe["invalidation_reason"], "coe.invalidation_reason")

    assignment = fixtures.create_assignment(client, recruiter_id, base.area["id"])
    assert_int_equals(assignment["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
    assert_is_null(assignment["cancelled_reason"], "assignment.cancelled_reason")

    request = fixtures.open_transfer_request(client, student["id"])
    assert_int_equals(request["status"], TRANSFER_INITIATED, "request.status")
    assert_is_null(request["matched_prior_student_id"], "request.matched_prior_student_id")
    assert_decimal_equals(
        request["applied_transferred_credits"], "0.00", "request.applied_transferred_credits"
    )
    assert_is_null(request["rejection_reason"], "request.rejection_reason")


def test_adjudicating_an_already_verified_move_returns_move_already_adjudicated(client):
    """The second adjudication is refused and leaves the first decision's stamp intact.

    "The payload carries a single `decision`, either `VERIFIED` or `REJECTED`, and the move
    must still be `RECORDED` - a second adjudication of the same move, whether it landed on
    `VERIFIED` or `REJECTED`, is refused with `ERR_MOVE_ALREADY_ADJUDICATED`." "An accepted
    adjudication moves the move `RECORDED -> VERIFIED` or `RECORDED -> REJECTED` and stamps
    `adjudicated_on` with the logical clock instant."

    Design: Corner/state_machines/corner_adjudicating_an_already_verified_move_returns_move_already_adjudicated
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    move = fixtures.create_move(client, recruiter_id, student["id"])

    verified = validate_success(
        client.adjudicate_move(
            move["id"], factories.adjudicate_payload(DECISION_VERIFIED), make_admin_headers()
        ),
        200,
    )
    assert_int_equals(verified["status"], MOVE_STATUS_VERIFIED, "move.status")
    assert_instant_equals(
        verified["adjudicated_on"], CLOCK_START_INSTANT, "move.adjudicated_on"
    )

    response = client.adjudicate_move(
        move["id"], factories.adjudicate_payload(DECISION_VERIFIED), make_admin_headers()
    )
    validate_error(response, api_errors.ERR_MOVE_ALREADY_ADJUDICATED, 409)

    frozen = validate_success(client.get_move(move["id"], make_admin_headers()), 200)
    assert_int_equals(frozen["status"], MOVE_STATUS_VERIFIED, "move.status")
    assert_instant_equals(
        frozen["adjudicated_on"], CLOCK_START_INSTANT, "move.adjudicated_on"
    )
    assert_version_unchanged(frozen, verified["version"], "move")


def test_approving_a_draft_certificate_returns_coe_invalid_state(client):
    """Approval is unavailable from DRAFT, so no term and no eligibility appears.

    "From anywhere else, including `DRAFT`, `QC_SELECTED`, `RETURNED_FOR_CORRECTION`,
    `APPROVED` or `INVALIDATED`, the attempt is refused with `ERR_COE_INVALID_STATE`."

    Design: Corner/state_machines/corner_approving_a_draft_coe_returns_coe_invalid_state
    """
    bundle = fixtures.identified_child(client)
    coe = fixtures.draft_coe(
        client, bundle.recruiter["id"], bundle.student["id"], bundle.move["id"]
    )

    response = client.approve_coe(coe["id"], make_admin_headers())
    validate_error(response, api_errors.ERR_COE_INVALID_STATE, 409)

    frozen = validate_success(client.get_coe(coe["id"], make_admin_headers()), 200)
    assert_int_equals(frozen["status"], COE_DRAFT, "coe.status")
    for field in (
        "provisional_eligibility_end_on",
        "eligibility_start_on",
        "eligibility_end_on",
        "age_out_capped",
    ):
        assert_is_null(frozen[field], "coe." + field)
    assert_version_unchanged(frozen, coe["version"], "coe")

    terms, _meta = fixtures.list_rows(
        client.list_terms(make_admin_headers(), {"student_id": bundle.student["id"]})
    )
    assert_row_count(terms, 0, "eligibility terms for the child")
    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["eligibility_status"],
        ELIGIBILITY_NOT_ELIGIBLE,
        "student.eligibility_status",
    )


def test_invalidating_an_invalidated_certificate_returns_coe_invalid_state(client):
    """INVALIDATED is terminal, and every later write against it reports its own code.

    "**Invalidation** is the destructive counterpart, reserved to the state office and
    available only from `APPROVED`; from any other status it is refused with
    `ERR_COE_INVALID_STATE`." "From any other status the correction is refused with
    `ERR_COE_NOT_IN_DRAFT`."

    Design: Corner/state_machines/corner_invalidating_an_invalidated_coe_returns_coe_invalid_state
    """
    bundle = fixtures.certified_child(client)
    invalidated = validate_success(
        client.invalidate_coe(
            bundle.coe["id"], factories.invalidate_payload(), make_admin_headers()
        ),
        200,
    )
    assert_int_equals(invalidated["status"], COE_INVALIDATED, "coe.status")

    validate_error(
        client.invalidate_coe(
            bundle.coe["id"], factories.invalidate_payload(), make_admin_headers()
        ),
        api_errors.ERR_COE_INVALID_STATE,
        409,
    )
    validate_error(
        client.submit_coe(
            bundle.coe["id"], make_recruiter_headers(bundle.recruiter["id"])
        ),
        api_errors.ERR_COE_NOT_IN_DRAFT,
        409,
    )
    validate_error(
        client.patch_coe(
            bundle.coe["id"],
            {"residency_date": "2026-07-15"},
            make_recruiter_headers(bundle.recruiter["id"]),
        ),
        api_errors.ERR_COE_NOT_IN_DRAFT,
        409,
    )

    frozen = validate_success(client.get_coe(bundle.coe["id"], make_admin_headers()), 200)
    assert_int_equals(frozen["status"], COE_INVALIDATED, "coe.status")
    assert_int_equals(
        frozen["invalidation_reason"],
        invalidated["invalidation_reason"],
        "coe.invalidation_reason",
    )
    assert_date_equals(
        frozen["residency_date"], invalidated["residency_date"], "coe.residency_date"
    )
    assert_version_unchanged(frozen, invalidated["version"], "coe")


def test_certificate_submit_without_a_supporting_initial_interview_is_refused(client):
    """An inconclusive initial interview does not document eligibility, but it does flag risk.

    "At least one interview record must exist for the same `student_id` and `move_id` whose
    `interview_kind` is `INITIAL` and whose `outcome` is `SUPPORTS_ELIGIBILITY` - an
    `INCONCLUSIVE` or `CONTRADICTS_ELIGIBILITY` initial interview does not satisfy this, and
    a certificate without qualifying documentation is refused with
    `ERR_INTERVIEW_DOCUMENTATION_MISSING`."

    Design: Corner/state_machines/corner_coe_submit_without_a_supporting_initial_interview_is_refused
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    move = fixtures.verified_move(client, recruiter_id, student["id"])
    fixtures.file_interview(
        client, recruiter_id, student["id"], move["id"], outcome=OUTCOME_INCONCLUSIVE
    )
    coe = fixtures.draft_coe(client, recruiter_id, student["id"], move["id"])

    refused = client.submit_coe(coe["id"], make_recruiter_headers(recruiter_id))
    validate_error(refused, api_errors.ERR_INTERVIEW_DOCUMENTATION_MISSING, 409)
    assert_int_equals(
        validate_success(client.get_coe(coe["id"], make_admin_headers()), 200)["status"],
        COE_DRAFT,
        "coe.status",
    )

    fixtures.file_interview(
        client, recruiter_id, student["id"], move["id"], outcome=OUTCOME_SUPPORTS
    )
    submitted = validate_success(
        client.submit_coe(coe["id"], make_recruiter_headers(recruiter_id)), 200
    )

    assert_int_equals(submitted["status"], COE_SUBMITTED, "coe.status")
    assert_date_equals(
        submitted["provisional_eligibility_end_on"],
        "2029-06-14",
        "coe.provisional_eligibility_end_on",
    )
    assert_int_equals(submitted["risk_flag_count"], 1, "coe.risk_flag_count")
    assert_int_equals(
        fixtures.read_student(client, student["id"])["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )


def test_creating_a_second_plan_of_the_same_type_supersedes_the_first(client):
    """The older plan is closed out as SUPERSEDED and keeps the hours it last held.

    "If that child already holds a plan of the same `plan_type` in `DRAFT` or `ACTIVE`
    status, that older plan moves `DRAFT -> SUPERSEDED` or `ACTIVE -> SUPERSEDED`, its
    `closure_reason` is set to `SUPERSEDED`, its `superseded_by_plan_id` is pointed at the
    new plan's `id`, and its `version` is incremented by 1."

    Design: Corner/state_machines/corner_creating_a_second_plan_of_the_same_type_supersedes_the_first
    """
    base = fixtures.area_and_recruiter(client)
    student = fixtures.create_student(client, base.recruiter["id"], base.area["id"])
    first = fixtures.draft_plan(client, student["id"])
    assert_plan_allocation(first, PRIORITY_TIER_NON_PFS, "75.00", "first plan")
    before = fixtures.read_student(client, student["id"])

    second = fixtures.draft_plan(
        client, student["id"], delivery_mode=DELIVERY_MODE_VIRTUAL
    )

    assert_int_equals(second["status"], PLAN_DRAFT, "second plan.status")
    assert_int_equals(
        second["delivery_mode"], DELIVERY_MODE_VIRTUAL, "second plan.delivery_mode"
    )
    assert_plan_allocation(second, PRIORITY_TIER_NON_PFS, "75.00", "second plan")
    assert_is_null(second["superseded_by_plan_id"], "second plan.superseded_by_plan_id")

    displaced = fixtures.read_plan(client, first["id"])
    assert_int_equals(displaced["status"], PLAN_SUPERSEDED, "first plan.status")
    assert_int_equals(
        displaced["closure_reason"], CLOSURE_REASON_SUPERSEDED, "first plan.closure_reason"
    )
    assert_int_equals(
        displaced["superseded_by_plan_id"], second["id"], "first plan.superseded_by_plan_id"
    )
    assert_decimal_equals(displaced["allocated_hours"], "75.00", "first plan.allocated_hours")
    assert_version_advanced_by(displaced, first["version"], 1, "first plan")

    after = fixtures.read_student(client, student["id"])
    assert_int_equals(
        after["service_status"], SERVICE_STATUS_PLAN_DRAFTED, "student.service_status"
    )
    assert_version_advanced_by(after, before["version"], 1, "student")

    rows, _meta = fixtures.list_rows(
        client.list_plans(make_admin_headers(), {"superseded_by_plan_id": second["id"]})
    )
    assert_row_count(rows, 1, "plans displaced by the newer plan")
    assert_int_equals(rows[0]["id"], first["id"], "displaced plan.id")


def test_transfer_reconcile_syncs_the_student_credit_ledger(client):
    """A pre-cap key of 10.00 admits fifty percent, so 10.00 reported credits land as 5.00.

    "**Fourth**, the cap percentage is chosen as the highest tier whose floor the key
    reaches - a key below 12.00 credits admits 50 percent, a key of at least 12.00 but below
    24.00 admits 35 percent, and a key of 24.00 or more admits 25 percent. **Fifth**, the
    accepted transfer is the smaller of the uncapped amount and the cap percentage applied
    to the tier key, rounded half up to two decimals."

    Design: Corner/state_machines/corner_transfer_reconcile_syncs_the_student_credit_ledger
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    predecessor = fixtures.create_student(
        client, recruiter_id, base.area["id"], full_name="Ana Solis"
    )
    arriving = fixtures.create_student(
        client, recruiter_id, base.area["id"], full_name="Mateo Reyes"
    )

    request = fixtures.open_transfer_request(
        client, arriving["id"], reported_prior_credits=10.00
    )
    fixtures.carry_transfer_to_received(client, request["id"], predecessor["id"])

    reconciled = validate_success(
        client.reconcile_transfer_request(request["id"], make_liaison_headers()), 200
    )
    assert_int_equals(reconciled["status"], TRANSFER_RECONCILED, "request.status")
    assert_decimal_equals(
        reconciled["applied_transferred_credits"],
        "5.00",
        "request.applied_transferred_credits",
    )

    child = fixtures.read_student(client, arriving["id"])
    assert_student_ledgers(
        child, hours="0.00", transferred="5.00", locally="0.00", awarded="5.00"
    )
    assert_student_ledgers(
        fixtures.read_student(client, predecessor["id"]),
        hours="0.00",
        transferred="0.00",
        locally="0.00",
        awarded="0.00",
    )


def test_student_eligibility_and_service_dimensions_advance_independently(client):
    """Four writes move one dimension each, never both, and never read one another.

    "A child's record carries **two independent state dimensions on the same row**, and they
    never read each other." "A newly identified child therefore reads `NOT_ELIGIBLE` and
    `UNSERVED` simultaneously, and each dimension advances on its own triggers - a child can
    be `RECEIVING_SERVICES` while their eligibility reads `CONTINUATION`, and the two are
    never reconciled against each other."

    Design: Corner/state_machines/corner_student_eligibility_and_service_dimensions_advance_independently
    """
    bundle = fixtures.identified_child(client)
    recruiter_id = bundle.recruiter["id"]
    student_id = bundle.student["id"]

    def dimensions():
        row = fixtures.read_student(client, student_id)
        return row["eligibility_status"], row["service_status"]

    assert_int_equals(
        dimensions(),
        (ELIGIBILITY_NOT_ELIGIBLE, SERVICE_STATUS_UNSERVED),
        "dimensions at identification",
    )

    plan = fixtures.draft_plan(client, student_id)
    assert_int_equals(
        dimensions(),
        (ELIGIBILITY_NOT_ELIGIBLE, SERVICE_STATUS_PLAN_DRAFTED),
        "dimensions after the first draft plan",
    )

    coe = fixtures.draft_coe(client, recruiter_id, student_id, bundle.move["id"])
    fixtures.submit_coe(client, recruiter_id, coe["id"])
    assert_int_equals(
        dimensions(),
        (ELIGIBILITY_PENDING_DETERMINATION, SERVICE_STATUS_PLAN_DRAFTED),
        "dimensions after submission",
    )

    fixtures.approve_coe(client, coe["id"])
    assert_int_equals(
        dimensions(),
        (ELIGIBILITY_ELIGIBLE, SERVICE_STATUS_PLAN_DRAFTED),
        "dimensions after approval",
    )

    activated = fixtures.activate_plan(client, plan["id"])
    assert_int_equals(
        dimensions(),
        (ELIGIBILITY_ELIGIBLE, SERVICE_STATUS_RECEIVING_SERVICES),
        "dimensions after activation",
    )

    final = fixtures.read_student(client, student_id)
    assert_date_equals(
        final["eligibility_expires_on"], "2029-06-30", "student.eligibility_expires_on"
    )
    term = fixtures.only_term_for(client, student_id)
    assert_int_equals(term["status"], TERM_ACTIVE, "term.status")
    assert_int_equals(
        fixtures.read_plan(client, activated["id"])["status"], "ACTIVE", "plan.status"
    )
