"""The two eligibility-window variants written on one certificate row."""

from prd_bench_local_runner.testing import validate_success

from test_helpers import fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
)
from test_helpers.constants import COE_APPROVED, COE_SUBMITTED
from test_helpers.test_users import make_admin_headers, make_recruiter_headers


def _draft_certificate(client):
    """A child with a VERIFIED move dated 2026-06-15 and a DRAFT certificate on it."""
    bundle = fixtures.identified_child(client)
    bundle.coe = fixtures.draft_coe(
        client,
        bundle.recruiter["id"],
        bundle.student["id"],
        bundle.move["id"],
        residency_date="2026-07-01",
        qc_hold_exempt=True,
    )
    return bundle


def test_submission_writes_only_the_move_anchored_provisional_window(client):
    """Submission writes the move-anchored provisional end date and no final window.

    "It is anchored on the qualifying move rather than on residency: take the move's
    `move_date`, add 36 calendar months to it under the day-of-month convention of
    2.6, then step back one day; the result is the last day of the provisional window."

    Design: Difficulty/dual_variant_calc/coe_window_provisional_move_anchored_vs_final_residency_anchored
    """
    bundle = _draft_certificate(client)

    submitted = validate_success(
        client.submit_coe(
            bundle.coe["id"], make_recruiter_headers(bundle.recruiter["id"])
        ),
        200,
    )

    assert_int_equals(submitted["status"], COE_SUBMITTED, "certificate.status")
    assert_date_equals(
        submitted["provisional_eligibility_end_on"],
        "2029-06-14",
        "certificate.provisional_eligibility_end_on",
    )
    assert_is_null(
        submitted["eligibility_start_on"], "certificate.eligibility_start_on"
    )
    assert_is_null(submitted["eligibility_end_on"], "certificate.eligibility_end_on")
    assert_is_null(submitted["age_out_capped"], "certificate.age_out_capped")

    stored = validate_success(
        client.get_coe(bundle.coe["id"], make_admin_headers()), 200
    )
    assert_date_equals(
        stored["provisional_eligibility_end_on"],
        "2029-06-14",
        "stored certificate.provisional_eligibility_end_on",
    )
    assert_is_null(
        stored["eligibility_end_on"], "stored certificate.eligibility_end_on"
    )


def test_approval_writes_the_residency_anchored_window_beside_the_provisional_one(client):
    """Approval writes the residency-anchored final window and leaves the provisional value.

    "`eligibility_start_on` is set equal to the certificate's `residency_date`."

    Design: Difficulty/dual_variant_calc/coe_window_provisional_move_anchored_vs_final_residency_anchored
    """
    bundle = _draft_certificate(client)
    fixtures.submit_coe(client, bundle.recruiter["id"], bundle.coe["id"])

    approved = validate_success(
        client.approve_coe(bundle.coe["id"], make_admin_headers()), 200
    )

    assert_int_equals(approved["status"], COE_APPROVED, "certificate.status")
    assert_date_equals(
        approved["eligibility_start_on"],
        "2026-07-01",
        "certificate.eligibility_start_on",
    )
    assert_date_equals(
        approved["eligibility_end_on"], "2029-06-30", "certificate.eligibility_end_on"
    )
    assert_int_equals(approved["age_out_capped"], False, "certificate.age_out_capped")
    assert_date_equals(
        approved["provisional_eligibility_end_on"],
        "2029-06-14",
        "certificate.provisional_eligibility_end_on",
    )
    assert (
        approved["eligibility_end_on"] != approved["provisional_eligibility_end_on"]
    ), "the two window variants must diverge when residency followed the move"
