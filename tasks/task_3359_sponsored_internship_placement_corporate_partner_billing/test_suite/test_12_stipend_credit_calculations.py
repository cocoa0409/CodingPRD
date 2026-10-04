"""Calculation constants: the hours cap, the tuition cap, ratio precision, listing."""
from test_helpers import (
    assert_credit_grant,
    assert_stipend_statement,
    create_cohort,
    create_enrolled_student,
    create_stipend_statement,
    credit_grant_payload,
    setup_active_placement,
    staff_headers,
    stipend_payload,
    validate_paginated,
    validate_success,
)


def test_internship_hours_cap_clamps_expected_hours(api):
    """PRD §3.5: "Third, the billable hours are the week count multiplied by the
    smaller of the weekly hours and 25 — the weekly cap — so a 60-hour expectation
    over a 14-day period bills 50 hours rather than 60"
    PRD §3.5: "`contract_points_earned` is 6 points, plus 3 additional points when
    `attendance_ratio` is at least 0.95"

    Design: Corner/calculations/internship_hours_cap_clamps_expected_hours
    """
    scenario = setup_active_placement()

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                scenario.student["id"], phase="INTERNSHIP",
                period_start="2026-11-02", period_end="2026-11-15",
                hours_attended=60, hours_expected=60, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert data["gross_amount_cents"] == 82500, data["gross_amount_cents"]
    assert float(data["attendance_ratio"]) == 1.0000, data["attendance_ratio"]
    assert data["net_amount_cents"] == 82500, data["net_amount_cents"]
    assert data["contract_points_earned"] == 9, data["contract_points_earned"]
    assert_stipend_statement(data)


def test_tuition_credit_cap_applies_to_each_grant_before_summing(api):
    """PRD §3.8: "its own `tuition_credit_cents` is computed at creation as the
    smaller of `credit_hours` multiplied by 12,500 cents — $125 per credit hour — and
    a per-grant cap of 500,000 cents, that is, $5,000"
    PRD §3.8: "The grant starts at `status` `PENDING`"

    A 48-credit grant is worth 600,000 cents uncapped, so the cap is what stores
    500,000.

    Design: Corner/calculations/tuition_credit_cap_applied_per_grant
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])

    data = validate_success(
        api.create_credit_grant(credit_grant_payload(student["id"]), staff_headers()), 201
    )

    assert data["tuition_credit_cents"] == 500_000, data["tuition_credit_cents"]
    assert data["status"] == "PENDING", data["status"]
    assert_credit_grant(data)


def test_attendance_ratio_rounds_to_four_decimals(api):
    """PRD §3.5: "Third, `attendance_ratio` is `hours_attended` divided by
    `hours_expected`, rounded half up to 4 decimal places."
    PRD §3.5: "Fifth, `attendance_deduction_cents` is `gross_amount_cents` multiplied
    by the absence ratio and divided by 10, rounded half up to a whole cent"

    97 of 140 hours rounds to 0.6929, which drives the 1,075-cent deduction.

    Design: Corner/calculations/attendance_ratio_rounds_to_four_decimals
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                student["id"], period_start="2026-09-07", period_end="2026-09-20",
                hours_attended=97, hours_expected=140, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert float(data["attendance_ratio"]) == 0.6929, data["attendance_ratio"]
    assert data["gross_amount_cents"] == 35000, data["gross_amount_cents"]
    assert data["attendance_deduction_cents"] == 1075, data["attendance_deduction_cents"]
    assert data["net_amount_cents"] == 33925, data["net_amount_cents"]
    assert data["contract_points_earned"] == 3, data["contract_points_earned"]


def test_stipend_listing_honors_limit_and_total_count(api):
    """PRD §2.3: "The `meta` object of any list response carries `limit`, `offset`,
    `total_count` and `has_more`."

    Design: Corner/entities/stipend_listing_honors_limit_and_total_count
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    first = create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=126, hours_expected=140, behavior_incidents=0,
    )
    second = create_stipend_statement(
        student["id"], period_start="2026-09-21", period_end="2026-10-04",
        hours_attended=126, hours_expected=140, behavior_incidents=0,
    )

    statements, meta = validate_paginated(
        api.list_student_stipends(student["id"], staff_headers(), {"limit": 1, "offset": 0})
    )

    assert meta["total_count"] == 2, meta
    assert meta["has_more"] is True, meta
    assert meta["limit"] == 1, meta
    assert len(statements) == 1, statements
    assert statements[0]["id"] in (first["id"], second["id"]), statements
