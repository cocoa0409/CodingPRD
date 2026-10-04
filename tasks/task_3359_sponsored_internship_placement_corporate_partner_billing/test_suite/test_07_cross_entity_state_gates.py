"""Cross-entity state gates: internship stipends and stipend period overlap."""
from test_helpers import (
    ApiErrorId,
    acceptance_payload,
    create_cohort,
    create_enrolled_student,
    create_stipend_statement,
    make_student_headers,
    setup_offered_placement,
    staff_headers,
    stipend_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

INTERNSHIP_PERIOD = {
    "phase": "INTERNSHIP",
    "period_start": "2026-11-02",
    "period_end": "2026-11-15",
    "hours_attended": 50,
    "hours_expected": 60,
    "behavior_incidents": 0,
}


def test_internship_stipend_requires_a_running_placement(api):
    """PRD §3.5: "An internship-phase statement additionally requires the student to
    be holding a placement at `ACCEPTED` or `ACTIVE`, because an internship stipend
    cannot be paid for a placement that is not running; otherwise the request is
    refused with `ERR_PARENT_STATE_CONFLICT` (409)."

    Design: Difficulty/cross_entity_state_dependency/internship_stipend_requires_accepted_or_active_placement
    """
    scenario = setup_offered_placement()
    assert scenario.placement["state"] == "OFFERED", scenario.placement["state"]

    response = api.create_stipend_statement(
        stipend_payload(scenario.student["id"], **INTERNSHIP_PERIOD), staff_headers()
    )

    validate_error(response, ApiErrorId.ERR_PARENT_STATE_CONFLICT)


def test_internship_stipend_succeeds_once_the_offer_is_accepted(api):
    """PRD §3.5: "An internship-phase statement additionally requires the student to
    be holding a placement at `ACCEPTED` or `ACTIVE`, because an internship stipend
    cannot be paid for a placement that is not running; otherwise the request is
    refused with `ERR_PARENT_STATE_CONFLICT` (409)."
    PRD §3.5: "Sixth, the total deduction is the sum of three parts:
    `gross_amount_cents` multiplied by 1 minus `attendance_ratio`, rounded half up;
    plus 15,000 cents when `attendance_ratio` is below 0.60; plus 7,500 cents when
    `behavior_incidents` is 3 or more."

    Design: Difficulty/cross_entity_state_dependency/internship_stipend_requires_accepted_or_active_placement
    """
    scenario = setup_offered_placement()

    placement = validate_success(
        api.accept_offer(
            scenario.placement["id"],
            acceptance_payload(),
            make_student_headers(scenario.student["id"]),
        ),
        200,
    )
    assert placement["state"] == "ACCEPTED", placement["state"]

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(scenario.student["id"], **INTERNSHIP_PERIOD), staff_headers()
        ),
        201,
    )
    assert data["status"] == "PENDING", data["status"]
    assert data["net_amount_cents"] == 68747, data["net_amount_cents"]
    assert data["contract_points_earned"] == 6, data["contract_points_earned"]


def test_stipend_period_sharing_the_last_day_is_refused(api):
    """PRD §3.5: "The period must not overlap an existing statement of the same
    student and phase whose `status` is `PENDING` or `PAID` — two inclusive periods
    overlap when they share at least one calendar day — and a violation is
    `ERR_STIPEND_PERIOD_OVERLAP` (409)"

    Design: Difficulty/resource_temporal_overlap/stipend_period_inclusive_day_overlap
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=126, hours_expected=140, behavior_incidents=0,
    )

    response = api.create_stipend_statement(
        stipend_payload(
            student["id"], period_start="2026-09-20", period_end="2026-10-04",
            hours_attended=126, hours_expected=140, behavior_incidents=0,
        ),
        staff_headers(),
    )

    validate_error(response, ApiErrorId.ERR_STIPEND_PERIOD_OVERLAP)


def test_stipend_period_starting_the_next_day_is_accepted(api):
    """PRD §3.5: "The period must not overlap an existing statement of the same
    student and phase whose `status` is `PENDING` or `PAID` — two inclusive periods
    overlap when they share at least one calendar day — and a violation is
    `ERR_STIPEND_PERIOD_OVERLAP` (409)"
    PRD §3.5: "Fifth, `attendance_deduction_cents` is `gross_amount_cents` multiplied
    by the absence ratio and divided by 10, rounded half up to a whole cent"

    Design: Difficulty/resource_temporal_overlap/stipend_period_inclusive_day_overlap
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=126, hours_expected=140, behavior_incidents=0,
    )

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                student["id"], period_start="2026-09-21", period_end="2026-10-04",
                hours_attended=126, hours_expected=140, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )
    assert data["status"] == "PENDING", data["status"]
    assert data["net_amount_cents"] == 34650, data["net_amount_cents"]

    listing = api.list_student_stipends(student["id"], staff_headers())
    statements, meta = validate_paginated(listing)
    assert meta["total_count"] == 2, meta
    assert len(statements) == 2, len(statements)
