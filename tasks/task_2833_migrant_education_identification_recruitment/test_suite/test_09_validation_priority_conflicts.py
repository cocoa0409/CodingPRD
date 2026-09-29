"""Deliberately conflicting failures resolve in the specified ladder order."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors, factories, fixtures
from test_helpers.assertions import (
    assert_date_equals,
    assert_int_equals,
    assert_is_null,
    assert_row_count,
    assert_version_unchanged,
)
from test_helpers.constants import (
    ASSIGNMENT_STATUS_PLANNED,
    COE_APPROVED,
    COE_QC_SELECTED,
    COVERAGE_ROLE_PRIMARY,
    CREDENTIAL_QC_CERTIFIED,
    QC_DECISION_PASS,
    REVIEW_OPEN,
)
from test_helpers.test_users import (
    make_admin_headers,
    make_qc_reviewer_headers,
    make_recruiter_headers,
)


# --------------------------------------------------------------------------------------
# State-machine position outranks the temporal residency check on a correction.
# --------------------------------------------------------------------------------------
def _approved_certificate(client):
    bundle = fixtures.certified_child(
        client, coe_overrides={"residency_date": "2026-07-01", "qc_hold_exempt": True}
    )
    bundle.coe = validate_success(
        client.get_coe(bundle.coe["id"], make_admin_headers()), 200
    )
    return bundle


def test_correcting_an_approved_certificate_reports_the_state_failure_not_the_date_failure(
    client,
):
    """A residency date before the move on an APPROVED row still reports the state code.

    "From any other status the correction is refused with `ERR_COE_NOT_IN_DRAFT`."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_6_beats_business_temporal_priority_18_and_rejects_patch_of_approved_coe
    """
    bundle = _approved_certificate(client)

    response = client.patch_coe(
        bundle.coe["id"],
        {"residency_date": "2026-06-01"},
        make_recruiter_headers(bundle.recruiter["id"]),
    )

    validate_error(response, api_errors.ERR_COE_NOT_IN_DRAFT, 409)


def test_the_rejected_correction_leaves_the_approved_certificate_exactly_as_it_was(client):
    """The refused write moves neither the stored residency date nor the final window.

    "A supplied `residency_date` is re-validated against the linked move's `move_date`
    and again reports `ERR_RESIDENCY_DATE_BEFORE_MOVE` when it precedes it."

    Design: Difficulty/priority_pair_validation_conflict/state_priority_6_beats_business_temporal_priority_18_and_rejects_patch_of_approved_coe
    """
    bundle = _approved_certificate(client)
    before = bundle.coe

    client.patch_coe(
        bundle.coe["id"],
        {"residency_date": "2026-06-01"},
        make_recruiter_headers(bundle.recruiter["id"]),
    )

    after = validate_success(client.get_coe(bundle.coe["id"], make_admin_headers()), 200)
    assert_int_equals(after["status"], COE_APPROVED, "certificate.status")
    assert_date_equals(after["residency_date"], "2026-07-01", "certificate.residency_date")
    assert_date_equals(
        after["eligibility_end_on"], "2029-06-30", "certificate.eligibility_end_on"
    )
    assert_version_unchanged(after, before["version"], "certificate")


# --------------------------------------------------------------------------------------
# Segregation of duties outranks the re-interview linkage check on a decision.
# --------------------------------------------------------------------------------------
def _self_reviewed_selection(client):
    """One QC-credentialled recruiter who both initiated and was drawn to review the row."""
    base = fixtures.area_and_recruiter(
        client, recruiter_overrides={"credential_level": CREDENTIAL_QC_CERTIFIED}
    )
    recruiter_id = base.recruiter["id"]
    student = fixtures.create_student(client, recruiter_id, base.area["id"])
    move = fixtures.verified_move(client, recruiter_id, student["id"])
    interview = fixtures.file_interview(client, recruiter_id, student["id"], move["id"])
    coe = fixtures.draft_coe(
        client, recruiter_id, student["id"], move["id"], qc_hold_exempt=False
    )
    fixtures.submit_coe(client, recruiter_id, coe["id"])
    fixtures.run_qc_selection(client)

    base.recruiter_id = recruiter_id
    base.student = student
    base.move = move
    base.interview = interview
    base.coe = coe
    base.review = fixtures.open_review_for(client, coe["id"])
    return base


def test_deciding_ones_own_certificate_reports_segregation_not_the_reinterview_mismatch(
    client,
):
    """An INITIAL record cited by the initiating recruiter still reports the safety code.

    "The acting `X-User-ID` must differ from the certificate's
    `initiating_recruiter_id` - a reviewer may not decide a certificate they themselves
    initiated, and the attempt is refused with `ERR_SEGREGATION_OF_DUTIES` (403)."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_8_beats_business_referential_priority_13_and_rejects_qc_decision
    """
    bundle = _self_reviewed_selection(client)

    response = client.decide_qc_review(
        bundle.review["id"],
        factories.qc_decision_payload(QC_DECISION_PASS, bundle.interview["id"]),
        make_qc_reviewer_headers(bundle.recruiter_id),
    )

    validate_error(response, api_errors.ERR_SEGREGATION_OF_DUTIES, 403)


def test_the_refused_decision_leaves_the_review_open_and_the_certificate_selected(client):
    """Nothing on the review or the certificate moves when the decision is turned away.

    "An accepted pass sets the review's `status` to `PASSED`, writes
    `reviewer_recruiter_id` from `X-User-ID`, stores the supplied `reinterview_id`,
    stamps `decided_on` with the logical clock instant, leaves `discrepancy_codes` as an
    empty list, and increments the review's `version` by 1."

    Design: Difficulty/priority_pair_validation_conflict/business_safety_priority_8_beats_business_referential_priority_13_and_rejects_qc_decision
    """
    bundle = _self_reviewed_selection(client)

    client.decide_qc_review(
        bundle.review["id"],
        factories.qc_decision_payload(QC_DECISION_PASS, bundle.interview["id"]),
        make_qc_reviewer_headers(bundle.recruiter_id),
    )

    review = validate_success(
        client.get_qc_review(bundle.review["id"], make_admin_headers()), 200
    )
    assert_int_equals(review["status"], REVIEW_OPEN, "review.status")
    assert_is_null(review["decided_on"], "review.decided_on")
    assert_is_null(review["reviewer_recruiter_id"], "review.reviewer_recruiter_id")

    coe = validate_success(client.get_coe(bundle.coe["id"], make_admin_headers()), 200)
    assert_int_equals(coe["status"], COE_QC_SELECTED, "certificate.status")
    assert_int_equals(
        coe["correction_round_count"], 0, "certificate.correction_round_count"
    )


# --------------------------------------------------------------------------------------
# Peak-season containment outranks the area capacity aggregate on a create.
# --------------------------------------------------------------------------------------
def _single_slot_area(client):
    """A one-recruiter area already anchored by a season-long PRIMARY assignment."""
    area = fixtures.create_area(
        client,
        name="Skagit Flats",
        recruiter_capacity=1,
        peak_season_start_date="2026-06-01",
        peak_season_end_date="2026-09-30",
    )
    first = fixtures.create_recruiter(client, full_name="Rosa Aguilar")
    second = fixtures.create_recruiter(client, full_name="Ken Ortiz")
    fixtures.create_assignment(client, first["id"], area["id"])
    return fixtures.Bundle(area=area, first=first, second=second)


def test_an_assignment_inside_the_peak_season_reports_containment_not_capacity(client):
    """A PRIMARY interval narrower than the peak season reports the containment code.

    "An assignment that starts even one day into the peak season, or ends one day before
    it closes, is refused with `ERR_PEAK_SEASON_NOT_COVERED`."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_priority_19_beats_business_fiscal_priority_29_and_rejects_assignment
    """
    bundle = _single_slot_area(client)
    version = fixtures.area_version(client, bundle.area["id"])

    response = client.create_assignment(
        factories.assignment_payload(
            bundle.second["id"],
            bundle.area["id"],
            version,
            coverage_role=COVERAGE_ROLE_PRIMARY,
            starts_on="2026-07-01",
            ends_on="2026-08-31",
        ),
        make_admin_headers(),
    )

    validate_error(response, api_errors.ERR_PEAK_SEASON_NOT_COVERED, 422)


def test_the_refused_assignment_leaves_the_area_counter_and_version_untouched(client):
    """The slot counter and the area version stay where the accepted assignment left them.

    "Alongside these sits a derived counter, `assigned_primary_slots_used`, defined as
    the number of coverage assignments for this area whose `coverage_role` is `PRIMARY`
    and whose `status` is `PLANNED` or `ACTIVE`; it starts at 0 and is republished on
    every assignment create, activation and closure."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_priority_19_beats_business_fiscal_priority_29_and_rejects_assignment
    """
    bundle = _single_slot_area(client)
    before = fixtures.read_area(client, bundle.area["id"])

    client.create_assignment(
        factories.assignment_payload(
            bundle.second["id"],
            bundle.area["id"],
            before["version"],
            coverage_role=COVERAGE_ROLE_PRIMARY,
            starts_on="2026-07-01",
            ends_on="2026-08-31",
        ),
        make_admin_headers(),
    )

    after = fixtures.read_area(client, bundle.area["id"])
    assert_int_equals(
        after["assigned_primary_slots_used"], 1, "area.assigned_primary_slots_used"
    )
    assert_version_unchanged(after, before["version"], "area")

    rows, _meta = fixtures.list_rows(
        client.list_assignments(make_admin_headers(), {"area_id": bundle.area["id"]})
    )
    assert_row_count(rows, 1, "assignments in the area")
    assert_int_equals(rows[0]["status"], ASSIGNMENT_STATUS_PLANNED, "assignment.status")
