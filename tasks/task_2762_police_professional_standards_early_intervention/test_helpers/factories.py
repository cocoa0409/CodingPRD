"""Request payload builders.

Each builder returns a valid body for one write endpoint, with sensible defaults
that any test can override by keyword. Salary and award amounts are emitted as
JSON numbers - integer counts of cents - never as strings.
"""

from typing import Any, Dict, List, Optional

# ── Reference data ─────────────────────────────────────────────────────────

def unit_payload(
    name: str = "Patrol North",
    unit_role: str = "PATROL_DIVISION",
    command_code: str = "PN",
    peer_group_code: str = "PG_NORTH",
    sworn_headcount: int = 60,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name,
        "unit_role": unit_role,
        "command_code": command_code,
        "peer_group_code": peer_group_code,
        "sworn_headcount": sworn_headcount,
    }
    payload.update(overrides)
    return payload


def internal_affairs_unit_payload(**overrides: Any) -> Dict[str, Any]:
    """The unit that intake routes to when a file must go to Internal Affairs."""
    return unit_payload(
        name="Internal Affairs",
        unit_role="INTERNAL_AFFAIRS",
        command_code="IA",
        peer_group_code="PG_IA",
        sworn_headcount=12,
        intake_enabled=True,
        **overrides,
    )


def patrol_unit_payload(**overrides: Any) -> Dict[str, Any]:
    return unit_payload(intake_enabled=True, **overrides)


def hearing_room_payload(
    facility_code: str = "HQ",
    room_name: str = "Interview 1",
    concurrent_capacity: int = 1,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "facility_code": facility_code,
        "room_name": room_name,
        "concurrent_capacity": concurrent_capacity,
    }
    payload.update(overrides)
    return payload


def officer_payload(
    unit_id: str,
    badge_number: str = "PN-501",
    full_name: str = "Officer Vance",
    rank: str = "OFFICER",
    assignment_type: str = "PATROL",
    annual_salary_cents: int = 9100013,
    demographic_code: str = "DG_C",
    hire_date: str = "2019-06-01T00:00:00Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "unit_id": unit_id,
        "badge_number": badge_number,
        "full_name": full_name,
        "rank": rank,
        "assignment_type": assignment_type,
        "annual_salary_cents": annual_salary_cents,
        "demographic_code": demographic_code,
        "hire_date": hire_date,
    }
    payload.update(overrides)
    return payload


def _role_payload(unit_id: str, defaults: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Merge a role's default officer fields with caller overrides.

    Overrides must win over the role defaults rather than colliding with them,
    so that a caller may vary any single field (salary, demographic, hire date)
    without having to restate the whole role profile.
    """
    merged = dict(defaults)
    merged.update(overrides)
    return officer_payload(unit_id, **merged)


def commander_payload(unit_id: str, **overrides: Any) -> Dict[str, Any]:
    """A commander who adjudicates but never carries a case load."""
    return _role_payload(
        unit_id,
        {
            "badge_number": "IA-001",
            "full_name": "Commander Reyes",
            "rank": "CAPTAIN",
            "assignment_type": "ADMIN",
            "annual_salary_cents": 16500000,
            "demographic_code": "DG_A",
            "hire_date": "2004-01-05T00:00:00Z",
            "is_investigator": False,
            "certification_level": 3,
            "max_case_load": 0,
        },
        overrides,
    )


def investigator_payload(
    unit_id: str,
    badge_number: str = "IA-101",
    full_name: str = "Investigator Ahn",
    certification_level: int = 3,
    max_case_load: int = 8,
    **overrides: Any,
) -> Dict[str, Any]:
    """A certified investigator who is eligible for assignment."""
    return _role_payload(
        unit_id,
        {
            "badge_number": badge_number,
            "full_name": full_name,
            "rank": "SERGEANT",
            "assignment_type": "INVESTIGATIVE",
            "annual_salary_cents": 12800000,
            "demographic_code": "DG_B",
            "hire_date": "2011-03-01T00:00:00Z",
            "is_investigator": True,
            "certification_level": certification_level,
            "max_case_load": max_case_load,
        },
        overrides,
    )


def supervisor_payload(
    unit_id: str,
    badge_number: str = "PN-010",
    full_name: str = "Sergeant Doyle",
    **overrides: Any,
) -> Dict[str, Any]:
    """A patrol sergeant who files complaints and monitors intervention plans."""
    return _role_payload(
        unit_id,
        {
            "badge_number": badge_number,
            "full_name": full_name,
            "rank": "SERGEANT",
            "assignment_type": "PATROL",
            "annual_salary_cents": 10500000,
            "demographic_code": "DG_A",
            "hire_date": "2012-02-02T00:00:00Z",
        },
        overrides,
    )


def subject_officer_payload(
    unit_id: str,
    badge_number: str = "PN-501",
    full_name: str = "Officer Vance",
    **overrides: Any,
) -> Dict[str, Any]:
    """A patrol officer who can be the subject of an allegation."""
    return officer_payload(unit_id, badge_number=badge_number, full_name=full_name, **overrides)


def employment_status_payload(employment_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"employment_status": employment_status}
    payload.update(overrides)
    return payload


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ── Intake ─────────────────────────────────────────────────────────────────

def supervisor_complaint_payload(
    subject_unit_id: str,
    reporting_supervisor_officer_id: str,
    narrative: str = "Reports not filed for four shifts.",
    incident_datetime: str = "2026-07-15T20:00:00Z",
    reported_allegation_types: Optional[List[str]] = None,
    alleged_injury: bool = False,
    complainant_name: str = "Sergeant Doyle",
    complainant_contact: str = "doyle@example.org",
    **overrides: Any,
) -> Dict[str, Any]:
    """A supervisor-channel intake, which names both the complainant and the reporter."""
    payload: Dict[str, Any] = {
        "intake_channel": "SUPERVISOR",
        "narrative": narrative,
        "incident_datetime": incident_datetime,
        "alleged_injury": alleged_injury,
        "reported_allegation_types": (
            ["NEGLECT_OF_DUTY"]
            if reported_allegation_types is None
            else list(reported_allegation_types)
        ),
        "subject_unit_id": subject_unit_id,
        "complainant_name": complainant_name,
        "complainant_contact": complainant_contact,
        "reporting_supervisor_officer_id": reporting_supervisor_officer_id,
    }
    payload.update(overrides)
    return payload


def public_complaint_payload(
    subject_unit_id: str,
    narrative: str = "Officer was rude during a traffic stop.",
    incident_datetime: str = "2026-07-15T20:00:00Z",
    reported_allegation_types: Optional[List[str]] = None,
    alleged_injury: bool = False,
    complainant_name: str = "Ira Fox",
    complainant_contact: str = "ira@example.org",
    **overrides: Any,
) -> Dict[str, Any]:
    """A public-channel intake, which must carry both identity fields."""
    payload: Dict[str, Any] = {
        "intake_channel": "PUBLIC",
        "narrative": narrative,
        "incident_datetime": incident_datetime,
        "alleged_injury": alleged_injury,
        "reported_allegation_types": (
            ["DISCOURTESY"]
            if reported_allegation_types is None
            else list(reported_allegation_types)
        ),
        "subject_unit_id": subject_unit_id,
        "complainant_name": complainant_name,
        "complainant_contact": complainant_contact,
    }
    payload.update(overrides)
    return payload


def anonymous_complaint_payload(
    subject_unit_id: str,
    narrative: str = "An anonymous account of a discourteous stop.",
    incident_datetime: str = "2026-07-15T20:00:00Z",
    reported_allegation_types: Optional[List[str]] = None,
    alleged_injury: bool = False,
    **overrides: Any,
) -> Dict[str, Any]:
    """An anonymous intake, which must carry neither identity field."""
    payload: Dict[str, Any] = {
        "intake_channel": "ANONYMOUS",
        "narrative": narrative,
        "incident_datetime": incident_datetime,
        "alleged_injury": alleged_injury,
        "reported_allegation_types": (
            ["DISCOURTESY"]
            if reported_allegation_types is None
            else list(reported_allegation_types)
        ),
        "subject_unit_id": subject_unit_id,
    }
    payload.update(overrides)
    return payload


def allegation_payload(
    subject_officer_id: str,
    allegation_type: str = "NEGLECT_OF_DUTY",
    narrative: str = "No report filed.",
    offense_class: str = "B",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject_officer_id": subject_officer_id,
        "allegation_type": allegation_type,
        "narrative": narrative,
        "offense_class": offense_class,
    }
    payload.update(overrides)
    return payload


def screening_payload(screening_outcome: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"screening_outcome": screening_outcome}
    payload.update(overrides)
    return payload


def reclassification_payload(classification_override: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"classification_override": classification_override}
    payload.update(overrides)
    return payload


def withdrawal_payload(intake_reference_code: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if intake_reference_code is not None:
        payload["intake_reference_code"] = intake_reference_code
    payload.update(overrides)
    return payload


# ── Investigation ──────────────────────────────────────────────────────────

def assignment_payload(
    expected_investigation_version: int,
    investigator_officer_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """An assignment. Omitting the nominee lets the selector choose."""
    payload: Dict[str, Any] = {"expected_investigation_version": expected_investigation_version}
    if investigator_officer_id is not None:
        payload["investigator_officer_id"] = investigator_officer_id
    payload.update(overrides)
    return payload


def tolling_payload(action: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if action == "SUSPEND" and "tolling_reason" not in overrides:
        payload["tolling_reason"] = "Awaiting a criminal referral."
    payload.update(overrides)
    return payload


def finding_entry(
    allegation_id: str,
    evidence_weight_for: float = 60,
    evidence_weight_against: float = 40,
    policy_compliant: bool = False,
) -> Dict[str, Any]:
    """One entry of the findings payload, one per allegation on the complaint."""
    return {
        "allegation_id": allegation_id,
        "evidence_weight_for": evidence_weight_for,
        "evidence_weight_against": evidence_weight_against,
        "policy_compliant": policy_compliant,
    }


def findings_payload(allegation_findings: List[Dict[str, Any]], **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"allegation_findings": allegation_findings}
    payload.update(overrides)
    return payload


# ── Interviews ─────────────────────────────────────────────────────────────

def interview_session_payload(
    subject_officer_id: str,
    hearing_room_id: str,
    scheduled_start: str = "2026-08-05T09:00:00Z",
    scheduled_end: str = "2026-08-05T10:30:00Z",
    notice_served_at: str = "2026-08-01T00:00:00Z",
    representation_status: str = "REP_PRESENT",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "subject_officer_id": subject_officer_id,
        "hearing_room_id": hearing_room_id,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "notice_served_at": notice_served_at,
        "representation_status": representation_status,
    }
    payload.update(overrides)
    return payload


def hold_payload(
    interview_summary: str = "The officer answered every question put to them.",
    representation_status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"interview_summary": interview_summary}
    if representation_status is not None:
        payload["representation_status"] = representation_status
    payload.update(overrides)
    return payload


def postpone_payload(
    new_scheduled_start: str,
    new_scheduled_end: str,
    new_notice_served_at: str,
    postpone_reason: str = "The representative was unavailable.",
    hearing_room_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "new_scheduled_start": new_scheduled_start,
        "new_scheduled_end": new_scheduled_end,
        "new_notice_served_at": new_notice_served_at,
        "postpone_reason": postpone_reason,
    }
    if hearing_room_id is not None:
        payload["hearing_room_id"] = hearing_room_id
    payload.update(overrides)
    return payload


# ── Adjudication and discipline ────────────────────────────────────────────

def disposition_payload(
    disposition: str,
    aggravator_count: int = 0,
    mitigator_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "disposition": disposition,
        "aggravator_count": aggravator_count,
        "mitigator_count": mitigator_count,
    }
    payload.update(overrides)
    return payload


def imposition_payload(
    effective_date: str = "2026-08-10T00:00:00Z",
    aggravator_count: int = 0,
    mitigator_count: int = 0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "effective_date": effective_date,
        "aggravator_count": aggravator_count,
        "mitigator_count": mitigator_count,
    }
    payload.update(overrides)
    return payload


def appeal_payload(
    forum: str = "ARBITRATION",
    grounds: str = "The finding rests on a misreading of the footage.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"forum": forum, "grounds": grounds}
    payload.update(overrides)
    return payload


def appeal_decision_payload(
    outcome: str,
    modified_days: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if modified_days is not None:
        payload["modified_days"] = modified_days
    payload.update(overrides)
    return payload


def reinstatement_finalize_payload(interim_earnings_cents: int = 0, **overrides: Any) -> Dict[str, Any]:
    """Finalization carries the interim earnings offset as an integer count of cents."""
    payload: Dict[str, Any] = {"interim_earnings_cents": interim_earnings_cents}
    payload.update(overrides)
    return payload


# ── Early intervention ─────────────────────────────────────────────────────

def activity_event_payload(
    event_type: str = "USE_OF_FORCE",
    occurred_at: str = "2026-07-15T00:00:00Z",
    severity_code: Optional[str] = None,
    source_reference: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event_type": event_type, "occurred_at": occurred_at}
    if severity_code is not None:
        payload["severity_code"] = severity_code
    if source_reference is not None:
        payload["source_reference"] = source_reference
    payload.update(overrides)
    return payload


def eis_run_payload(officer_id: Optional[str] = None, **overrides: Any) -> Dict[str, Any]:
    """A sweep body. Naming an officer narrows the sweep to a targeted rescore."""
    payload: Dict[str, Any] = {}
    if officer_id is not None:
        payload["officer_id"] = officer_id
    payload.update(overrides)
    return payload


def intervention_plan_payload(
    expected_alert_version: int,
    supervisor_officer_id: str,
    required_checkin_count: int = 2,
    duration_days: int = 30,
    interventions: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_alert_version": expected_alert_version,
        "supervisor_officer_id": supervisor_officer_id,
        "required_checkin_count": required_checkin_count,
        "duration_days": duration_days,
        "interventions": (
            ["RETRAINING"] if interventions is None else list(interventions)
        ),
    }
    payload.update(overrides)
    return payload


def check_in_completion_payload(outcome: str = "SATISFACTORY", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ── Reporting ──────────────────────────────────────────────────────────────

def outcome_report_params(
    period_start: str,
    period_end: str,
    breakdown: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    params: Dict[str, Any] = {"period_start": period_start, "period_end": period_end}
    if breakdown is not None:
        params["breakdown"] = breakdown
    params.update(overrides)
    return params
