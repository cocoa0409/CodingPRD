"""Payload factories.

Each factory returns a plain dictionary carrying valid values for every
required input, and accepts keyword overrides.  Numeric inputs are emitted as
JSON numbers, never as strings.  Unique identifiers are generated from a
process-wide counter so two calls in the same test never collide on a
uniqueness rung.
"""

import itertools
from typing import Any, Dict, Optional

from .constants import CLOCK_STARTUP_DATE
from .types import (
    CreditPolicy,
    EnrollmentType,
    GradeReplacementPolicy,
    Modality,
    Pathway,
    PriorOutcome,
    ProviderRoleType,
    ServiceCode,
    StationType,
    SubjectArea,
)

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix unique within the process."""
    return f"{next(_counter):04d}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``None`` removes the key entirely so a test
    can exercise an omitted optional input."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning "leave this key out of the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


#: Pass ``OMIT`` as an override to drop a key from the generated payload.
OMIT = _Omit()
_OMIT = OMIT


# --------------------------------------------------------------------------
# Setup entities
# --------------------------------------------------------------------------
def home_school_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "name": f"North High {suffix}",
            "district_code": f"NHS-{suffix}",
            "accountability_cohort_year": 2026,
        },
        overrides,
    )


def center_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "name": f"Cedar AEC {suffix}",
            "seat_capacity": 10,
            "certified_teacher_fte": 4.00,
            "support_staff_fte": 2.00,
            "max_students_per_teacher": 12,
        },
        overrides,
    )


def staffing_payload(expected_center_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"expected_center_version": expected_center_version}, overrides)


def course_payload(**overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "code": f"CRS{suffix}",
            "title": f"Algebra One {suffix}",
            "subject_area": SubjectArea.MATH.value,
            "credit_value": 1.00,
            "modality": Modality.PACKET.value,
            "total_modules": 8,
            "required_seat_hours": 60.00,
            "pacing_days": 40,
            "proctoring_required": False,
            "ncaa_approved": False,
        },
        overrides,
    )


def online_course_payload(**overrides: Any) -> Dict[str, Any]:
    """An ONLINE course, which the catalogue requires to be proctored."""
    base = course_payload(
        modality=Modality.ONLINE.value,
        proctoring_required=True,
    )
    return _merge(base, overrides)


def blended_course_payload(**overrides: Any) -> Dict[str, Any]:
    base = course_payload(
        modality=Modality.BLENDED.value,
        proctoring_required=True,
    )
    return _merge(base, overrides)


def student_payload(home_school_id: str, **overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "home_school_id": home_school_id,
            "state_student_id": f"S-{suffix}",
            "full_name": f"Ola Pereira {suffix}",
            "cohort_year": 2027,
            "grade_level": 11,
        },
        overrides,
    )


def prior_course_record_payload(
    student_id: str, course_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "course_id": course_id,
            "term_code": "2025SP",
            "original_percent": 42.00,
            "credits_attempted": 1.00,
            "outcome": PriorOutcome.FAILED.value,
        },
        overrides,
    )


def graduation_plan_payload(student_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "required_credits_total": 24.00,
            "grade_replacement_policy": GradeReplacementPolicy.REPLACE_ON_RECOVERY.value,
        },
        overrides,
    )


def proctor_station_payload(center_id: str, **overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "center_id": center_id,
            "label": f"Room {suffix}",
            "station_type": StationType.COMPUTER.value,
        },
        overrides,
    )


def support_provider_payload(center_id: str, **overrides: Any) -> Dict[str, Any]:
    suffix = unique_suffix()
    return _merge(
        {
            "center_id": center_id,
            "role_type": ProviderRoleType.COUNSELOR.value,
            "full_name": f"Dana Reyes {suffix}",
            "max_concurrent_students": 2,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Referral flow
# --------------------------------------------------------------------------
def referral_payload(student_id: str, center_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "center_id": center_id,
            "pathway": Pathway.CREDIT_DEFICIENCY.value,
            "deficiency_credits": 4.00,
            "behavior_incident_count": 1,
            "days_disengaged": 6,
            "narrative": "Student is four credits behind and needs a recovery seat.",
        },
        overrides,
    )


def screen_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"screening_note": "Intake packet reviewed."}, overrides)


def request_info_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"missing_items": "Latest transcript and attendance ledger."}, overrides)


def resubmit_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"narrative": "Updated intake packet supplied by the counsellor."}, overrides
    )


def offer_payload(expected_center_version: int, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "expected_center_version": expected_center_version,
            "offer_valid_days": 10,
        },
        overrides,
    )


def waitlist_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"waitlist_reason": "No funded seat available this week."}, overrides)


def deny_referral_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"denial_reason": "Case does not meet placement criteria."}, overrides)


def withdraw_offer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"screening_note": "Offer withdrawn at the family's request."}, overrides)


def accept_offer_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "credit_policy": CreditPolicy.SEAT_TIME.value,
            "start_date": CLOCK_STARTUP_DATE,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Placement flow
# --------------------------------------------------------------------------
def attendance_payload(
    days_present_delta: int, days_enrolled_delta: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "days_present_delta": days_present_delta,
            "days_enrolled_delta": days_enrolled_delta,
        },
        overrides,
    )


def request_re_entry_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"target_re_entry_date": "2026-09-01"}, overrides)


def approve_re_entry_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"actual_re_entry_date": "2026-09-02"}, overrides)


def deny_re_entry_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"re_entry_denial_reason": "Home school requests one more grading period."},
        overrides,
    )


def exit_placement_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"exit_reason": "Family relocated out of district."}, overrides)


# --------------------------------------------------------------------------
# Enrollment flow
# --------------------------------------------------------------------------
def new_credit_enrollment_payload(
    placement_id: str, course_id: str, expected_placement_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "placement_id": placement_id,
            "course_id": course_id,
            "enrollment_type": EnrollmentType.NEW_CREDIT.value,
            "expected_placement_version": expected_placement_version,
        },
        overrides,
    )


def recovery_enrollment_payload(
    placement_id: str,
    course_id: str,
    prior_course_record_id: Optional[str],
    expected_placement_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "placement_id": placement_id,
        "course_id": course_id,
        "enrollment_type": EnrollmentType.CREDIT_RECOVERY.value,
        "expected_placement_version": expected_placement_version,
    }
    if prior_course_record_id is not None:
        payload["prior_course_record_id"] = prior_course_record_id
    return _merge(payload, overrides)


def progress_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({}, overrides)


def submit_for_award_payload(final_percent: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"final_percent": final_percent}, overrides)


def award_credit_payload(
    expected_graduation_plan_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"expected_graduation_plan_version": expected_graduation_plan_version},
        overrides,
    )


def deny_award_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {"denial_reason": "Submitted work does not evidence the final percent."},
        overrides,
    )


def flag_integrity_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"integrity_incident_code": "PLAGIARISM_REVIEW"}, overrides)


def resolve_integrity_payload(resolution: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "resolution": resolution,
            "integrity_resolution_note": "Adjudicated by the district office.",
        },
        overrides,
    )


def void_award_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason": "Posted against the wrong term."}, overrides)


# --------------------------------------------------------------------------
# Proctoring and support sessions
# --------------------------------------------------------------------------
def proctor_session_payload(
    course_enrollment_id: str,
    proctor_station_id: str,
    scheduled_start: str = "2026-08-10T09:00:00.000Z",
    scheduled_end: str = "2026-08-10T11:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "course_enrollment_id": course_enrollment_id,
            "proctor_station_id": proctor_station_id,
            "scheduled_start": scheduled_start,
            "scheduled_end": scheduled_end,
        },
        overrides,
    )


def complete_proctor_session_payload(
    score_percent: float, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"score_percent": score_percent}, overrides)


def no_show_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"no_show_note": "Student did not appear for the exam slot."}, overrides)


def support_session_payload(
    support_provider_id: str,
    placement_id: str,
    start_at: str = "2026-08-10T13:00:00.000Z",
    end_at: str = "2026-08-10T14:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "support_provider_id": support_provider_id,
            "placement_id": placement_id,
            "start_at": start_at,
            "end_at": end_at,
            "service_code": ServiceCode.ACADEMIC_COUNSELING.value,
        },
        overrides,
    )


def complete_support_session_payload(
    minutes_delivered: int = 60, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"minutes_delivered": minutes_delivered}, overrides)


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)
