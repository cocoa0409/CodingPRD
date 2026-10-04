"""Payload factories — one per creatable resource, input fields only.

Computed and system-managed fields are never placed on a request body; the
defaults reproduce the canonical world (service year 2026-09-01 through
2027-06-15, stipend 1300000 cents, team size 3, backfill deadline 2027-01-15)
and every factory accepts ``**overrides`` for the values a test needs to
control.
"""

from typing import Any, Dict, Optional

from .constants import (
    ANNUAL_STIPEND_CENTS,
    BACKFILL_DEADLINE,
    BACKFILL_LIMIT,
    MEMBER_DOB,
    SCHOOL_COST_SHARE_CENTS,
    SCHOOL_TEAM_SIZE,
    SERVICE_YEAR_END,
    SERVICE_YEAR_START,
)


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


def site_payload(**overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "name": "Riverton Site",
        "city": "Riverton",
        "service_year_start": SERVICE_YEAR_START,
        "service_year_end": SERVICE_YEAR_END,
        "annual_stipend_cents": ANNUAL_STIPEND_CENTS,
    }
    defaults.update(overrides)
    return defaults


def school_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "name": "Riverton Elementary",
        "district_name": "Riverton USD",
        "team_size": SCHOOL_TEAM_SIZE,
        "service_scope": ["ATTENDANCE_SUPPORT", "MATH_TUTORING"],
        "annual_cost_share_cents": SCHOOL_COST_SHARE_CENTS,
    }
    defaults.update(overrides)
    return defaults


def application_payload(site_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "site_id": site_id,
        "full_name": "Jordan Rivers",
        "date_of_birth": MEMBER_DOB,
        "education_level": "BACHELORS_PLUS",
        "citizenship_status": "US_CITIZEN",
        "prior_service_terms": 0,
        "prior_full_awards_received": 0,
    }
    defaults.update(overrides)
    return defaults


def team_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "name": "Team Alpha",
        "backfill_deadline": BACKFILL_DEADLINE,
        "backfill_limit": BACKFILL_LIMIT,
    }
    defaults.update(overrides)
    return defaults


def assignment_payload(corps_member_id: str, expected_team_version: int, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "corps_member_id": corps_member_id,
        "start_date": SERVICE_YEAR_START,
        "expected_team_version": expected_team_version,
    }
    defaults.update(overrides)
    return defaults


def student_payload(school_id: str, external_student_ref: str = "S01", **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "external_student_ref": external_student_ref,
        "grade_level": 3,
        "focus_list_type": "ATTENDANCE",
        "baseline_attendance_pct": 80.0,
    }
    defaults.update(overrides)
    return defaults


def hour_entry_payload(corps_member_id: str, service_date: str, hours: float, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "corps_member_id": corps_member_id,
        "service_date": service_date,
        "hours": hours,
        "category": "DIRECT_SERVICE",
    }
    defaults.update(overrides)
    return defaults


def stipend_payment_payload(period_start: str, period_end: str) -> Dict[str, Any]:
    return {"period_start": period_start, "period_end": period_end}


def evaluation_report_payload(school_id: str, **overrides: Any) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "school_id": school_id,
        "period_start": "2026-09-01",
        "period_end": "2026-10-31",
    }
    defaults.update(overrides)
    return defaults
