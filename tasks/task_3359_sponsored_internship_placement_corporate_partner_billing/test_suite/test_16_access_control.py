"""Role segregation: an operation reserved for one role refuses every other caller."""
from test_helpers import (
    ApiErrorId,
    anonymous_headers,
    create_cohort,
    create_enrolled_student,
    create_stipend_statement,
    interview_payload,
    make_partner_headers,
    make_student_headers,
    read_student,
    setup_matched_placement,
    staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_partner_cannot_schedule_interview_rounds(api):
    """PRD §2.1: "A caller whose role is valid but who is not among the roles
    authorized for an operation is rejected with `ERR_UNAUTHORIZED` at HTTP 401."

    Scheduling an interview round is a ProgramStaff operation, so the partner that
    owns the agreement is still refused.

    Design: Corner/rbac/partner_cannot_schedule_interview_rounds
    """
    scenario = setup_matched_placement()

    response = api.schedule_interview(
        scenario.placement["id"],
        interview_payload(),
        make_partner_headers(scenario.partner["id"]),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=401)
    placement = validate_success(
        api.get_placement(scenario.placement["id"], staff_headers()), 200
    )
    assert placement["state"] == "MATCHED", placement["state"]
    rounds, meta = validate_paginated(
        api.list_interviews(scenario.placement["id"], staff_headers())
    )
    assert meta["total_count"] == 0, rounds


def test_student_cannot_pay_a_stipend_statement(api):
    """PRD §2.1: "A caller whose role is valid but who is not among the roles
    authorized for an operation is rejected with `ERR_UNAUTHORIZED` at HTTP 401."

    Paying a stipend statement is a ProgramStaff operation, so the student the
    statement belongs to is still refused.

    Design: Corner/rbac/student_cannot_pay_a_stipend_statement
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    statement = create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=98, hours_expected=140, behavior_incidents=4,
    )

    response = api.pay_stipend_statement(
        statement["id"], make_student_headers(student["id"])
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=401)
    assert read_student(student["id"])["total_stipend_paid_cents"] == 0
    listing, meta = validate_paginated(
        api.list_student_stipends(student["id"], staff_headers())
    )
    assert meta["total_count"] == 1, listing
    assert listing[0]["status"] == "PENDING", listing[0]["status"]


def test_anonymous_caller_cannot_create_a_cohort(api):
    """PRD §2.1: "A request whose `X-User-Role` header is absent or names a role
    outside that set, or whose `X-User-ID` header is absent, is rejected with
    `ERR_UNAUTHORIZED` at HTTP 401."
    PRD §2.1: "The single exception is student registration, which is the one
    operation an `Anonymous` caller may perform without credentials; every other
    endpoint in this document requires both headers."

    Design: Corner/rbac/missing_auth_role_returns_unauthenticated
    """
    response = api.create_cohort(
        {
            "program_code": "DATA",
            "location_code": "BOS-09",
            "start_date": "2026-09-01",
            "capacity": 12,
        },
        anonymous_headers(),
    )

    validate_error(response, ApiErrorId.ERR_UNAUTHORIZED, expected_status=401)

    # The same request succeeds for the role that owns the operation.
    created = validate_success(
        api.create_cohort(
            {
                "program_code": "DATA",
                "location_code": "BOS-09",
                "start_date": "2026-09-01",
                "capacity": 12,
            },
            staff_headers(),
        ),
        201,
    )
    assert created["location_code"] == "BOS-09", created["location_code"]
