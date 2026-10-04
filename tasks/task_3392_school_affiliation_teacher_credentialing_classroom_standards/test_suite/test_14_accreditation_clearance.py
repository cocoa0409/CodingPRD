"""Classroom-clearance variants at application submit (LATEST_PASS vs
NO_FAIL_IN_CYCLE on identical audit histories) and segregation of duties at
accreditation approval.
"""

from test_helpers import (
    CONSULTANT_USER_ID,
    ApiErrorId,
    advance_school_once,
    create_accepted_self_study,
    create_active_catalog,
    create_application,
    create_classroom,
    create_school,
    create_visit,
    file_classroom_audit,
    file_visit_report,
    make_reviewer_headers,
    make_school_admin_headers,
    pay_dues,
    read_application,
    read_classroom,
    read_school,
    reset_clock,
    review_application,
    review_application_payload,
    set_clock,
    stage_accreditation_application,
    submit_application,
    validate_error,
    validate_success,
)


def test_membership_submit_latest_pass_forgives_earlier_noncompliant(api):
    """PRD section 3.7: "Under LATEST_PASS — used at `MEMBERSHIP` submission —
    a classroom clears when its most recent audit, chosen by greatest
    `created_at` with same-instant filings tie-broken by server receipt order
    rather than by id, has verdict `COMPLIANT` and the room's
    `compliance_override` is `NONE`; earlier failures are forgiven."

    Design: Difficulty/dual_variant_calc/school_clearance_latest_vs_no_fail_cycle
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="X School", display_name="X Schoolhouse")
    pay_dues(school["id"])
    room = create_classroom(school["id"], name="CX", enrolled_student_count=30)

    file_classroom_audit(room["id"], students_present=31, adults_present=2)
    set_clock("2026-09-03T00:00:00Z")
    file_classroom_audit(room["id"], students_present=30, adults_present=2)
    assert read_classroom(room["id"])["latest_audit_verdict"] == "COMPLIANT"

    advance_school_once(school["id"], "AFFILIATION")
    application = create_application(school["id"], "MEMBERSHIP")
    submitted = submit_application(application["id"], school["id"])
    assert submitted["status"] == "UNDER_REVIEW", "LATEST_PASS forgives the earlier NONCOMPLIANT"


def test_accreditation_submit_no_fail_in_cycle_rejects_in_window_failure(api):
    """PRD section 3.7: "Under NO_FAIL_IN_CYCLE — used at `ACCREDITATION`
    submission — a classroom clears when no audit whose `observed_at` date
    falls inside the trailing 12 calendar months, inclusive of today, has
    verdict `NONCOMPLIANT`, at least one such in-window audit exists, and the
    room's `compliance_override` is `NONE`." PRD section 3.7: "a single
    `NONCOMPLIANT` audit followed by a `COMPLIANT` one inside the window
    clears under LATEST_PASS but not under NO_FAIL_IN_CYCLE."

    Design: Difficulty/dual_variant_calc/school_clearance_latest_vs_no_fail_cycle
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Y School", display_name="Y Schoolhouse")
    pay_dues(school["id"])
    room = create_classroom(school["id"], name="CY", enrolled_student_count=24)
    file_classroom_audit(room["id"], students_present=24, adults_present=2)
    advance_school_once(school["id"], "AFFILIATION")
    advance_school_once(school["id"], "MEMBERSHIP")
    assert read_school(school["id"])["member_since"] == "2026-09-01"

    study = create_accepted_self_study(school["id"])
    set_clock("2027-09-05T00:00:00Z")
    visit = create_visit(
        school["id"], study["id"], window_start="2027-10-10", window_end="2027-10-12"
    )
    set_clock("2027-10-10T00:00:00Z")
    file_visit_report(visit["id"], verdict="COMPLIANT", findings=["Compliant across all standards"])

    set_clock("2027-10-15T00:00:00Z")
    file_classroom_audit(room["id"], students_present=31, adults_present=2)
    set_clock("2027-10-16T00:00:00Z")
    file_classroom_audit(room["id"], students_present=24, adults_present=2)

    pay_dues(school["id"], period_start="2027-09-04", period_end="2028-09-02", amount_cents=90000)
    set_clock("2027-10-20T00:00:00Z")
    application = create_application(school["id"], "ACCREDITATION")
    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_CLASSROOM_NONCOMPLIANT)
    assert read_application(application["id"])["status"] == "DRAFT"


def test_accreditation_approval_by_visit_consultant_rejected_segregation(api):
    """PRD section 3.7: "the approving reviewer's `X-User-ID` must differ from
    the `consultant_id` recorded on that visit, failing with
    `ERR_SEGREGATION_OF_DUTIES` (HTTP 409) — the reviewer is never the
    consultant who filed the supporting report."

    Design: Corner/validations/accreditation_approval_by_visit_consultant_rejected_segregation
    """
    reset_clock()
    staged = stage_accreditation_application()
    application_id = staged.application["id"]

    same_user = api.review_school_application(
        application_id,
        review_application_payload("APPROVED"),
        headers=make_reviewer_headers(CONSULTANT_USER_ID),
    )
    validate_error(same_user, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
    assert read_application(application_id)["status"] == "UNDER_REVIEW", (
        "the rejection leaves the application actionable"
    )

    approved = review_application(application_id, "APPROVED")
    assert approved["status"] == "APPROVED"
    school = read_school(staged.school["id"])
    assert school["membership_level"] == "ACCREDITED"
    assert school["directory_visible"] is True
