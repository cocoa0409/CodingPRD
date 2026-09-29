"""Two writes are gated on the state of a different entity than the one being written."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
)
from test_helpers.constants import (
    COE_DRAFT,
    COE_SUBMITTED,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_NOT_ELIGIBLE,
    ELIGIBILITY_PENDING_DETERMINATION,
    PLAN_ACTIVE,
    PLAN_DRAFT,
    SERVICE_STATUS_PLAN_DRAFTED,
    SERVICE_STATUS_RECEIVING_SERVICES,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_coordinator_headers,
    make_recruiter_headers,
)


# --------------------------------------------------------------------------------------
# Submission is gated on the linked move, not on the certificate.
# --------------------------------------------------------------------------------------
def _certificate_on_an_unverified_move(client):
    """A documented DRAFT certificate whose qualifying move is still merely RECORDED."""
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    move = fixtures.create_move(client, recruiter_id, student["id"])
    fixtures.file_interview(client, recruiter_id, student["id"], move["id"])
    coe = fixtures.draft_coe(
        client, recruiter_id, student["id"], move["id"], qc_hold_exempt=True
    )
    base.recruiter_id = recruiter_id
    base.student = student
    base.move = move
    base.coe = coe
    return base


def test_submission_is_refused_while_the_move_is_only_recorded(client):
    """The certificate is otherwise perfect, so the refusal comes from the move's state.

    "The linked qualifying move must already be in `VERIFIED` status - a move still
    `RECORDED`, or one adjudicated `REJECTED`, is refused with `ERR_MOVE_NOT_VERIFIED`."

    Design: Difficulty/cross_entity_state_dependency/coe_submit_is_blocked_until_the_referenced_move_is_verified
    """
    bundle = _certificate_on_an_unverified_move(client)

    response = client.submit_coe(
        bundle.coe["id"], make_recruiter_headers(bundle.recruiter_id)
    )
    validate_error(response, api_errors.ERR_MOVE_NOT_VERIFIED, 409)

    coe = validate_success(client.get_coe(bundle.coe["id"], make_admin_headers()), 200)
    assert_int_equals(coe["status"], COE_DRAFT, "certificate.status")
    assert_is_null(
        coe["provisional_eligibility_end_on"],
        "certificate.provisional_eligibility_end_on",
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_NOT_ELIGIBLE,
        "student.eligibility_status",
    )


def test_verifying_the_move_unblocks_the_identical_submission(client):
    """Adjudicating the sibling row is the only change, and the same call now succeeds.

    "Submission moves the certificate `DRAFT` -> `SUBMITTED` and is where the program's
    evidentiary discipline bites."

    Design: Difficulty/cross_entity_state_dependency/coe_submit_is_blocked_until_the_referenced_move_is_verified
    """
    bundle = _certificate_on_an_unverified_move(client)
    client.submit_coe(bundle.coe["id"], make_recruiter_headers(bundle.recruiter_id))

    fixtures.adjudicate_move(client, bundle.move["id"])

    submitted = validate_success(
        client.submit_coe(bundle.coe["id"], make_recruiter_headers(bundle.recruiter_id)),
        200,
    )
    assert_int_equals(submitted["status"], COE_SUBMITTED, "certificate.status")
    assert_date_equals(
        submitted["provisional_eligibility_end_on"],
        "2029-06-14",
        "certificate.provisional_eligibility_end_on",
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )


# --------------------------------------------------------------------------------------
# Plan activation is gated on the child's eligibility dimension, not on the plan.
# --------------------------------------------------------------------------------------
def _draft_plan_for_a_pending_child(client):
    """A DRAFT plan for a child whose certificate is submitted but not yet approved."""
    bundle = fixtures.submitted_certificate(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    bundle.plan = fixtures.draft_plan(client, bundle.student["id"])
    return bundle


def test_activation_is_refused_while_the_child_is_only_pending_determination(client):
    """The plan is in DRAFT and valid, so the refusal comes from the child's status.

    "A child reading `NOT_ELIGIBLE`, `PENDING_DETERMINATION` or `TERM_EXPIRED` blocks
    activation with `ERR_STUDENT_NOT_ELIGIBLE_FOR_SERVICES`, so a plan drafted in
    anticipation of certification cannot be activated until the approval cascade has run,
    and a plan whose child's term has since expired cannot be activated at all."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_is_blocked_until_the_student_reaches_an_eligible_status
    """
    bundle = _draft_plan_for_a_pending_child(client)
    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )

    response = client.activate_plan(bundle.plan["id"], make_coordinator_headers())
    validate_error(response, api_errors.ERR_STUDENT_NOT_ELIGIBLE_FOR_SERVICES, 409)

    plan = fixtures.read_plan(client, bundle.plan["id"])
    assert_int_equals(plan["status"], PLAN_DRAFT, "plan.status")
    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["service_status"],
        SERVICE_STATUS_PLAN_DRAFTED,
        "student.service_status",
    )


def test_approving_the_certificate_unblocks_the_identical_activation(client):
    """Once the cascade has made the child ELIGIBLE the same activation call succeeds.

    "An accepted activation drives `DRAFT` -> `ACTIVE`, increments the plan's `version`
    by 1, re-runs the allocation rule, and re-derives the child's `service_status`."

    Design: Difficulty/cross_entity_state_dependency/plan_activation_is_blocked_until_the_student_reaches_an_eligible_status
    """
    bundle = _draft_plan_for_a_pending_child(client)
    client.activate_plan(bundle.plan["id"], make_coordinator_headers())

    fixtures.approve_coe(client, bundle.coe["id"])
    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["eligibility_status"],
        ELIGIBILITY_ELIGIBLE,
        "student.eligibility_status",
    )

    activated = validate_success(
        client.activate_plan(bundle.plan["id"], make_coordinator_headers()), 200
    )
    assert_int_equals(activated["status"], PLAN_ACTIVE, "plan.status")

    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["service_status"],
        SERVICE_STATUS_RECEIVING_SERVICES,
        "student.service_status",
    )
