"""A failed review sends a certificate back through draft and out again."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_instant_equals,
    assert_int_equals,
    assert_is_null,
)
from test_helpers.constants import (
    CLOCK_START_INSTANT,
    COE_DRAFT,
    COE_QC_SELECTED,
    COE_RETURNED_FOR_CORRECTION,
    COE_SUBMITTED,
    CREDENTIAL_QC_CERTIFIED,
    ELIGIBILITY_NOT_ELIGIBLE,
    ELIGIBILITY_PENDING_DETERMINATION,
    OUTCOME_CONTRADICTS,
    QC_DECISION_FAIL,
    REVIEW_FAILED,
    SELECTION_REASON_QUOTA,
)
from test_helpers.test_users import make_qc_reviewer_headers, make_recruiter_headers


def _selected_certificate(client):
    """A non-exempt SUBMITTED certificate drawn into an OPEN review with a re-interview."""
    base = fixtures.area_and_recruiter(client, area_overrides={"name": "Walla Walla Bench"})
    initiator = base.recruiter["id"]
    reviewer = fixtures.create_recruiter(
        client, full_name="Ken Ortiz", credential_level=CREDENTIAL_QC_CERTIFIED
    )["id"]

    student = fixtures.create_student(client, initiator, base.area["id"])
    move = fixtures.verified_move(client, initiator, student["id"])
    fixtures.file_interview(
        client,
        initiator,
        student["id"],
        move["id"],
        documentation_notes="Parent confirms onion harvest work.",
    )
    coe = fixtures.draft_coe(
        client,
        initiator,
        student["id"],
        move["id"],
        residency_date="2026-07-01",
        qc_hold_exempt=False,
    )
    fixtures.submit_coe(client, initiator, coe["id"])

    selection = fixtures.run_qc_selection(client)
    review = fixtures.open_review_for(client, coe["id"])
    reinterview = fixtures.file_reinterview(
        client,
        reviewer,
        student["id"],
        move["id"],
        coe["id"],
        outcome=OUTCOME_CONTRADICTS,
        corroboration_count=1,
    )

    base.initiator = initiator
    base.reviewer = reviewer
    base.student = student
    base.move = move
    base.coe = coe
    base.selection = selection
    base.review = review
    base.reinterview = reinterview
    return base


def test_a_failed_review_returns_the_certificate_for_correction(client):
    """The fail branch drives QC_SELECTED to RETURNED_FOR_CORRECTION and clears the window.

    "It then drives the certificate `QC_SELECTED` -> `RETURNED_FOR_CORRECTION`,
    increments `correction_round_count` by 1, clears `provisional_eligibility_end_on`
    back to null, and increments the certificate's `version` by 1."

    Design: Difficulty/non_linear_state_machine/coe_cycles_back_to_draft_after_failed_qc_and_can_be_resubmitted
    """
    bundle = _selected_certificate(client)

    assert_int_equals(bundle.selection["candidate_count"], 1, "selection.candidate_count")
    assert_int_equals(bundle.selection["target_n"], 1, "selection.target_n")
    assert_int_equals(bundle.selection["selected_count"], 1, "selection.selected_count")
    assert_int_equals(
        bundle.review["selection_reason"], SELECTION_REASON_QUOTA, "review.selection_reason"
    )

    decided = validate_success(
        client.decide_qc_review(
            bundle.review["id"],
            factories.qc_decision_payload(
                QC_DECISION_FAIL,
                bundle.reinterview["id"],
                discrepancy_codes=["RESIDENCY_DATE"],
            ),
            make_qc_reviewer_headers(bundle.reviewer),
        ),
        200,
    )

    assert_int_equals(decided["status"], REVIEW_FAILED, "review.status")
    assert_int_equals(
        decided["reviewer_recruiter_id"], bundle.reviewer, "review.reviewer_recruiter_id"
    )
    assert_int_equals(
        decided["discrepancy_codes"], ["RESIDENCY_DATE"], "review.discrepancy_codes"
    )
    assert_instant_equals(decided["decided_on"], CLOCK_START_INSTANT, "review.decided_on")

    coe = validate_success(
        client.get_coe(bundle.coe["id"], make_recruiter_headers(bundle.initiator)), 200
    )
    assert_int_equals(coe["status"], COE_RETURNED_FOR_CORRECTION, "certificate.status")
    assert_int_equals(coe["correction_round_count"], 1, "certificate.correction_round_count")
    assert_is_null(
        coe["provisional_eligibility_end_on"],
        "certificate.provisional_eligibility_end_on",
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"], ELIGIBILITY_NOT_ELIGIBLE, "student.eligibility_status"
    )


def test_the_corrected_certificate_can_be_resubmitted_without_resetting_the_counter(client):
    """Correction returns the row to DRAFT and a resubmission mints a fresh window.

    "The failed certificate is now back at the top of the correction loop, and its
    recruiter can correct and resubmit it, whereupon a fresh provisional window and a
    fresh `risk_flag_count` are written and the cycle may repeat with
    `correction_round_count` climbing each time."

    Design: Difficulty/non_linear_state_machine/coe_cycles_back_to_draft_after_failed_qc_and_can_be_resubmitted
    """
    bundle = _selected_certificate(client)
    assert_int_equals(
        fixtures.read_student(client, bundle.student["id"])["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status before the decision",
    )
    selected = validate_success(
        client.get_coe(bundle.coe["id"], make_recruiter_headers(bundle.initiator)), 200
    )
    assert_int_equals(selected["status"], COE_QC_SELECTED, "certificate.status")

    fixtures.decide_review(
        client,
        bundle.reviewer,
        bundle.review["id"],
        factories.qc_decision_payload(
            QC_DECISION_FAIL,
            bundle.reinterview["id"],
            discrepancy_codes=["RESIDENCY_DATE"],
        ),
    )

    corrected = validate_success(
        client.patch_coe(
            bundle.coe["id"],
            {"residency_date": "2026-07-15"},
            make_recruiter_headers(bundle.initiator),
        ),
        200,
    )
    assert_int_equals(corrected["status"], COE_DRAFT, "certificate.status")
    assert_date_equals(
        corrected["residency_date"], "2026-07-15", "certificate.residency_date"
    )
    assert_int_equals(
        corrected["correction_round_count"], 1, "certificate.correction_round_count"
    )

    resubmitted = validate_success(
        client.submit_coe(bundle.coe["id"], make_recruiter_headers(bundle.initiator)), 200
    )
    assert_int_equals(resubmitted["status"], COE_SUBMITTED, "certificate.status")
    assert_int_equals(
        resubmitted["correction_round_count"], 1, "certificate.correction_round_count"
    )
    assert_date_equals(
        resubmitted["provisional_eligibility_end_on"],
        "2029-06-14",
        "certificate.provisional_eligibility_end_on",
    )

    student = fixtures.read_student(client, bundle.student["id"])
    assert_int_equals(
        student["eligibility_status"],
        ELIGIBILITY_PENDING_DETERMINATION,
        "student.eligibility_status",
    )
