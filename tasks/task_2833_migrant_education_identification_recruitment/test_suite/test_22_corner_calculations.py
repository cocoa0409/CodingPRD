"""Computed figures: sample ranking, scoring input sets, the age-out clip and the sweep."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_assessment_components,
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
    assert_pfs_triple,
    assert_row_count,
)
from test_helpers.constants import (
    CLOSURE_REASON_REIDENTIFICATION_LAPSED,
    COE_APPROVED,
    COE_QC_SELECTED,
    COE_SUBMITTED,
    DECISION_REJECTED,
    ELIGIBILITY_ELIGIBLE,
    ELIGIBILITY_TERM_EXPIRED,
    PFS_VARIANT_INTERRUPTION_WEIGHTED,
    PLAN_CLOSED,
    PLAN_DRAFT,
    REVIEW_OPEN,
    SELECTION_REASON_MANDATORY,
    SERVICE_STATUS_EXITED,
    TERM_ACTIVE,
    TERM_EXPIRED,
    TERM_LAPSED,
    WORKER_RELATIONSHIP_SELF,
    WORK_TYPE_FISHING,
)
from test_helpers.test_users import make_admin_headers


def test_qc_selection_computes_candidate_count_target_n_and_ranking(client):
    """Two eligible candidates give a target of one, and the flagged one takes the slot.

    "The quota target, reported as `target_n`, is one tenth of the candidate count rounded
    **up** to the next whole number, or 1, whichever is larger - so a pool of a single
    candidate has a target of 1, a pool of ten has a target of 1, and a pool of eleven has a
    target of 2. The candidates are then ranked by `risk_flag_count` descending, ties broken
    by `created_at` ascending, and the first `target_n` of that ranking are taken."

    Design: Corner/calculations/corner_qc_selection_computes_candidate_count_target_n_and_ranking
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    area_id = base.area["id"]

    def submitted(name, work_type, residency_date, exempt):
        student = fixtures.create_student(
            client, recruiter_id, area_id, full_name=name
        )
        move = fixtures.verified_move(
            client,
            recruiter_id,
            student["id"],
            work_type=work_type,
            worker_relationship=WORKER_RELATIONSHIP_SELF,
        )
        fixtures.file_interview(client, recruiter_id, student["id"], move["id"])
        coe = fixtures.draft_coe(
            client,
            recruiter_id,
            student["id"],
            move["id"],
            residency_date=residency_date,
            qc_hold_exempt=exempt,
        )
        return fixtures.submit_coe(client, recruiter_id, coe["id"])

    clean = submitted("Student A", "AGRICULTURAL", "2026-07-01", False)
    flagged = submitted("Student B", WORK_TYPE_FISHING, "2026-07-02", False)
    exempt = submitted("Student C", "AGRICULTURAL", "2026-07-03", True)
    assert_int_equals(clean["risk_flag_count"], 0, "clean certificate.risk_flag_count")
    assert_int_equals(flagged["risk_flag_count"], 1, "flagged certificate.risk_flag_count")

    run = validate_success(client.run_qc_selection(make_admin_headers()), 201)

    assert_int_equals(run["candidate_count"], 2, "run.candidate_count")
    assert_int_equals(run["target_n"], 1, "run.target_n")
    assert_int_equals(run["selected_count"], 1, "run.selected_count")
    assert_int_equals(run["selected_coe_ids"], [flagged["id"]], "run.selected_coe_ids")
    assert_row_count(run["review_ids"], 1, "minted review identifiers")

    review = fixtures.read_qc_review(client, run["review_ids"][0])
    assert_int_equals(review["coe_id"], flagged["id"], "review.coe_id")
    assert_int_equals(review["status"], REVIEW_OPEN, "review.status")
    assert_int_equals(
        review["selection_reason"], SELECTION_REASON_MANDATORY, "review.selection_reason"
    )
    assert_is_null(review["decided_on"], "review.decided_on")

    assert_int_equals(
        fixtures.read_coe(client, flagged["id"])["status"],
        COE_QC_SELECTED,
        "flagged certificate.status",
    )
    assert_int_equals(
        fixtures.read_coe(client, clean["id"])["status"],
        COE_SUBMITTED,
        "clean certificate.status",
    )
    assert_int_equals(
        fixtures.read_coe(client, exempt["id"])["status"],
        COE_SUBMITTED,
        "exempt certificate.status",
    )

    rows, _meta = fixtures.list_rows(client.list_qc_reviews(make_admin_headers()))
    assert_row_count(rows, 1, "quality-control review rows in the service")


def test_pfs_move_band_counts_only_verified_moves(client):
    """Recorded and rejected moves contribute nothing, so the band stays at zero.

    "Count the child's qualifying moves that are in `VERIFIED` status and whose `move_date`
    falls within the 365-day window ending on the logical clock date, inclusive at both ends
    - a move dated exactly 365 days before the clock counts, and so does one dated on the
    clock date itself. Moves in `RECORDED` or `REJECTED` status never count."

    Design: Corner/calculations/corner_pfs_move_band_counts_only_verified_moves
    """
    base = fixtures.area_and_recruiter(client)
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(
        client,
        recruiter_id,
        base.area["id"],
        school_days_interrupted=5,
        credit_deficit=3,
        math_below_grade=True,
        reading_below_grade=True,
    )
    fixtures.create_move(client, recruiter_id, student["id"])
    rejected = fixtures.create_move(
        client, recruiter_id, student["id"], move_date="2026-06-20"
    )
    fixtures.adjudicate_move(client, rejected["id"], DECISION_REJECTED)
    third = fixtures.create_move(
        client, recruiter_id, student["id"], move_date="2026-07-05"
    )

    first = fixtures.read_assessment(client, student["id"])
    assert_assessment_components(
        first,
        recent_verified_moves=0,
        move_band_points=0,
        interruption_points=4,
        academic_points=28,
        credit_points=9,
        raw_score=41,
        floor_applied=False,
    )
    assert_pfs_triple(
        first, PFS_VARIANT_INTERRUPTION_WEIGHTED, 41, False, "first assessment"
    )

    fixtures.adjudicate_move(client, third["id"])

    second = fixtures.read_assessment(client, student["id"])
    assert_assessment_components(
        second,
        recent_verified_moves=1,
        move_band_points=18,
        interruption_points=4,
        academic_points=28,
        credit_points=9,
        raw_score=59,
        floor_applied=False,
    )
    assert_pfs_triple(
        second, PFS_VARIANT_INTERRUPTION_WEIGHTED, 59, False, "second assessment"
    )


def test_age_out_constant_clips_the_final_eligibility_window(client):
    """The day before the twenty-second birthday beats the thirty-six-month date.

    "The age-out cap is obtained by adding 22 years to the child's `birth_date` and stepping
    back one day - the day before the child's twenty-second birthday. `eligibility_end_on` is
    whichever of those two dates is earlier, and `age_out_capped` is true exactly when the
    age-out date is strictly earlier than the uncapped end, and false when the two coincide
    or the uncapped end comes first."

    Design: Corner/calculations/corner_age_out_constant_clips_the_final_eligibility_window
    """
    bundle = fixtures.submitted_certificate(
        client,
        coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True},
        full_name="Elena Cruz",
        birth_date="2007-05-20",
        grade_level=12,
    )
    assert_int_equals(bundle.move["student_age_at_move"], 19, "move.student_age_at_move")
    assert_date_equals(
        bundle.coe["provisional_eligibility_end_on"],
        "2029-06-14",
        "coe.provisional_eligibility_end_on",
    )

    approved = fixtures.approve_coe(client, bundle.coe["id"])

    assert_int_equals(approved["status"], COE_APPROVED, "coe.status")
    assert_date_equals(
        approved["eligibility_start_on"], "2026-07-01", "coe.eligibility_start_on"
    )
    assert_date_equals(
        approved["eligibility_end_on"], "2029-05-19", "coe.eligibility_end_on"
    )
    assert_int_equals(approved["age_out_capped"], True, "coe.age_out_capped")

    term = fixtures.only_term_for(client, bundle.student["id"])
    assert_date_equals(term["term_start_on"], "2026-07-01", "term.term_start_on")
    assert_date_equals(term["term_end_on"], "2029-05-19", "term.term_end_on")

    child = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        child["eligibility_status"], ELIGIBILITY_ELIGIBLE, "student.eligibility_status"
    )
    assert_date_equals(
        child["eligibility_expires_on"], "2029-05-19", "student.eligibility_expires_on"
    )


def test_term_sweep_advances_one_step_per_call(client):
    """Both tests are already true, yet the term needs two calls to reach LAPSED.

    "Each term in the batch advances **at most one** status per call, and the three branches
    are evaluated in a fixed order against the logical clock date." "The third branch handles
    the lapse, `EXPIRED -> LAPSED`: when a term is `EXPIRED` and the clock date is strictly
    later than its `reidentification_due_on`, the grace period has closed and the term
    becomes `LAPSED`."

    Design: Corner/calculations/corner_term_sweep_advances_one_step_per_call
    """
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    plan = fixtures.draft_plan(client, bundle.student["id"])
    term_id = bundle.term["id"]
    assert_int_equals(bundle.term["status"], TERM_ACTIVE, "term.status")
    assert_date_equals(bundle.term["term_end_on"], "2029-06-30", "term.term_end_on")
    assert_is_null(bundle.term["reidentification_due_on"], "term.reidentification_due_on")

    fixtures.set_clock(client, "2029-09-01T00:00:00Z")

    first = fixtures.sweep(client)
    assert_int_equals(first["swept_count"], 1, "first sweep.swept_count")
    assert_int_equals(first["expiring_count"], 0, "first sweep.expiring_count")
    assert_int_equals(first["expired_count"], 1, "first sweep.expired_count")
    assert_int_equals(first["lapsed_count"], 0, "first sweep.lapsed_count")
    assert_int_equals(first["expired_term_ids"], [term_id], "first sweep.expired_term_ids")

    expired = fixtures.read_term(client, term_id)
    assert_int_equals(expired["status"], TERM_EXPIRED, "term.status")
    assert_date_equals(
        expired["reidentification_due_on"], "2029-08-14", "term.reidentification_due_on"
    )
    midway_child = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        midway_child["eligibility_status"],
        ELIGIBILITY_TERM_EXPIRED,
        "student.eligibility_status",
    )
    assert_is_null(
        midway_child["eligibility_expires_on"], "student.eligibility_expires_on"
    )
    midway_plan = fixtures.read_plan(client, plan["id"])
    assert_int_equals(midway_plan["status"], PLAN_DRAFT, "plan.status")
    assert_is_null(midway_plan["closure_reason"], "plan.closure_reason")

    second = fixtures.sweep(client)
    assert_int_equals(second["swept_count"], 1, "second sweep.swept_count")
    assert_int_equals(second["expired_count"], 0, "second sweep.expired_count")
    assert_int_equals(second["lapsed_count"], 1, "second sweep.lapsed_count")
    assert_int_equals(second["expired_term_ids"], [], "second sweep.expired_term_ids")

    assert_int_equals(fixtures.read_term(client, term_id)["status"], TERM_LAPSED, "term.status")
    closed = fixtures.read_plan(client, plan["id"])
    assert_int_equals(closed["status"], PLAN_CLOSED, "plan.status")
    assert_int_equals(
        closed["closure_reason"],
        CLOSURE_REASON_REIDENTIFICATION_LAPSED,
        "plan.closure_reason",
    )
    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["service_status"],
        SERVICE_STATUS_EXITED,
        "student.service_status",
    )
