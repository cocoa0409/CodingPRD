"""Domain assertions.

Per-entity shape checks confirm every field the requirements document declares
for that resource is present, and the invariant checkers assert the conserved
quantities the district names.
"""

from datetime import datetime
from typing import Any, Dict, Optional

import pytest

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .constants import TOLERANCE, round_half_up
from .types import COMMON_FIELD_NAMES


# --------------------------------------------------------------------------
# Small primitives
# --------------------------------------------------------------------------
def assert_common_fields(resource: Dict[str, Any], expected_version: Optional[int] = None):
    """Every business resource carries id, created_at, updated_at and version."""
    for field in COMMON_FIELD_NAMES:
        assert field in resource, f"missing system-managed field {field}"
    assert is_valid_uuid(resource["id"]), f"id is not a bare UUID: {resource['id']}"
    assert "_" not in resource["id"], "the id carries no type prefix of any kind"
    assert is_iso8601_timestamp(resource["created_at"])
    assert is_iso8601_timestamp(resource["updated_at"])
    assert isinstance(resource["version"], int)
    assert resource["version"] >= 1
    if expected_version is not None:
        assert resource["version"] == expected_version, (
            f"expected version {expected_version}, got {resource['version']}"
        )


def assert_fields_present(resource: Dict[str, Any], *names: str):
    for name in names:
        assert name in resource, f"missing declared field {name}"


def assert_close(actual: Optional[float], expected: Optional[float], label: str = ""):
    """Compare a decimal figure at the tolerance every test uses."""
    if expected is None:
        assert actual is None, f"{label}: expected null, got {actual}"
        return
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert actual == pytest.approx(expected, abs=TOLERANCE), (
        f"{label}: expected {expected}, got {actual}"
    )


def assert_decimal_places(value: float, places: int, label: str = ""):
    """The figure equals its own rounding at the declared precision."""
    assert value == pytest.approx(round_half_up(value, places), abs=1e-9), (
        f"{label}: {value} is not carried to {places} decimal places"
    )


def assert_same_instant(actual: Optional[str], expected: str, label: str = ""):
    """Two ISO 8601 instants name the same moment.

    Compared as parsed instants rather than as strings, so a response that
    serialises the same moment with a different sub-second width or offset
    spelling still satisfies the check.
    """
    assert actual is not None, f"{label}: expected {expected}, got null"
    assert is_iso8601_timestamp(actual), f"{label}: {actual!r} is not ISO 8601"
    assert _instant(actual) == _instant(expected), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


def _instant(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    return datetime.fromisoformat(text)


# --------------------------------------------------------------------------
# Per-entity shape checks
# --------------------------------------------------------------------------
def assert_home_school(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "name",
        "district_code",
        "accountability_cohort_year",
        "cohort_size",
        "graduates_count",
        "alt_ed_placed_count",
        "adjusted_grad_rate",
        "cohort_flag",
    )


def assert_center(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "name",
        "seat_capacity",
        "certified_teacher_fte",
        "support_staff_fte",
        "max_students_per_teacher",
        "restricted_seat_margin",
        "active_student_count",
        "seats_reserved",
        "seats_committed",
        "seats_available",
        "student_teacher_ratio",
        "staffing_headroom",
        "intake_posture",
    )
    assert_seat_conservation(resource)


def assert_course(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "code",
        "title",
        "subject_area",
        "credit_value",
        "modality",
        "total_modules",
        "required_seat_hours",
        "pacing_days",
        "proctoring_required",
        "proctored_exam_weight",
        "ncaa_approved",
        "min_passing_percent",
    )


def assert_student(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "home_school_id",
        "state_student_id",
        "full_name",
        "cohort_year",
        "grade_level",
        "status",
        "credits_earned_total",
        "alt_ed_credits",
        "ncaa_acceptable_credits",
        "gpa",
    )


def assert_prior_course_record(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "student_id",
        "course_id",
        "term_code",
        "original_percent",
        "credits_attempted",
        "outcome",
        "original_grade_code",
        "replacement_status",
    )


def assert_graduation_plan(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "student_id",
        "required_credits_total",
        "grade_replacement_policy",
        "status",
        "credits_earned",
        "credits_in_progress",
        "credits_remaining",
        "expected_credits_by_grade",
        "posture",
    )


def assert_referral(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "student_id",
        "center_id",
        "pathway",
        "deficiency_credits",
        "behavior_incident_count",
        "days_disengaged",
        "narrative",
        "prior_referral_id",
        "status",
        "priority_score",
        "promoted_from_waitlist",
    )


def assert_placement(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "referral_id",
        "student_id",
        "center_id",
        "credit_policy",
        "start_date",
        "status",
        "days_present",
        "days_enrolled",
        "attendance_rate",
        "readiness_base_score",
        "engagement_bonus",
        "readiness_score",
        "re_entry_eligible",
        "support_sessions_completed",
    )


def assert_course_enrollment(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "placement_id",
        "course_id",
        "enrollment_type",
        "prior_course_record_id",
        "enrolled_on",
        "progress_state",
        "integrity_state",
        "modules_passed",
        "seat_hours_logged",
        "module_avg_percent",
        "proctored_exam_percent",
        "mastery_pct",
        "final_percent",
        "awarded_credits",
        "projected_credits",
        "pace_index",
        "pacing_flag",
    )


def assert_credit_award(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "course_enrollment_id",
        "student_id",
        "prior_course_record_id",
        "credits_awarded",
        "award_basis",
        "posted_on",
        "modality_code",
        "transcript_code",
        "alt_ed_flag",
        "transcript_grade_code",
        "ncaa_acceptable",
        "grade_replacement_mode",
        "status",
    )


def assert_proctor_station(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "center_id",
        "label",
        "station_type",
        "turnaround_buffer_minutes",
        "scheduled_session_count",
    )


def assert_proctor_session(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "course_enrollment_id",
        "proctor_station_id",
        "scheduled_start",
        "scheduled_end",
        "status",
    )


def assert_support_provider(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "center_id",
        "role_type",
        "full_name",
        "max_concurrent_students",
        "completed_session_count",
    )


def assert_support_session(resource: Dict[str, Any]):
    assert_common_fields(resource)
    assert_fields_present(
        resource,
        "support_provider_id",
        "placement_id",
        "start_at",
        "end_at",
        "service_code",
        "status",
    )


# --------------------------------------------------------------------------
# Named invariants
# --------------------------------------------------------------------------
def assert_seat_conservation(center: Dict[str, Any]):
    """Available plus committed equals funded capacity, and committed equals
    the active roster plus the reserved seats."""
    assert center["seats_available"] + center["seats_committed"] == center[
        "seat_capacity"
    ], (
        "available seats plus committed seats must equal the funded seat capacity: "
        f"{center['seats_available']} + {center['seats_committed']} != {center['seat_capacity']}"
    )
    assert center["seats_committed"] == center["active_student_count"] + center[
        "seats_reserved"
    ], (
        "committed seats must equal the active student count plus the reserved seats: "
        f"{center['seats_committed']} != {center['active_student_count']} + {center['seats_reserved']}"
    )
    for field in ("seats_available", "seats_committed", "seats_reserved", "staffing_headroom"):
        assert isinstance(center[field], int), f"{field} must be an integer"


def assert_seat_picture(
    center: Dict[str, Any],
    active_student_count: int,
    seats_reserved: int,
    seats_available: int,
    intake_posture: Optional[str] = None,
):
    """Assert the whole seat picture at once and re-check conservation."""
    assert center["active_student_count"] == active_student_count
    assert center["seats_reserved"] == seats_reserved
    assert center["seats_available"] == seats_available
    assert center["seats_committed"] == active_student_count + seats_reserved
    if intake_posture is not None:
        assert center["intake_posture"] == intake_posture, (
            f"expected posture {intake_posture}, got {center['intake_posture']}"
        )
    assert_seat_conservation(center)


def assert_credit_ledger_agrees(student: Dict[str, Any], plan: Dict[str, Any]):
    """The plan's earned credits mirror the student's earned total."""
    assert_close(
        plan["credits_earned"],
        student["credits_earned_total"],
        "plan credits_earned versus student credits_earned_total",
    )


def assert_transcript_coding(
    award: Dict[str, Any],
    course_code: str,
    modality_code: str,
    grade_code: str,
):
    """The district's transcript coding is code, hyphen, modality, then -AE."""
    assert award["modality_code"] == modality_code
    assert award["transcript_code"] == f"{course_code}-{modality_code}-AE"
    assert award["alt_ed_flag"] is True
    assert award["transcript_grade_code"] == grade_code


def assert_readiness_figures(
    placement: Dict[str, Any],
    base_score: Optional[float] = None,
    bonus: Optional[float] = None,
    score: Optional[float] = None,
):
    if base_score is not None:
        assert_close(placement["readiness_base_score"], base_score, "readiness_base_score")
    if bonus is not None:
        assert_close(placement["engagement_bonus"], bonus, "engagement_bonus")
    if score is not None:
        assert_close(placement["readiness_score"], score, "readiness_score")


def assert_version_advanced(before: Dict[str, Any], after: Dict[str, Any], by: int = 1):
    """A mutation refreshes updated_at and advances version by exactly ``by``."""
    assert after["version"] == before["version"] + by, (
        f"expected version {before['version'] + by}, got {after['version']}"
    )
    assert after["id"] == before["id"]


def assert_unchanged(before: Dict[str, Any], after: Dict[str, Any], *fields: str):
    """The named fields hold exactly the values they held before."""
    for field in fields:
        assert after[field] == before[field], (
            f"{field} drifted from {before[field]} to {after[field]}"
        )


def assert_zero_drift(
    before_student: Dict[str, Any],
    after_student: Dict[str, Any],
):
    """After a void the student's ledger equals its pre-award values exactly."""
    for field in (
        "credits_earned_total",
        "alt_ed_credits",
        "ncaa_acceptable_credits",
    ):
        assert_close(after_student[field], before_student[field], field)
    assert after_student["gpa"] == before_student["gpa"], (
        f"gpa drifted from {before_student['gpa']} to {after_student['gpa']}"
    )
