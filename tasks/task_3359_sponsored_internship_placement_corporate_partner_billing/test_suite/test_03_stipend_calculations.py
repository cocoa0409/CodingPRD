"""Stipend arithmetic — attendance-driven deductions in both program phases.

The L&D deduction is strictly proportional to the absence ratio (PRD §3.5),
while the internship deduction adds an exact-threshold floor penalty.
"""
from test_helpers import (
    assert_stipend_statement,
    create_cohort,
    create_enrolled_student,
    create_stipend_statement,
    pay_stipend_statement,
    read_student,
    setup_active_placement,
    staff_headers,
    stipend_payload,
    validate_success,
)


def test_lnd_deduction_is_proportional_to_the_absence_ratio(api):
    """PRD §3.5: "Fifth, `attendance_deduction_cents` is `gross_amount_cents`
    multiplied by the absence ratio and divided by 10, rounded half up to a whole
    cent"
    PRD §3.5: "an absence ratio of exactly 0.1000 on a 35,000-cent period deducts
    350 cents rather than a flat tenth of the gross"

    Design: Difficulty/dual_variant_calc/lnd_stipend_absence_ratio_versus_absence_days
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                student["id"], period_start="2026-09-07", period_end="2026-09-20",
                hours_attended=126, hours_expected=140, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert float(data["attendance_ratio"]) == 0.9000, data["attendance_ratio"]
    assert data["gross_amount_cents"] == 35000, data["gross_amount_cents"]
    assert data["attendance_deduction_cents"] == 350, data["attendance_deduction_cents"]
    assert data["net_amount_cents"] == 34650, data["net_amount_cents"]
    assert data["contract_points_earned"] == 3, data["contract_points_earned"]
    assert_stipend_statement(data)


def test_lnd_deduction_scales_with_a_smaller_absence_ratio(api):
    """PRD §3.5: "Third, `attendance_ratio` is `hours_attended` divided by
    `hours_expected`, rounded half up to 4 decimal places."
    PRD §3.5: "Eighth, `contract_points_earned` is 3 points, plus 2 additional points
    when `attendance_ratio` is at least 0.95."

    A 0.9500 ratio halves the absence ratio to 0.0500 and so halves the deduction
    to 175 cents on the same 35,000-cent period.

    Design: Difficulty/dual_variant_calc/lnd_stipend_absence_ratio_versus_absence_days
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                student["id"], period_start="2026-09-21", period_end="2026-10-04",
                hours_attended=133, hours_expected=140, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert float(data["attendance_ratio"]) == 0.9500, data["attendance_ratio"]
    assert data["gross_amount_cents"] == 35000, data["gross_amount_cents"]
    assert data["attendance_deduction_cents"] == 175, data["attendance_deduction_cents"]
    assert data["net_amount_cents"] == 34825, data["net_amount_cents"]
    assert data["contract_points_earned"] == 5, data["contract_points_earned"]


def test_internship_stipend_escapes_the_floor_at_exactly_sixty_percent(api):
    """PRD §3.5: "Sixth, the total deduction is the sum of three parts:
    `gross_amount_cents` multiplied by 1 minus `attendance_ratio`, rounded half up;
    plus 15,000 cents when `attendance_ratio` is below 0.60; plus 7,500 cents when
    `behavior_incidents` is 3 or more."
    PRD §3.5: "Third, the billable hours are the week count multiplied by the smaller
    of the weekly hours and 25 — the weekly cap — so a 60-hour expectation over a
    14-day period bills 50 hours rather than 60."

    Design: Difficulty/boundary_precision_check/internship_attendance_floor_at_exactly_sixty_percent
    """
    scenario = setup_active_placement()

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                scenario.student["id"], phase="INTERNSHIP",
                period_start="2026-11-02", period_end="2026-11-15",
                hours_attended=36, hours_expected=60, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert float(data["attendance_ratio"]) == 0.6000, data["attendance_ratio"]
    assert data["gross_amount_cents"] == 82500, data["gross_amount_cents"]
    assert data["attendance_deduction_cents"] == 33000, data["attendance_deduction_cents"]
    assert data["net_amount_cents"] == 49500, data["net_amount_cents"]
    assert_stipend_statement(data)


def test_internship_stipend_incurs_the_floor_below_sixty_percent(api):
    """PRD §3.5: "plus 15,000 cents when `attendance_ratio` is below 0.60"
    PRD §3.5: "Seventh, `net_amount_cents` is `gross_amount_cents` minus that total
    deduction, floored at zero."

    A 0.5833 ratio adds the flat 15,000-cent floor to the 34,378-cent proportional
    part, so the two statements differ by the floor plus the 1,378-cent
    proportional difference.

    Design: Difficulty/boundary_precision_check/internship_attendance_floor_at_exactly_sixty_percent
    """
    scenario = setup_active_placement()

    data = validate_success(
        api.create_stipend_statement(
            stipend_payload(
                scenario.student["id"], phase="INTERNSHIP",
                period_start="2026-11-16", period_end="2026-11-29",
                hours_attended=35, hours_expected=60, behavior_incidents=0,
            ),
            staff_headers(),
        ),
        201,
    )

    assert float(data["attendance_ratio"]) == 0.5833, data["attendance_ratio"]
    assert data["gross_amount_cents"] == 82500, data["gross_amount_cents"]
    assert data["attendance_deduction_cents"] == 49378, data["attendance_deduction_cents"]
    assert data["net_amount_cents"] == 33122, data["net_amount_cents"]


def test_voiding_a_pending_statement_leaves_student_totals_untouched(api):
    """PRD §3.5: "A voided statement stops contributing to every student total and to
    the cohort's `awarded_points`"
    PRD §3.5: "Payment credits the student's `total_stipend_paid_cents` with the
    statement's `net_amount_cents` and adds the statement's `contract_points_earned`
    to `lifetime_contract_points`."

    Design: Difficulty/compensating_invariant/student_stipend_total_restored_by_statement_void
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    paid = create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=98, hours_expected=140, behavior_incidents=4,
    )
    pay_stipend_statement(paid["id"])
    before = read_student(student["id"])
    assert before["total_stipend_paid_cents"] == 28950, before["total_stipend_paid_cents"]
    assert before["lifetime_contract_points"] == 3, before["lifetime_contract_points"]

    pending = create_stipend_statement(
        student["id"], period_start="2026-09-21", period_end="2026-10-04",
        hours_attended=133, hours_expected=140, behavior_incidents=0,
    )
    validate_success(
        api.void_stipend_statement(
            pending["id"], staff_headers(), {"reason": "Attendance sheet was entered twice"}
        ),
        200,
    )

    after = read_student(student["id"])
    assert after["total_stipend_paid_cents"] == before["total_stipend_paid_cents"], (
        after["total_stipend_paid_cents"]
    )
    assert after["lifetime_contract_points"] == before["lifetime_contract_points"], (
        after["lifetime_contract_points"]
    )


def test_voided_statement_never_enters_the_student_totals(api):
    """PRD §3.5: "A voided statement stops contributing to every student total and to
    the cohort's `awarded_points`"

    The voided statement keeps its own computed 34,825-cent net amount, which is
    exactly the money that never reached the student.

    Design: Difficulty/compensating_invariant/student_stipend_total_restored_by_statement_void
    """
    cohort = create_cohort()
    student = create_enrolled_student(cohort["id"])
    paid = create_stipend_statement(
        student["id"], period_start="2026-09-07", period_end="2026-09-20",
        hours_attended=98, hours_expected=140, behavior_incidents=4,
    )
    pay_stipend_statement(paid["id"])
    pending = create_stipend_statement(
        student["id"], period_start="2026-09-21", period_end="2026-10-04",
        hours_attended=133, hours_expected=140, behavior_incidents=0,
    )

    data = validate_success(
        api.void_stipend_statement(pending["id"], staff_headers(), {"reason": "Duplicate period"}),
        200,
    )

    assert data["status"] == "VOID", data["status"]
    assert data["net_amount_cents"] == 34825, data["net_amount_cents"]
    student_now = read_student(student["id"])
    assert student_now["total_stipend_paid_cents"] == 28950, student_now["total_stipend_paid_cents"]
    assert student_now["lifetime_contract_points"] == 3, student_now["lifetime_contract_points"]
