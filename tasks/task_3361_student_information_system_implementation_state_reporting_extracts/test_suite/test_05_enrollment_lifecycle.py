"""Enrollment lifecycle: withdraw side effects, re-entry, truancy inference, and
the parallel absence-posture dimension."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_student_with_enrollment,
    get_student,
    post_unexcused_full_day_events,
    setup_base,
    validate_error,
    validate_success,
    withdraw_enrollment,
)

TEN_ABSENCE_DATES = [f"2026-09-{day:02d}T00:00:00Z" for day in range(1, 11)]


def test_withdraw_sets_exit_freezes_membership_and_inactivates_student(
        api, registrar_headers):
    """PRD §3.4: "Either way, withdrawal closes the segment: the `exit_date` is set,
    the days of the closing segment — counted half-open and intersected with the year
    window — are folded into `prior_segment_days`, and `membership_days`,
    `absence_rate`, both FTE variants, and `absence_posture` are recomputed."
    PRD §3.4: "If the student then holds no other `ACTIVE` enrollment, the student
    moves from `ENROLLED` to `INACTIVE`."

    Design: Corner/state_machines/withdraw_sets_exit_freezes_membership_and_inactivates_student
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])

    withdrawn = withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")
    assert withdrawn["exit_date"] == "2026-11-09T00:00:00Z"
    assert withdrawn["lifecycle"] == "WITHDRAWN"
    # Half-open [2026-08-01, 2026-11-09) is 100 days, folded into prior_segment_days.
    assert withdrawn["prior_segment_days"] == 100
    assert withdrawn["membership_days"] == 100
    assert withdrawn["fte_adm"] == pytest.approx(0.556, abs=1e-9)

    assert get_student(student["id"])["status"] == "INACTIVE"


def test_withdraw_already_withdrawn_enrollment_returns_not_active(api, registrar_headers):
    """PRD §3.4: "Withdrawal moves an `ACTIVE` enrollment to `WITHDRAWN` (from any
    other lifecycle, `ERR_ENROLLMENT_NOT_ACTIVE`)."

    Design: Corner/state_machines/withdraw_already_withdrawn_enrollment_returns_not_active
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")

    res = api.withdraw_enrollment(
        enrollment["id"], {"exit_date": "2026-12-01T00:00:00Z"}, registrar_headers)
    validate_error(res, ApiErrorId.ERR_ENROLLMENT_NOT_ACTIVE, expected_status=409)

    frozen = validate_success(api.get_enrollment(enrollment["id"], registrar_headers), 200)
    assert frozen["exit_date"] == "2026-11-09T00:00:00Z", \
        "the rejected second withdraw must not move the recorded exit_date"
    assert frozen["membership_days"] == 100, \
        "the rejected second withdraw must not recompute membership"


def test_posture_transitions_to_chronic_while_lifecycle_withdrawn(
        api, registrar_headers):
    """PRD §3.5: "Because `absence_posture` is an independent dimension of the
    enrollment, it moves freely in any direction — `CLEAR` ↔ `AT_RISK`, `AT_RISK` ↔
    `CHRONIC`, and direct `CLEAR` ↔ `CHRONIC` jumps — and it re-derives after every
    attendance post, every withdrawal, every re-entry, and every discipline approval
    or void."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_lifecycle_and_absence_dimensions
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    post_unexcused_full_day_events(enrollment["id"], TEN_ABSENCE_DATES)

    withdrawn = withdraw_enrollment(enrollment["id"], "2026-10-20T00:00:00Z")
    assert withdrawn["lifecycle"] == "WITHDRAWN"
    assert withdrawn["absence_weight_sum"] == pytest.approx(10.0, abs=1e-9)
    # Half-open [2026-08-01, 2026-10-20) is 80 days; 10.0 / 80 = 0.125 >= 0.10.
    assert withdrawn["membership_days"] == 80
    assert withdrawn["absence_posture"] == "CHRONIC", \
        "posture must be able to reach CHRONIC on the withdraw recompute"


def test_reenter_lengthens_membership_and_clears_posture(api, registrar_headers):
    """PRD §3.5: "A re-entry that lengthens membership can pull a `CHRONIC`
    enrollment back to `AT_RISK` or `CLEAR`, just as a voided suspension can."
    PRD §3.4: "Re-entry opens a fresh segment: `entry_date` becomes the
    `reentry_date`, `exit_date` returns to null, the accumulated `prior_segment_days`
    are retained, the derived quantities recompute, and an `INACTIVE` student returns
    to `ENROLLED`."

    Design: Difficulty/non_linear_state_machine/enrollment_parallel_lifecycle_and_absence_dimensions
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    post_unexcused_full_day_events(enrollment["id"], TEN_ABSENCE_DATES)
    withdraw_enrollment(enrollment["id"], "2026-10-20T00:00:00Z")
    assert get_student(student["id"])["status"] == "INACTIVE"

    res = api.reenter_enrollment(
        enrollment["id"], {"reentry_date": "2027-01-05T00:00:00Z"}, registrar_headers)
    reentered = validate_success(res, 200)
    assert reentered["lifecycle"] == "ACTIVE"
    assert reentered["exit_date"] is None
    # 80 prior days + half-open [2027-01-05, 2027-06-01) = 147 days.
    assert reentered["membership_days"] == 227
    assert reentered["absence_weight_sum"] == pytest.approx(10.0, abs=1e-9)
    # 10.0 / 227 = 0.0441 < 0.05 -> CLEAR.
    assert reentered["absence_posture"] == "CLEAR", \
        "the posture dimension recomputes independently of the lifecycle flip"

    assert get_student(student["id"])["status"] == "ENROLLED"


def _setup_truancy_enrollment(api, registrar_headers):
    """Base + one enrollment with three consecutive-day unexcused full-day absences
    on 2026-09-01..2026-09-03 (the spec's auto_withdraw_streak is 3)."""
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    post_unexcused_full_day_events(
        enrollment["id"],
        ["2026-09-01T00:00:00Z", "2026-09-02T00:00:00Z", "2026-09-03T00:00:00Z"],
    )
    return enrollment["id"]


def test_truancy_streak_infers_exit_date(api, registrar_headers):
    """PRD §3.5: "The inferred `exit_date` is the `attendance_date` of the streak's
    final event — the Nth day of that first qualifying run, where N is the configured
    streak length."

    Design: Difficulty/combinatorial_formula/truancy_streak_infers_exit_then_membership
    """
    enrollment_id = _setup_truancy_enrollment(api, registrar_headers)
    res = api.withdraw_enrollment(enrollment_id, {}, registrar_headers)
    withdrawn = validate_success(res, 200)
    assert withdrawn["exit_date"] == "2026-09-03T00:00:00Z", \
        "the third consecutive unexcused full-day absence dates the inferred exit"
    assert withdrawn["lifecycle"] == "WITHDRAWN"
    # Half-open [2026-08-01, 2026-09-03) is 33 days.
    assert withdrawn["membership_days"] == 33


def test_truancy_inferred_exit_excludes_event_on_exit_date(api, registrar_headers):
    """PRD §3.5: "The segment then closes half-open around that exit: membership
    recomputes with the exit exclusive, and `absence_weight_sum` counts only events
    whose `attendance_date` falls strictly before the exit — an event on the exit
    date itself is excluded."

    Design: Difficulty/combinatorial_formula/truancy_streak_infers_exit_then_membership
    """
    enrollment_id = _setup_truancy_enrollment(api, registrar_headers)
    res = api.withdraw_enrollment(enrollment_id, {}, registrar_headers)
    withdrawn = validate_success(res, 200)
    # Only the 09-01 and 09-02 events count; the 09-03 streak-completing event is
    # excluded by the half-open exit.
    assert withdrawn["absence_weight_sum"] == pytest.approx(2.0, abs=1e-9)
    # 2.0 / 33 = 0.0606 -> >= 0.05 and < 0.10.
    assert withdrawn["absence_posture"] == "AT_RISK"
