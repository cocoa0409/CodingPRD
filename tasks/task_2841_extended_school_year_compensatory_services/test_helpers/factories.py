"""Request-payload factories.

Every factory returns the PRD's required fields with valid defaults and lets a
caller override any of them with keyword arguments. Money is always an integer
number of cents; clock instants are always full ISO-8601 UTC instants.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CANON_BLACKOUT_DATES,
    CANON_BUDGET_CODE,
    CANON_DAILY_MINUTES_CAP,
    CANON_PROGRAM_NAME,
    CANON_SCHOOL_YEAR,
    CANON_SESSION_END,
    CANON_SESSION_START,
    CANON_WEEKDAYS,
    CANON_AUTHORIZED_AMOUNT_CENTS,
)


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; an override value of None removes the key entirely."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _OMIT:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Omit:
    """Sentinel meaning 'leave this optional field out of the payload'."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "<OMIT>"


_OMIT = _Omit()
OMIT = _OMIT


# ----------------------------------------------------------------- students
def student_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "student_number": "S-2841-001",
            "first_name": "Ada",
            "last_name": "Reyes",
            "grade_band": "MS_6_8",
            "primary_disability": "AUTISM",
            "iep_weekly_minutes_total": 250,
            "transportation_required": True,
            "home_school_code": "MS-014",
        },
        overrides,
    )


# --------------------------------------------------- eligibility probes
def skill_probe(
    skill_domain: str = "READING_FLUENCY",
    pre_break_mastery_pct: int = 80,
    post_break_mastery_pct: int = 60,
    recoupment_days_observed: int = 20,
    trials_count: int = 4,
) -> Dict[str, Any]:
    return {
        "skill_domain": skill_domain,
        "pre_break_mastery_pct": pre_break_mastery_pct,
        "post_break_mastery_pct": post_break_mastery_pct,
        "recoupment_days_observed": recoupment_days_observed,
        "trials_count": trials_count,
    }


def canonical_probes() -> List[Dict[str, Any]]:
    """Two probes yielding max_regression_pct 26.0 and max_recoupment_days 22."""
    return [
        skill_probe("READING_FLUENCY", 80, 60, 20, 4),
        skill_probe("MATH_COMPUTATION", 100, 74, 22, 4),
    ]


def determination_payload(
    student_id: str,
    skill_probes: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "school_year": CANON_SCHOOL_YEAR,
            "analysis_variant": "PROBE_BASED",
            "skill_probes": skill_probes
            if skill_probes is not None
            else canonical_probes(),
        },
        overrides,
    )


# ----------------------------------------------------------------- programs
def program_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "name": CANON_PROGRAM_NAME,
            "school_year": CANON_SCHOOL_YEAR,
            "session_start_date": CANON_SESSION_START,
            "session_end_date": CANON_SESSION_END,
            "instructional_weekdays": list(CANON_WEEKDAYS),
            "daily_minutes_cap": CANON_DAILY_MINUTES_CAP,
            "blackout_dates": list(CANON_BLACKOUT_DATES),
        },
        overrides,
    )


# --------------------------------------------------------- fund allocations
def fund_allocation_payload(
    program_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "fund_source": "IDEA_611_FEDERAL",
            "budget_code": CANON_BUDGET_CODE,
            "authorized_amount_cents": CANON_AUTHORIZED_AMOUNT_CENTS,
        },
        overrides,
    )


# ---------------------------------------------------------------- providers
def provider_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": "Nina Torres",
            "role_type": "SPED_TEACHER",
            "credential_expires_on": "2028-06-30",
            "rate_cents_per_minute": 150,
            "max_weekly_minutes": 1200,
        },
        overrides,
    )


# ------------------------------------------------------ transportation runs
def transportation_run_payload(program_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "route_code": "RT-7",
            "service_date": "2027-06-14",
            "window_start_time": "07:00",
            "window_end_time": "07:45",
            "vehicle_capacity_seats": 6,
        },
        overrides,
    )


# ------------------------------------------------------ service commitments
def commitment_payload(
    program_id: str, student_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "program_id": program_id,
            "student_id": student_id,
            "service_type": "SPECIALIZED_INSTRUCTION",
            "iep_weekly_minutes": 250,
            "staffing_ratio": "ONE_TO_THREE",
        },
        overrides,
    )


# ------------------------------------------------------ provider assignments
def assignment_payload(
    commitment_id: str,
    provider_id: str,
    expected_commitment_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "provider_id": provider_id,
            "weekday": "MON",
            "start_time": "09:00",
            "end_time": "10:00",
            "effective_from": CANON_SESSION_START,
            "effective_to": CANON_SESSION_END,
            "covered_weekly_minutes": 229,
            "expected_commitment_version": expected_commitment_version,
        },
        overrides,
    )

# --------------------------------------------------------------- service logs
def service_log_payload(
    commitment_id: str, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "service_date": "2027-06-14",
            "outcome": "MISSED_DISTRICT",
            "minutes_scheduled": 60,
            "minutes_delivered": 0,
            "miss_reason_code": "STAFF_ABSENCE",
        },
        overrides,
    )


def delivered_log_payload(
    commitment_id: str, service_date: str, minutes: int = 60, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "service_date": service_date,
            "outcome": "DELIVERED",
            "minutes_scheduled": minutes,
            "minutes_delivered": minutes,
        },
        overrides,
    )


def partial_log_payload(
    commitment_id: str,
    service_date: str,
    minutes_scheduled: int = 45,
    minutes_delivered: int = 20,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "service_date": service_date,
            "outcome": "PARTIAL",
            "minutes_scheduled": minutes_scheduled,
            "minutes_delivered": minutes_delivered,
            "miss_reason_code": "TRANSPORT_FAILURE",
        },
        overrides,
    )


def missed_district_log_payload(
    commitment_id: str,
    service_date: str,
    minutes_scheduled: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "service_date": service_date,
            "outcome": "MISSED_DISTRICT",
            "minutes_scheduled": minutes_scheduled,
            "minutes_delivered": 0,
            "miss_reason_code": "STAFF_ABSENCE",
        },
        overrides,
    )


def missed_parent_log_payload(
    commitment_id: str,
    service_date: str,
    minutes_scheduled: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "commitment_id": commitment_id,
            "service_date": service_date,
            "outcome": "MISSED_PARENT",
            "minutes_scheduled": minutes_scheduled,
            "minutes_delivered": 0,
            "miss_reason_code": "PARENT_CANCELLED",
        },
        overrides,
    )


# --------------------------------------------------------- compensatory awards
def award_payload(
    student_id: str,
    source_program_id: str,
    calculation_variant: str = "MINUTE_FOR_MINUTE",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "source_program_id": source_program_id,
            "calculation_variant": calculation_variant,
        },
        overrides,
    )


# ------------------------------------------------------------ makeup sessions
def makeup_session_payload(
    award_id: str,
    provider_id: str,
    expected_award_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "award_id": award_id,
            "provider_id": provider_id,
            "session_date": "2027-09-13",
            "start_time": "15:00",
            "end_time": "16:00",
            "minutes_planned": 60,
            "expected_award_version": expected_award_version,
        },
        overrides,
    )


# ------------------------------------------------------- due process records
def due_process_record_payload(
    student_id: str,
    record_type: str = "COMPLAINT",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "student_id": student_id,
            "record_type": record_type,
            "filed_on": "2027-06-01",
            "allegation_summary": "District failed to deliver agreed summer services.",
        },
        overrides,
    )
