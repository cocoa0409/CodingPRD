"""Authentication, authorization, ownership, and visibility gates (PRD §2.1, §3.7)."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_integration,
    create_assignment,
    create_institution,
    create_instructor,
    create_student,
    get_assignment_version,
    grant_consent,
    make_instructor_headers,
    make_student_headers,
    process,
    setup_basic_scenario,
    setup_processed_submission,
    submit,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]


def test_missing_auth_headers_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or the supplied role is not one of
    the four known roles, the request is rejected with `ERR_UNAUTHENTICATED`
    (HTTP 401)."

    Design: Corner/rbac/missing_auth_headers_unauthenticated
    """
    inst = create_institution(name="Auth U", residency_region="US")
    resp = api.get_institution(inst["id"], headers=None)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_instructor_cannot_patch_other_instructors_assignment(api):
    """PRD §2.1: "When `X-User-Role` is `Instructor`, `X-User-ID` is the `id` of
    the acting `Instructor`; ownership checks on any resource that references an
    `Instructor` (notably `Assignment.instructor_id`) compare that foreign-key
    field to `X-User-ID`, so an instructor may only write against assignments
    whose `instructor_id` equals their own `X-User-ID`."

    Design: Corner/rbac/instructor_cannot_patch_other_instructors_assignment
    """
    inst = create_institution(name="Own U", residency_region="US")
    integ = create_active_integration(inst["id"], external_key="c21")
    instr_a = create_instructor(inst["id"], email="ia@x.edu")
    instr_b = create_instructor(inst["id"], email="ib@x.edu")
    asg = create_assignment(integ["id"], instr_a["id"], title="Owned by A")

    resp = api.patch_assignment(
        asg["id"],
        {"expected_assignment_version": asg["version"], "exclude_quotes": True},
        make_instructor_headers(instr_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
    fetched = validate_success(api.get_assignment(asg["id"], make_instructor_headers(instr_a["id"])))
    assert fetched["exclude_quotes"] is False, "assignment unchanged after a forbidden write"


def test_student_report_gated_by_visibility(api):
    """PRD §3.7: "Students see reports only after release: a `Student` may read a
    submission's report solely when the assignment's `report_visibility` is
    `RELEASED` and the submission is their own; otherwise the read is
    `ERR_FORBIDDEN`."

    Design: Corner/rbac/student_report_gated_by_visibility
    """
    inst, integ, instr, student, asg, sub = setup_processed_submission("US", "visibility body")

    hidden = api.list_similarity_reports(sub["id"], make_student_headers(student["id"]))
    validate_error(hidden, ApiErrorId.ERR_FORBIDDEN, expected_status=403)

    asg_v = get_assignment_version(asg["id"], instr["id"])
    validate_success(
        api.patch_assignment(
            asg["id"],
            {"expected_assignment_version": asg_v, "report_visibility": "RELEASED"},
            make_instructor_headers(instr["id"]),
        )
    )
    resp = api.list_similarity_reports(sub["id"], make_student_headers(student["id"]))
    data = validate_success(resp)
    assert len(data) == 1, "released reports are readable by the owning student"


def test_student_cannot_submit_for_other_student(api):
    """PRD §3.4: "Authentication, authorization, and ownership — the caller's
    role must be `Student` and the payload's `student_id` must equal the
    caller's `X-User-ID`, otherwise `ERR_UNAUTHENTICATED` or `ERR_FORBIDDEN`."

    Design: Corner/rbac/student_cannot_submit_for_other_student
    """
    inst = create_institution(name="OwnS U", residency_region="US")
    integ = create_active_integration(inst["id"], external_key="c23")
    instr = create_instructor(inst["id"])
    stu_a = create_student(inst["id"], external_lms_id="osa")
    grant_consent(stu_a["id"], stu_a["version"])
    stu_b = create_student(inst["id"], external_lms_id="osb")
    grant_consent(stu_b["id"], stu_b["version"])
    asg = create_assignment(integ["id"], instr["id"], title="OwnS")

    resp = api.create_submission(
        asg["id"],
        {"student_id": stu_a["id"], "content_text": "forged authorship"},
        make_student_headers(stu_b["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
