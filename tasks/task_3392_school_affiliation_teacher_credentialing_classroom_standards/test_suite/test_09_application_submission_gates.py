"""School application submission gates: next-level typing, in-flight
uniqueness, the classroom floor, delinquent dues, missing self-study or
verification visit, the accreditation tenure boundary, and the referential
tier outranking the fiscal tier.
"""

from test_helpers import (
    ApiErrorId,
    create_accepted_self_study,
    create_active_catalog,
    create_application,
    create_classroom,
    create_school,
    create_school_application_payload,
    create_visit,
    file_classroom_audit,
    file_visit_report,
    make_school_admin_headers,
    pay_dues,
    read_application,
    read_school,
    reset_clock,
    school_version,
    set_clock,
    setup_member_school,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_application_type_must_match_schools_next_level(api):
    """PRD section 3.7: "The `type` must name the school's next level —
    `AFFILIATION` for an `APPLICANT` school, `MEMBERSHIP` for an `AFFILIATE`,
    `ACCREDITATION` for a `MEMBER` — and a wrong-typed application fails with
    `ERR_INVALID_STATE` (HTTP 409)."

    Design: Corner/state_machines/application_type_must_match_schools_next_level
    """
    reset_clock()
    school = create_school(name="Skip School", display_name="Skip Schoolhouse")
    rejected = api.create_school_application(
        create_school_application_payload(school["id"], "MEMBERSHIP", school["version"]),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_INVALID_STATE)

    rows, meta = validate_paginated(
        api.list_school_applications(
            headers=make_school_admin_headers(school["id"]),
            params={"school_id": school["id"]},
        )
    )
    assert rows == [] and meta["total_count"] == 0


def test_affiliation_submit_with_delinquent_dues_rejected(api):
    """PRD section 3.7: "Every type requires the school's dues to be current at
    submission, failing with `ERR_DUES_DELINQUENT` (HTTP 402)."

    Design: Corner/validations/affiliation_submit_with_delinquent_dues_rejected
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Broke School", display_name="Broke Schoolhouse")
    create_classroom(school["id"], name="CB")
    application = create_application(school["id"], "AFFILIATION")

    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_DUES_DELINQUENT)
    assert read_application(application["id"])["status"] == "DRAFT"


def test_affiliation_submit_requires_at_least_one_classroom(api):
    """PRD section 3.7: "An `AFFILIATION` submission additionally requires at
    least one classroom (`ERR_CLASSROOM_REQUIRED`, HTTP 422)".

    Design: Corner/validations/affiliation_submit_requires_at_least_one_classroom
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="Empty School", display_name="Empty Schoolhouse")
    pay_dues(school["id"])
    application = create_application(school["id"], "AFFILIATION")

    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_CLASSROOM_REQUIRED)

    create_classroom(school["id"], name="First Room", enrolled_student_count=12)
    accepted = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school["id"])
    )
    assert validate_success(accepted, 200)["status"] == "UNDER_REVIEW"


def test_second_in_flight_application_rejected(api):
    """PRD section 3.7: "Only one application per school may be in flight
    across `DRAFT`, `UNDER_REVIEW`, `RETURNED` and `SUSPENDED`; a second fails
    with `ERR_IN_FLIGHT_APPLICATION_EXISTS` (HTTP 409)."

    Design: Corner/validations/second_in_flight_application_rejected
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="IF App School", display_name="IF App Schoolhouse")
    create_application(school["id"], "AFFILIATION")

    fresh_version = school_version(school["id"])
    rejected = api.create_school_application(
        create_school_application_payload(school["id"], "AFFILIATION", fresh_version),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_IN_FLIGHT_APPLICATION_EXISTS)

    rows, meta = validate_paginated(
        api.list_school_applications(
            headers=make_school_admin_headers(school["id"]),
            params={"school_id": school["id"]},
        )
    )
    assert len(rows) == 1 and meta["total_count"] == 1


def test_accreditation_submit_without_filed_visit_rejected(api):
    """PRD section 3.7: "a `REPORT_FILED` visit on that study must exist, else
    `ERR_VERIFICATION_VISIT_REQUIRED` (HTTP 422)".

    Design: Corner/validations/accreditation_submit_without_filed_visit_rejected
    """
    reset_clock()
    staged = setup_member_school()
    create_accepted_self_study(staged.school["id"])
    set_clock("2027-09-02T00:00:00Z")

    application = create_application(staged.school["id"], "ACCREDITATION")
    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(staged.school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_VERIFICATION_VISIT_REQUIRED)
    assert read_application(application["id"])["status"] == "DRAFT"


def test_accreditation_tenure_boundary_day_before_vs_day_of(api):
    """PRD section 3.7: "the current logical date must be at least
    `member_since` plus the `ACTIVE` catalog's
    `min_membership_months_before_accreditation` — equality passes — else
    `ERR_ACCREDITATION_TENURE_TOO_SHORT` (HTTP 422)".

    Design: Corner/validations/accreditation_tenure_boundary_day_before_vs_day_of
    """
    reset_clock()
    staged = setup_member_school()
    school_id = staged.school["id"]
    study = create_accepted_self_study(school_id)
    visit = create_visit(school_id, study["id"])
    set_clock("2026-10-01T00:00:00Z")
    file_classroom_audit(staged.classroom["id"])
    file_visit_report(visit["id"], verdict="COMPLIANT", findings=["Compliant"])

    set_clock("2027-08-31T00:00:00Z")
    application = create_application(school_id, "ACCREDITATION")
    day_before = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school_id)
    )
    validate_error(day_before, ApiErrorId.ERR_ACCREDITATION_TENURE_TOO_SHORT)

    set_clock("2027-09-01T00:00:00Z")
    day_of = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(school_id)
    )
    assert validate_success(day_of, 200)["status"] == "UNDER_REVIEW"
    assert read_school(school_id)["member_since"] == "2026-09-01"


def _member_school_with_lapsed_dues():
    """MEMBER school (member_since 2026-09-01) whose dues run only through
    2027-08-31, with an in-window COMPLIANT audit and no self-study; clock at
    the exact tenure boundary 2027-09-01."""
    staged = setup_member_school(dues_period_end="2027-08-31")
    set_clock("2027-09-01T00:00:00Z")
    return staged


def test_self_study_error_outranks_dues_error_on_accreditation_submit(api):
    """PRD section 3.7: "Submitting a `DRAFT` application — or resubmitting a
    `RETURNED` one, which closes the revision loop and re-evaluates everything
    against current state — runs the escalating requirement chain in the
    pipeline's order: state first, then the tenure temporal check, then
    referential requirements, then the constraint checks, and fiscal last."
    PRD section 3.7: "the school must hold an `ACCEPTED` self-study, else
    `ERR_SELF_STUDY_REQUIRED` (HTTP 422)".

    Design: Difficulty/priority_pair_validation_conflict/accreditation_submit_rejected_with_self_study_error_over_dues_error
    """
    reset_clock()
    staged = _member_school_with_lapsed_dues()
    application = create_application(staged.school["id"], "ACCREDITATION")
    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(staged.school["id"])
    )
    error = validate_error(rejected, ApiErrorId.ERR_SELF_STUDY_REQUIRED)
    assert error["error_id"] != ApiErrorId.ERR_DUES_DELINQUENT.value, (
        "the referential tier (8) fires before the fiscal tier (10)"
    )
    assert error["error_id"] != ApiErrorId.ERR_ACCREDITATION_TENURE_TOO_SHORT.value, (
        "2027-09-01 >= member_since 2026-09-01 + 12 months exactly: tenure passes"
    )


def test_self_study_priority_rejection_leaves_application_draft(api):
    """PRD section 3.7: "the school must hold an `ACCEPTED` self-study, else
    `ERR_SELF_STUDY_REQUIRED` (HTTP 422)". PRD section 3.7: "A successful
    submission stamps `submitted_at` and moves the application to
    `UNDER_REVIEW`" — a rejected submission does neither.

    Design: Difficulty/priority_pair_validation_conflict/accreditation_submit_rejected_with_self_study_error_over_dues_error
    """
    reset_clock()
    staged = _member_school_with_lapsed_dues()
    application = create_application(staged.school["id"], "ACCREDITATION")
    rejected = api.submit_school_application(
        application["id"], headers=make_school_admin_headers(staged.school["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_SELF_STUDY_REQUIRED)

    application = read_application(application["id"])
    assert application["status"] == "DRAFT"
    assert application["submitted_at"] is None
    school = read_school(staged.school["id"])
    assert school["member_since"] == "2026-09-01"
    assert school["dues_paid_through"] == "2027-08-31"
    assert school["dues_current"] is False
