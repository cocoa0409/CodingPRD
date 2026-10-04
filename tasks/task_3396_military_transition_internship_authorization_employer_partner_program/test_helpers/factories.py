"""Payload factories - one per creatable resource, input fields only.

Defaults are chosen so a no-override payload is valid at the default logical
clock (2026-09-01T00:00:00Z): separation 2027-01-15 is 136 days out (inside
the 30-180 day eligibility window), and the default match window
[2026-10-01, 2026-10-31) is a legal 30 days.
"""

from typing import Any, Dict, List, Optional

DEFAULT_SEPARATION_DATE = "2027-01-15"
DEFAULT_MATCH_START = "2026-10-01"
DEFAULT_MATCH_END = "2026-10-31"
DEFAULT_OBJECTIVES = [
    {"objective_code": "O1", "description": "Safety basics", "weight_hours": 10},
]


def create_installation_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "Fort Liberty",
        "command_code": "ACC",
        "region_code": "R1",
        "max_internship_duration_days": 120,
        "appeal_window_days": 14,
        "requires_tap_complete": False,
    }
    payload.update(overrides)
    return payload


def create_service_member_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Alice Vega",
        "service_branch": "ARMY",
        "pay_grade": "E5",
        "separation_date": DEFAULT_SEPARATION_DATE,
        "skills": ["LOGISTICS"],
        "home_installation_id": None,
    }
    payload.update(overrides)
    return payload


def create_application_payload(service_member_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"service_member_id": service_member_id}
    payload.update(overrides)
    return payload


def commander_decision_payload(decision: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def appeal_payload(appeal_reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if appeal_reason is not None:
        payload["appeal_reason"] = appeal_reason
    return payload


def adjudicate_payload(outcome: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if reason is not None:
        payload["reason"] = reason
    return payload


def create_employer_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": "Acme Logistics LLC",
        "industry_code": "LOG",
    }
    payload.update(overrides)
    return payload


def periodic_review_payload(outcome: str, notes: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if notes is not None:
        payload["notes"] = notes
    return payload


def create_opening_payload(employer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "employer_id": employer_id,
        "title": "Warehouse Operations Intern",
        "required_skills": ["LOGISTICS"],
        "location_type": "REMOTE",
        "capacity": 1,
    }
    payload.update(overrides)
    return payload


def create_match_payload(
    internship_application_id: str,
    employer_opening_id: str,
    expected_employer_opening_version: int,
    start_date: str = DEFAULT_MATCH_START,
    end_date: str = DEFAULT_MATCH_END,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "internship_application_id": internship_application_id,
        "employer_opening_id": employer_opening_id,
        "start_date": start_date,
        "end_date": end_date,
        "expected_employer_opening_version": expected_employer_opening_version,
    }
    payload.update(overrides)
    return payload


def submit_plan_payload(
    objectives: Optional[List[Dict[str, Any]]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "learning_objectives": objectives if objectives is not None else [dict(o) for o in DEFAULT_OBJECTIVES],
        "supervisor_name": "S. Supervisor",
        "weekly_hours": 40,
    }
    payload.update(overrides)
    return payload


def review_plan_payload(outcome: str, feedback: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if feedback is not None:
        payload["feedback"] = feedback
    return payload


def installation_decision_payload(decision: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if reason is not None:
        payload["reason"] = reason
    return payload


def terminate_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


def supervision_report_payload(
    internship_match_id: str,
    week_start_date: str,
    objectives_achieved: Optional[List[str]] = None,
    objectives_excused: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "internship_match_id": internship_match_id,
        "week_start_date": week_start_date,
        "hours_supervised": 8,
        "supervisor_name": "S. Supervisor",
        "attestation_text": "week ok",
    }
    if objectives_achieved is not None:
        payload["objectives_achieved"] = objectives_achieved
    if objectives_excused is not None:
        payload["objectives_excused"] = objectives_excused
    payload.update(overrides)
    return payload


def wage_record_payload(
    internship_match_id: str,
    period_start_date: str,
    period_end_date: str,
    amount_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "internship_match_id": internship_match_id,
        "period_start_date": period_start_date,
        "period_end_date": period_end_date,
        "amount_cents": amount_cents,
    }
    payload.update(overrides)
    return payload


def create_audit_payload(employer_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"employer_id": employer_id}
    payload.update(overrides)
    return payload


def finding(finding_code: str, severity: str, note: str = "") -> Dict[str, Any]:
    return {"finding_code": finding_code, "severity": severity, "note": note}


def close_audit_payload(findings: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if findings is not None:
        payload["findings"] = findings
    return payload


def conversion_record_payload(
    internship_match_id: str,
    conversion_date: str,
    offer_made: bool,
    offer_accepted: bool,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "internship_match_id": internship_match_id,
        "conversion_date": conversion_date,
        "offer_made": offer_made,
        "offer_accepted": offer_accepted,
    }
    payload.update(overrides)
    return payload


def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}
