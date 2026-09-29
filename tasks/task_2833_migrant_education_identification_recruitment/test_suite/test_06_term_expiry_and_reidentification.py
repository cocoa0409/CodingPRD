"""Expiry and reidentification close the pending-determination cycle a second time."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
)
from test_helpers.constants import (
    COE_APPROVED,
    COE_DRAFT,
    ELIGIBILITY_PENDING_DETERMINATION,
    ELIGIBILITY_TERM_EXPIRED,
    TERM_EXPIRED,
    TERM_REIDENTIFIED,
    WORK_TYPE_FISHING,
)
from test_helpers.test_users import make_admin_headers, make_recruiter_headers


def _expired_term_with_a_new_move(client):
    """A certified child whose term has been swept to EXPIRED, plus a fresh VERIFIED move."""
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    fixtures.set_clock(client, "2029-07-05T00:00:00Z")
    bundle.sweep = fixtures.sweep(client)
    bundle.new_move = fixtures.verified_move(
        client,
        bundle.recruiter["id"],
        bundle.student["id"],
        from_state_code="OR",
        move_date="2029-07-01",
        work_type=WORK_TYPE_FISHING,
        distance_miles=240.75,
    )
    return bundle


def test_the_sweep_expires_the_term_and_opens_the_grace_period(client):
    """A clock past the inclusive last eligible day expires the term and dates the grace.

    "Entering `EXPIRED` writes `reidentification_due_on` as `term_end_on` plus
    forty-five days - the grace period during which the family can be reidentified -
    and drives the child's eligibility dimension to `TERM_EXPIRED` with
    `eligibility_expires_on` cleared to null."

    Design: Difficulty/non_linear_state_machine/student_term_expiry_and_reidentification_close_the_pending_determination_cycle
    """
    bundle = _expired_term_with_a_new_move(client)

    assert_int_equals(bundle.sweep["swept_count"], 1, "sweep.swept_count")
    assert_int_equals(bundle.sweep["expired_count"], 1, "sweep.expired_count")

    term = fixtures.only_term_for(client, bundle.student["id"])
    assert_int_equals(term["status"], TERM_EXPIRED, "term.status")
    assert_date_equals(term["term_start_on"], "2026-07-01", "term.term_start_on")
    assert_date_equals(term["term_end_on"], "2029-06-30", "term.term_end_on")
    assert_date_equals(
        term["reidentification_due_on"], "2029-08-14", "term.reidentification_due_on"
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student.eligibility_status",
    )
    assert_is_null(student["eligibility_expires_on"], "student.eligibility_expires_on")


def test_reidentification_mints_a_fresh_draft_certificate_on_the_new_move(client):
    """Reidentifying inside the grace period reopens the cycle at PENDING_DETERMINATION.

    "It mints a fresh certificate in `DRAFT` status for the same child on the new move,
    carrying the supplied `residency_date` and `initiating_recruiter_id` taken from
    `X-User-ID` - that certificate then walks the ordinary lifecycle of 3.5 from the
    beginning."

    Design: Difficulty/non_linear_state_machine/student_term_expiry_and_reidentification_close_the_pending_determination_cycle
    """
    bundle = _expired_term_with_a_new_move(client)
    term = fixtures.only_term_for(client, bundle.student["id"])
    recruiter_id = bundle.recruiter["id"]

    reidentified = validate_success(
        client.reidentify_term(
            term["id"],
            factories.reidentify_payload(bundle.new_move["id"], "2029-07-02"),
            make_recruiter_headers(recruiter_id),
        ),
        200,
    )

    assert_int_equals(reidentified["status"], TERM_REIDENTIFIED, "term.status")
    assert_int_equals(reidentified["id"], term["id"], "the response body is the term")

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )

    drafts, _meta = fixtures.list_rows(
        client.list_coes(
            make_admin_headers(),
            {"student_id": bundle.student["id"], "status": COE_DRAFT},
        )
    )
    assert_row_count(drafts, 1, "draft certificates for the child")
    fresh = drafts[0]
    assert_int_equals(fresh["move_id"], bundle.new_move["id"], "certificate.move_id")
    assert_date_equals(fresh["residency_date"], "2029-07-02", "certificate.residency_date")
    assert_int_equals(
        fresh["initiating_recruiter_id"],
        recruiter_id,
        "certificate.initiating_recruiter_id",
    )
    assert fresh["id"] != bundle.coe["id"], "reidentification must mint a new certificate"

    first = validate_success(client.get_coe(bundle.coe["id"], make_admin_headers()), 200)
    assert_int_equals(first["status"], COE_APPROVED, "the original certificate's status")

    newest, _meta = fixtures.list_rows(client.list_coes(make_admin_headers()))
    assert_int_equals(newest[0]["id"], fresh["id"], "the newest certificate listed first")
