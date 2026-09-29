"""Request payload factories.

Every factory returns a payload that satisfies the contract's shape rules, so a
test may override exactly the one field it is exercising and leave the rest
valid.  Hours, scores and thresholds are emitted as JSON numbers, dates as
``YYYY-MM-DD`` strings and instants as full second-precision instants, matching
the declared precision of each field.
"""
import itertools
from typing import Any, Dict, List, Optional

from .constants import (
    CLOCK_EPOCH,
    DOR_ACCEPTABLE_RATING,
)
from .types import DOR_DIMENSIONS

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short suffix that keeps unique identifiers distinct within one test."""
    return f"{next(_counter):04d}"


# ---------------------------------------------------------------------------
# Curriculum topics
# ---------------------------------------------------------------------------
TOPIC_LAW = "LAW"
TOPIC_FIREARMS = "FIREARMS"
TOPIC_DRIVING = "DRIVING"
TOPIC_ETHICS = "ETHICS"


def topic_requirement(topic_code: str = TOPIC_LAW, required_hours: float = 4.0,
                      exam_required: bool = True) -> Dict[str, Any]:
    return {
        "topic_code": topic_code,
        "required_hours": required_hours,
        "exam_required": exam_required,
    }


def certification_standard_payload(
    code: Optional[str] = None,
    state_code: str = "CA",
    min_total_hours: float = 4.0,
    min_passing_score: float = 70.0,
    max_remediation_attempts: int = 2,
    max_absence_hours: float = 4.0,
    topic_requirements: Optional[List[Dict[str, Any]]] = None,
    fitness_event_floor_points: Optional[int] = None,
    fitness_pass_score: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code or f"POST-STD-{unique_suffix()}",
        "state_code": state_code,
        "min_total_hours": min_total_hours,
        "min_passing_score": min_passing_score,
        "max_remediation_attempts": max_remediation_attempts,
        "max_absence_hours": max_absence_hours,
        "topic_requirements": (
            topic_requirements if topic_requirements is not None
            else [topic_requirement()]
        ),
    }
    if fitness_event_floor_points is not None:
        payload["fitness_event_floor_points"] = fitness_event_floor_points
    if fitness_pass_score is not None:
        payload["fitness_pass_score"] = fitness_pass_score
    return payload


def academy_class_payload(certification_standard_id: str,
                          class_code: Optional[str] = None,
                          start_date: str = "2026-08-03",
                          planned_seats: int = 20) -> Dict[str, Any]:
    return {
        "certification_standard_id": certification_standard_id,
        "class_code": class_code or f"CLASS-{unique_suffix()}",
        "start_date": start_date,
        "planned_seats": planned_seats,
    }


def recruit_payload(academy_class_id: str,
                    applicant_number: Optional[str] = None,
                    full_name: str = "Dana Ortiz",
                    date_of_birth: str = "1998-04-17",
                    age_bracket: str = "AGE_20_29") -> Dict[str, Any]:
    return {
        "academy_class_id": academy_class_id,
        "applicant_number": applicant_number or f"APP-{unique_suffix()}",
        "full_name": full_name,
        "date_of_birth": date_of_birth,
        "age_bracket": age_bracket,
    }


def instructor_payload(badge_number: Optional[str] = None,
                       full_name: str = "Sgt. Rae Lindqvist") -> Dict[str, Any]:
    return {
        "badge_number": badge_number or f"BDG-{unique_suffix()}",
        "full_name": full_name,
    }


def certify_instructor_payload(
    certification_expires_at: str = "2027-08-01T00:00:00Z",
    authorized_topic_codes: Optional[List[str]] = None,
    fto_certified: bool = False,
) -> Dict[str, Any]:
    return {
        "certification_expires_at": certification_expires_at,
        "authorized_topic_codes": (
            authorized_topic_codes if authorized_topic_codes is not None
            else [TOPIC_LAW]
        ),
        "fto_certified": fto_certified,
    }


def revoke_certification_payload(reason: str = "Integrity investigation sustained") -> Dict[str, Any]:
    return {"reason": reason}


def lesson_plan_payload(instructor_id: str, topic_code: str = TOPIC_LAW,
                        title: str = "Constitutional Law Fundamentals",
                        contact_hours: float = 2.0) -> Dict[str, Any]:
    return {
        "instructor_id": instructor_id,
        "topic_code": topic_code,
        "title": title,
        "contact_hours": contact_hours,
    }


def lesson_plan_revision_payload(expected_lesson_plan_version: int,
                                 contact_hours: float = 3.0,
                                 revision_notes: str = "Expanded case law module") -> Dict[str, Any]:
    return {
        "expected_lesson_plan_version": expected_lesson_plan_version,
        "contact_hours": contact_hours,
        "revision_notes": revision_notes,
    }


def request_revision_payload(reviewer_notes: str = "Add a practical exercise") -> Dict[str, Any]:
    return {"reviewer_notes": reviewer_notes}


def course_session_payload(academy_class_id: str, lesson_plan_id: str,
                           instructor_id: str, room_code: str = "ROOM-A",
                           starts_at: str = "2026-08-03T09:00:00Z",
                           ends_at: str = "2026-08-03T11:00:00Z",
                           min_enrollment: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "academy_class_id": academy_class_id,
        "lesson_plan_id": lesson_plan_id,
        "instructor_id": instructor_id,
        "room_code": room_code,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if min_enrollment is not None:
        payload["min_enrollment"] = min_enrollment
    return payload


def attendance_payload(recruit_id: str, status: str = "PRESENT",
                       present_hours: float = 2.0) -> Dict[str, Any]:
    return {
        "recruit_id": recruit_id,
        "status": status,
        "present_hours": present_hours,
    }


def void_delivery_payload(reason: str = "Instructor credential audit finding") -> Dict[str, Any]:
    return {"reason": reason}


def examination_payload(recruit_id: str, topic_code: str = TOPIC_LAW) -> Dict[str, Any]:
    return {"recruit_id": recruit_id, "topic_code": topic_code}


def grade_payload(raw_score: float = 80.0) -> Dict[str, Any]:
    return {"raw_score": raw_score}


def assign_remediation_payload(remediation_hours: float = 4.0) -> Dict[str, Any]:
    return {"remediation_hours": remediation_hours}


def screening_payload(screening_type: str = "BACKGROUND") -> Dict[str, Any]:
    return {"screening_type": screening_type}


def narrative_findings_payload(summary: str = "No adverse information developed",
                               disqualifier_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    """Findings for every screening type other than physical fitness."""
    return {
        "raw_metrics": {"summary": summary},
        "disqualifier_codes": (
            disqualifier_codes if disqualifier_codes is not None else []
        ),
    }


# A four-event set that scores 77 for AGE_20_29 with no event below the floor.
FITNESS_PASSING_METRICS = {
    "push_ups": 36,
    "sit_ups": 38,
    "run_1_5_mile_seconds": 700,
    "vertical_jump_inches": 16,
}
# The same set with a weak vertical jump, which trips the per-event floor and
# caps the composite at 59.
FITNESS_FLOOR_CAPPED_METRICS = {
    "push_ups": 36,
    "sit_ups": 38,
    "run_1_5_mile_seconds": 700,
    "vertical_jump_inches": 13,
}


def fitness_findings_payload(raw_metrics: Optional[Dict[str, Any]] = None,
                             disqualifier_codes: Optional[List[str]] = None) -> Dict[str, Any]:
    return {
        "raw_metrics": dict(raw_metrics if raw_metrics is not None
                            else FITNESS_PASSING_METRICS),
        "disqualifier_codes": (
            disqualifier_codes if disqualifier_codes is not None else []
        ),
    }


def findings_payload_for(screening_type: str,
                         disqualifier_codes: Optional[List[str]] = None,
                         raw_metrics: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if screening_type == "PHYSICAL_FITNESS":
        return fitness_findings_payload(raw_metrics, disqualifier_codes)
    return narrative_findings_payload(disqualifier_codes=disqualifier_codes)


def adjudicate_payload(decision: str = "CLEAR",
                       waiver_justification: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if waiver_justification is not None:
        payload["waiver_justification"] = waiver_justification
    return payload


def advance_stage_payload(to_stage: str,
                          probation_start: Optional[str] = None,
                          probation_base_days: Optional[int] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_stage": to_stage}
    if probation_start is not None:
        payload["probation_start"] = probation_start
    if probation_base_days is not None:
        payload["probation_base_days"] = probation_base_days
    return payload


def dismiss_payload(reason_code: str = "INTEGRITY",
                    justification: str = "Sustained integrity finding") -> Dict[str, Any]:
    return {"reason_code": reason_code, "justification": justification}


def probation_decision_payload(decision: str = "PASS",
                               justification: str = "Milestone review complete") -> Dict[str, Any]:
    return {"decision": decision, "justification": justification}


def rotation_payload(recruit_id: str, fto_instructor_id: str,
                     expected_recruit_version: int,
                     phase_number: int = 1,
                     start_date: str = "2026-09-01",
                     end_date: str = "2026-09-10",
                     prior_rotation_id: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "recruit_id": recruit_id,
        "fto_instructor_id": fto_instructor_id,
        "phase_number": phase_number,
        "start_date": start_date,
        "end_date": end_date,
        "expected_recruit_version": expected_recruit_version,
    }
    if prior_rotation_id is not None:
        payload["prior_rotation_id"] = prior_rotation_id
    return payload


def complete_rotation_payload(final_narrative: str = "Phase completed satisfactorily") -> Dict[str, Any]:
    return {"final_narrative": final_narrative}


def abort_rotation_payload(reason: str = "Officer reassigned to patrol") -> Dict[str, Any]:
    return {"reason": reason}


def dimension_ratings(value: int = DOR_ACCEPTABLE_RATING,
                      **overrides: int) -> Dict[str, int]:
    """The five standardized evaluation dimensions, uniform unless overridden."""
    ratings = {dimension: value for dimension in DOR_DIMENSIONS}
    ratings.update(overrides)
    return ratings


def observation_report_payload(author_instructor_id: str,
                               observed_on: str = "2026-09-02",
                               ratings: Optional[Dict[str, int]] = None,
                               narrative: str = "Trainee handled a domestic call competently",
                               not_responding_to_training: Optional[bool] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "author_instructor_id": author_instructor_id,
        "observed_on": observed_on,
        "dimension_ratings": (
            ratings if ratings is not None else dimension_ratings()
        ),
        "narrative": narrative,
    }
    if not_responding_to_training is not None:
        payload["not_responding_to_training"] = not_responding_to_training
    return payload


def clock_payload(current_utc: str = CLOCK_EPOCH) -> Dict[str, Any]:
    return {"current_utc": current_utc}
