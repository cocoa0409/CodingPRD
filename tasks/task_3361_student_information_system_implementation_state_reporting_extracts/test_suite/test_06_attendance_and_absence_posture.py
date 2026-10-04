"""Attendance event immutability and the absence-posture chronic boundary."""
import pytest

from test_helpers import (
    assert_attendance_event,
    create_student,
    create_student_with_enrollment,
    post_attendance_event,
    post_unexcused_full_day_events,
    setup_base,
    validate_success,
    withdraw_enrollment,
)


def test_attendance_event_response_has_no_version_or_update_surface(
        api, registrar_headers):
    """PRD §2.5: "One entity is the exception. An `AttendanceEvent` is an immutable
    ledger entry: it carries `id` and `created_at` only, and both `updated_at` and
    `version` are absent — an attendance mark is never modified after posting, and
    every derived quantity it influences is recomputed onto its owning enrollment
    instead."
    PRD §3.5: "A successful post persists the mapped `state_attendance_code`, the
    `absence_weight` (0.0, 0.5, or 1.0), and the `is_excused` flag onto the immutable
    `AttendanceEvent`".

    Design: Corner/entities/attendance_event_response_has_no_version_or_update_surface
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])

    res = api.post_attendance_event(
        enrollment["id"],
        {"attendance_date": "2026-09-02T00:00:00Z", "raw_code": "U"},
        registrar_headers,
    )
    assert res.status_code == 201, f"expected 201, got {res.status_code}: {res.text}"
    event = validate_success(res, 201)
    assert_attendance_event(event)
    assert event["state_attendance_code"] == "S_ABS_U"
    assert event["absence_weight"] == pytest.approx(1.0, abs=1e-9)
    assert event["is_excused"] is False
    assert event["enrollment_id"] == enrollment["id"]


def test_rate_exactly_at_chronic_threshold_is_chronic(api, registrar_headers):
    """PRD §3.5: "a rate at or above the spec's `chronic_absence_threshold` is
    `CHRONIC` — the comparison is inclusive, so a rate of exactly the threshold is
    chronic — a rate at or above 0.05 but below the chronic threshold is `AT_RISK`,
    and anything below 0.05 is `CLEAR`."

    Design: Difficulty/boundary_precision_check/chronic_threshold_exact_rate_boundary
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    post_unexcused_full_day_events(
        enrollment["id"], [f"2026-09-{day:02d}T00:00:00Z" for day in range(1, 11)])

    withdrawn = withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")
    assert withdrawn["absence_weight_sum"] == pytest.approx(10.0, abs=1e-9)
    assert withdrawn["membership_days"] == 100
    # 10.0 / 100 = 0.10 exactly; the >= boundary includes the threshold.
    assert withdrawn["absence_posture"] == "CHRONIC"


def test_rate_just_below_chronic_threshold_is_at_risk(api, registrar_headers):
    """PRD §3.5: "a rate at or above the spec's `chronic_absence_threshold` is
    `CHRONIC` — the comparison is inclusive, so a rate of exactly the threshold is
    chronic — a rate at or above 0.05 but below the chronic threshold is `AT_RISK`,
    and anything below 0.05 is `CLEAR`."

    Design: Difficulty/boundary_precision_check/chronic_threshold_exact_rate_boundary
    """
    district, spec, year = setup_base()
    student, enrollment = create_student_with_enrollment(district["id"], year["id"])
    # Nine full-day unexcused absences plus one half-day absence: weight 9.5.
    post_unexcused_full_day_events(
        enrollment["id"], [f"2026-09-{day:02d}T00:00:00Z" for day in range(1, 10)])
    post_attendance_event(enrollment["id"], "2026-09-10T00:00:00Z", "H")

    withdrawn = withdraw_enrollment(enrollment["id"], "2026-11-09T00:00:00Z")
    assert withdrawn["absence_weight_sum"] == pytest.approx(9.5, abs=1e-9)
    assert withdrawn["membership_days"] == 100
    # 9.5 / 100 = 0.095: below the 0.10 chronic threshold, at or above 0.05.
    assert withdrawn["absence_posture"] == "AT_RISK"
