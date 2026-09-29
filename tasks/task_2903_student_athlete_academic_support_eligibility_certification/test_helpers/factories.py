"""Request-payload factories.

Every numeric value is emitted as a JSON number (never a quoted string) and
every instant is emitted as a full ISO-8601 UTC instant, because the PRD
compares term, travel and session bounds against the logical clock.
"""

from datetime import datetime, timedelta, timezone
from itertools import count
from typing import Any, Dict, List, Optional

from .api_client import OMIT
from .constants import (
    APPLICABILITY_CORE,
    CERT_TYPE_INITIAL,
    CREDIT_SOURCE_RESIDENT,
    EVENT_TYPE_REGULAR_SEASON,
    INCIDENT_TYPES,
    OUTCOME_RECORD_GRADE,
    SESSION_STUDY_HALL,
    TRANSFER_STATUS_NATIVE,
)
from .test_users import INSTRUCTOR_KINE_1
from .types import Payload

_seq = count(1)


def next_seq() -> int:
    """A monotonically increasing counter for uniqueness-sensitive fields."""
    return next(_seq)


# ---------------------------------------------------------------------------
# Instant helpers
# ---------------------------------------------------------------------------
def instant(
    year: int,
    month: int,
    day: int,
    hour: int = 0,
    minute: int = 0,
    second: int = 0,
) -> str:
    """Build a full ISO-8601 UTC instant with no fractional part."""
    dt = datetime(year, month, day, hour, minute, second, tzinfo=timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_instant(value: str) -> datetime:
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text)


def shift(value: str, **delta: Any) -> str:
    """Return ``value`` shifted by the supplied ``timedelta`` keywords."""
    dt = parse_instant(value) + timedelta(**delta)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def minutes_after_midnight(value: str) -> int:
    dt = parse_instant(value)
    return dt.hour * 60 + dt.minute


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------
def term(
    code: str,
    term_index: int,
    start_date: str,
    end_date: str,
    term_type: str = "FALL",
    catalog_year: int = 2026,
    full_time_credit_minimum: Any = OMIT,
    is_apr_reporting_term: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "code": code,
        "term_index": term_index,
        "term_type": term_type,
        "catalog_year": catalog_year,
        "start_date": start_date,
        "end_date": end_date,
        "full_time_credit_minimum": full_time_credit_minimum,
        "is_apr_reporting_term": is_apr_reporting_term,
    }
    payload.update(extra)
    return payload


def degree_program(
    code: str = "BSKINE",
    name: str = "BS Kinesiology",
    catalog_year: int = 2026,
    total_required_credits: float = 60.0,
    min_progress_gpa: Any = OMIT,
    major_declaration_deadline_term_count: Any = OMIT,
    max_elective_credits_countable: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "code": code,
        "name": name,
        "catalog_year": catalog_year,
        "total_required_credits": total_required_credits,
        "min_progress_gpa": min_progress_gpa,
        "major_declaration_deadline_term_count": (
            major_declaration_deadline_term_count
        ),
        "max_elective_credits_countable": max_elective_credits_countable,
    }
    payload.update(extra)
    return payload


def course(
    subject_code: str = "KINE",
    course_number: str = "101",
    title: str = "Foundations of Kinesiology",
    credit_hours: float = 4.0,
    instructor_user_id: str = INSTRUCTOR_KINE_1,
    meeting_days: Any = OMIT,
    meeting_start_minute_utc: Any = OMIT,
    meeting_duration_minutes: Any = OMIT,
    is_remedial: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "subject_code": subject_code,
        "course_number": course_number,
        "title": title,
        "credit_hours": credit_hours,
        "instructor_user_id": instructor_user_id,
        "meeting_days": meeting_days,
        "meeting_start_minute_utc": meeting_start_minute_utc,
        "meeting_duration_minutes": meeting_duration_minutes,
        "is_remedial": is_remedial,
    }
    payload.update(extra)
    return payload


def applicability_rule(
    degree_program_id: str,
    course_id: str,
    effective_catalog_year: int = 2026,
    applicability: str = APPLICABILITY_CORE,
    max_countable_credits: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "degree_program_id": degree_program_id,
        "course_id": course_id,
        "effective_catalog_year": effective_catalog_year,
        "applicability": applicability,
        "max_countable_credits": max_countable_credits,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Students and enrollments
# ---------------------------------------------------------------------------
def student(
    full_name: str = "Avery Stone",
    sport_code: str = "SOC",
    entry_term_index: int = 1,
    entry_catalog_year: int = 2026,
    transfer_status: Any = OMIT,
    missed_class_units_allowance: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "sport_code": sport_code,
        "entry_term_index": entry_term_index,
        "entry_catalog_year": entry_catalog_year,
        "transfer_status": transfer_status,
        "missed_class_units_allowance": missed_class_units_allowance,
    }
    payload.update(extra)
    return payload


def major_declaration(declared_program_id: str, term_id: str, **extra: Any) -> Payload:
    payload: Dict[str, Any] = {
        "declared_program_id": declared_program_id,
        "term_id": term_id,
    }
    payload.update(extra)
    return payload


def enrollment(
    student_athlete_id: str,
    course_id: str,
    term_id: str,
    credit_hours: Any = OMIT,
    credit_source: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "student_athlete_id": student_athlete_id,
        "course_id": course_id,
        "term_id": term_id,
        "credit_hours": credit_hours,
        "credit_source": credit_source,
    }
    payload.update(extra)
    return payload


def outcome(
    action: str = OUTCOME_RECORD_GRADE,
    grade: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {"action": action, "grade": grade}
    payload.update(extra)
    return payload


def record_grade(grade: str) -> Payload:
    return {"action": OUTCOME_RECORD_GRADE, "grade": grade}


# ---------------------------------------------------------------------------
# Certifications and appeals
# ---------------------------------------------------------------------------
def certification(
    student_athlete_id: str,
    term_id: str,
    expected_student_athlete_version: int,
    certification_type: str = CERT_TYPE_INITIAL,
    audit_variant: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "student_athlete_id": student_athlete_id,
        "term_id": term_id,
        "certification_type": certification_type,
        "expected_student_athlete_version": expected_student_athlete_version,
        "audit_variant": audit_variant,
    }
    payload.update(extra)
    return payload


def action(name: str, **extra: Any) -> Payload:
    """A bare status payload carrying only ``action``."""
    payload: Dict[str, Any] = {"action": name}
    payload.update(extra)
    return payload


def appeal(
    certification_id: str,
    appeal_type: str = "PROGRESS_WAIVER",
    rationale: str = "Documented academic hardship during the term.",
    requested_credit_relief: Any = OMIT,
    predecessor_appeal_id: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "certification_id": certification_id,
        "appeal_type": appeal_type,
        "rationale": rationale,
        "requested_credit_relief": requested_credit_relief,
        "predecessor_appeal_id": predecessor_appeal_id,
    }
    payload.update(extra)
    return payload


def grant(granted_credit_relief: float, **extra: Any) -> Payload:
    payload: Dict[str, Any] = {
        "action": "GRANT",
        "granted_credit_relief": granted_credit_relief,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Tutors, assignments and sessions
# ---------------------------------------------------------------------------
def tutor(
    full_name: str = "Dana Reed",
    subject_codes: Optional[List[str]] = None,
    max_weekly_hours: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "full_name": full_name,
        "subject_codes": subject_codes if subject_codes is not None else ["KINE"],
        "max_weekly_hours": max_weekly_hours,
    }
    payload.update(extra)
    return payload


def complete_training(term_id: str, **extra: Any) -> Payload:
    payload: Dict[str, Any] = {"action": "COMPLETE_TRAINING", "term_id": term_id}
    payload.update(extra)
    return payload


def terminate(terminated_reason: str = "SPECIALIST_REQUEST", **extra: Any) -> Payload:
    payload: Dict[str, Any] = {
        "action": "TERMINATE",
        "terminated_reason": terminated_reason,
    }
    payload.update(extra)
    return payload


def assignment(
    tutor_id: str,
    enrollment_id: str,
    weekly_hours: float = 2.0,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "tutor_id": tutor_id,
        "enrollment_id": enrollment_id,
        "weekly_hours": weekly_hours,
    }
    payload.update(extra)
    return payload


def session(
    student_athlete_id: str,
    start_at: str,
    end_at: str,
    session_type: str = SESSION_STUDY_HALL,
    tutor_assignment_id: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "student_athlete_id": student_athlete_id,
        "session_type": session_type,
        "start_at": start_at,
        "end_at": end_at,
        "tutor_assignment_id": tutor_assignment_id,
    }
    payload.update(extra)
    return payload


def tutor_session(
    student_athlete_id: str,
    tutor_assignment_id: str,
    start_at: str,
    end_at: str,
    **extra: Any,
) -> Payload:
    return session(
        student_athlete_id,
        start_at,
        end_at,
        session_type="TUTOR_SESSION",
        tutor_assignment_id=tutor_assignment_id,
        **extra,
    )


# ---------------------------------------------------------------------------
# Travel and missed-class accounting
# ---------------------------------------------------------------------------
def event(
    term_id: str,
    departure_at: str,
    return_at: str,
    sport_code: str = "SOC",
    event_type: str = EVENT_TYPE_REGULAR_SEASON,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "sport_code": sport_code,
        "term_id": term_id,
        "event_type": event_type,
        "departure_at": departure_at,
        "return_at": return_at,
    }
    payload.update(extra)
    return payload


def missed_class_request(
    competition_event_id: str, enrollment_id: str, **extra: Any
) -> Payload:
    payload: Dict[str, Any] = {
        "competition_event_id": competition_event_id,
        "enrollment_id": enrollment_id,
    }
    payload.update(extra)
    return payload


def instructor_response(action_name: str, note: str = "Noted.", **extra: Any) -> Payload:
    payload: Dict[str, Any] = {
        "action": action_name,
        "instructor_response_note": note,
    }
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Compliance incidents
# ---------------------------------------------------------------------------
def incident(
    student_athlete_id: str,
    incident_type: str = INCIDENT_TYPES[0],
    narrative: str = "Coursework appears to have been completed by another party.",
    tutor_id: Any = OMIT,
    discovered_session_id: Any = OMIT,
    **extra: Any,
) -> Payload:
    payload: Dict[str, Any] = {
        "student_athlete_id": student_athlete_id,
        "incident_type": incident_type,
        "narrative": narrative,
        "tutor_id": tutor_id,
        "discovered_session_id": discovered_session_id,
    }
    payload.update(extra)
    return payload


def substantiate(severity: str, **extra: Any) -> Payload:
    payload: Dict[str, Any] = {"action": "SUBSTANTIATE", "severity": severity}
    payload.update(extra)
    return payload
