"""Security layers (authentication, role authorization, entity-backed
ownership) and the entity-specific 404 sweep, including left-to-right path
resolution before body foreign keys.
"""

from test_helpers import (
    ACCREDITATION_REVIEWER,
    ANONYMOUS,
    CONSULTANT,
    NON_EXISTENT_UUID,
    NON_EXISTENT_UUID_ALT,
    SOCIETY_ADMIN,
    ApiErrorId,
    create_active_catalog,
    create_application,
    create_classroom,
    create_classroom_payload,
    create_placement,
    create_program,
    create_school,
    create_school_payload,
    enroll_learner,
    log_hours,
    make_program_director_headers,
    make_school_admin_headers,
    pay_dues,
    read_application,
    read_placement,
    record_attendance_payload,
    reset_clock,
    review_application_payload,
    setup_affiliate_host_school,
    submit_application,
    validate_error,
    validate_paginated,
)


def test_schools_create_missing_auth_returns_unauthenticated(api):
    """PRD section 2.1: "A request missing either header, or carrying a role
    the server does not recognize, is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401) on every endpoint except the two public directory reads, which
    accept anonymous callers."

    Design: Corner/validations/schools_create_missing_auth_returns_unauthenticated
    """
    reset_clock()
    rejected = api.create_school(
        create_school_payload(
            name="NoHdr",
            display_name="NoHdr School",
            uses_method_name=False,
            contact_email="nh@x.org",
        ),
        headers=ANONYMOUS,
    )
    validate_error(rejected, ApiErrorId.ERR_UNAUTHENTICATED)

    rows, meta = validate_paginated(api.list_schools(headers=SOCIETY_ADMIN))
    assert rows == [] and meta["total_count"] == 0


def test_consultant_cannot_create_school_forbidden(api):
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/validations/consultant_cannot_create_school_forbidden
    """
    reset_clock()
    rejected = api.create_school(
        create_school_payload(
            name="Nope",
            display_name="Nope School",
            uses_method_name=False,
            contact_email="no@x.org",
        ),
        headers=CONSULTANT,
    )
    validate_error(rejected, ApiErrorId.ERR_FORBIDDEN)


def test_school_admin_cannot_touch_other_school_forbidden(api):
    """PRD section 2.1: "When `X-User-Role` is `SchoolAdmin`, `X-User-ID` is
    the `id` of the acting `School`; ownership checks compare the target
    school's `id` — or the `school_id` of the target child resource such as an
    application, self-study or improvement plan — to `X-User-ID`." PRD section
    2.1: "An entity-backed ownership mismatch is rejected with `ERR_FORBIDDEN`
    (HTTP 403)."

    Design: Corner/validations/school_admin_cannot_touch_other_school_forbidden
    """
    reset_clock()
    school_a = create_school(name="A School", display_name="A Schoolhouse")
    school_b = create_school(name="B School", display_name="B Schoolhouse")

    intruder = api.create_classroom(
        create_classroom_payload(
            school_b["id"],
            name="Intruder",
            age_level="EARLY_CHILDHOOD",
            declared_age_span_years=3,
            enrolled_student_count=10,
            assistant_count=1,
        ),
        headers=make_school_admin_headers(school_a["id"]),
    )
    validate_error(intruder, ApiErrorId.ERR_FORBIDDEN)

    rows, meta = validate_paginated(
        api.list_classrooms(headers=ACCREDITATION_REVIEWER, params={"school_id": school_b["id"]})
    )
    assert rows == [] and meta["total_count"] == 0


def test_school_admin_cannot_review_applications_forbidden(api):
    """PRD section 2.1: "A request whose role is authenticated but not listed
    among an endpoint's authorized roles is rejected with `ERR_FORBIDDEN`
    (HTTP 403)." The review step belongs exclusively to the
    AccreditationReviewer, even for the school's own admin.

    Design: Corner/rbac/school_admin_cannot_review_applications_forbidden
    """
    reset_clock()
    create_active_catalog()
    school = create_school(name="RBAC School", display_name="RBAC Schoolhouse")
    pay_dues(school["id"])
    create_classroom(school["id"], name="CR")
    application = create_application(school["id"], "AFFILIATION")
    submit_application(application["id"], school["id"])

    rejected = api.review_school_application(
        application["id"],
        review_application_payload("APPROVED"),
        headers=make_school_admin_headers(school["id"]),
    )
    validate_error(rejected, ApiErrorId.ERR_FORBIDDEN)
    assert read_application(application["id"])["status"] == "UNDER_REVIEW"


def test_program_director_cannot_verify_other_programs_placement(api):
    """PRD section 3.4: "A `ProgramDirector` verifies a placement that sits in
    `HOURS_COMPLETE`, but only for a learner of their own program — the
    director's `X-User-ID` must equal the learner's `program_id`, else
    `ERR_FORBIDDEN` (HTTP 403)".

    Design: Corner/rbac/program_director_cannot_verify_other_programs_placement
    """
    reset_clock()
    create_active_catalog()
    program_a = create_program(name="PD A")
    program_b = create_program(name="PD B")
    learner_b = enroll_learner(program_b["id"], full_name="B Learner")
    host = setup_affiliate_host_school()
    placement = create_placement(learner_b["id"], host.school["id"], program_b["id"])
    log_hours(placement["id"], learner_b["id"], 540)
    assert read_placement(placement["id"])["status"] == "HOURS_COMPLETE"

    rejected = api.verify_practicum_placement(
        placement["id"], headers=make_program_director_headers(program_a["id"])
    )
    validate_error(rejected, ApiErrorId.ERR_FORBIDDEN)
    assert read_placement(placement["id"])["status"] == "HOURS_COMPLETE"


def test_not_found_sweep_plans_events_audits(api):
    """PRD section 2.10: "the server validates existence strictly left to right
    and rejects with the 404 of the first identifier that does not resolve,
    before any business rule runs". The unknown event id in the attendance path
    is therefore reported before the unknown credential id in its body.

    Design: Corner/errors/not_found_sweep_plans_events_audits
    """
    reset_clock()
    plan = api.get_improvement_plan(NON_EXISTENT_UUID, headers=ACCREDITATION_REVIEWER)
    validate_error(plan, ApiErrorId.ERR_PLAN_NOT_FOUND)

    event = api.record_event_attendance(
        NON_EXISTENT_UUID,
        record_attendance_payload(NON_EXISTENT_UUID_ALT),
        headers=SOCIETY_ADMIN,
    )
    validate_error(event, ApiErrorId.ERR_EVENT_NOT_FOUND)

    audit = api.get_classroom_audit(NON_EXISTENT_UUID, headers=CONSULTANT)
    validate_error(audit, ApiErrorId.ERR_AUDIT_NOT_FOUND)


def test_not_found_sweep_remaining_entities(api):
    """PRD section 2.7: "Tier 3 is existence: path identifiers are validated
    left to right, then body-supplied foreign keys that are present and
    well-formed — `school_id`, `learner_id`, `classroom_id`, `credential_id`,
    `self_study_id`, `supervisor_credential_id`, `host_school_id`,
    `to_classroom_id`, `visit_id` — each failing with its entity-specific
    404".

    Design: Corner/errors/not_found_sweep_remaining_entities
    """
    reset_clock()
    cases = [
        (api.get_classroom, ApiErrorId.ERR_CLASSROOM_NOT_FOUND),
        (api.get_teacher_education_program, ApiErrorId.ERR_PROGRAM_NOT_FOUND),
        (api.get_adult_learner, ApiErrorId.ERR_LEARNER_NOT_FOUND),
        (api.get_practicum_placement, ApiErrorId.ERR_PLACEMENT_NOT_FOUND),
        (api.get_school_application, ApiErrorId.ERR_APPLICATION_NOT_FOUND),
        (api.get_self_study, ApiErrorId.ERR_SELF_STUDY_NOT_FOUND),
        (api.get_verification_visit, ApiErrorId.ERR_VISIT_NOT_FOUND),
        (api.get_standards_catalog, ApiErrorId.ERR_CATALOG_NOT_FOUND),
        (api.get_ce_entry, ApiErrorId.ERR_CE_ENTRY_NOT_FOUND),
    ]
    for getter, error_id in cases:
        resp = getter(NON_EXISTENT_UUID, headers=SOCIETY_ADMIN)
        validate_error(resp, error_id)
