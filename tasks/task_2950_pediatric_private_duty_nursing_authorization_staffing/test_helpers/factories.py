"""Request-body factories.

Each factory returns a complete, valid payload for one endpoint, built from the
canonical literals in :mod:`constants`, and accepts ``**overrides`` so a test
can perturb exactly one field. Numeric fields are emitted as JSON numbers
(never strings) and every field the PRD types as an instant carries a full
ISO-8601 instant literal, never a date-only value.
"""

from typing import Any, Dict, List, Optional

from . import constants as C
from .types import (
    BillingEditRuleset,
    DisputeType,
    EvvMethod,
    IncidentCategory,
    IncidentSeverity,
    LicenseType,
    PlanType,
    Skill,
    VisitOutcome,
)


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of ``...`` (Ellipsis) drops the key entirely."""
    payload.update(overrides)
    return {key: value for key, value in payload.items() if value is not ...}


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = C.CLOCK_WEEK32_MONDAY_06, **overrides):
    """POST /pdn/_clock/set_current_utc"""
    return _merge({"to_iso8601": to_iso8601}, overrides)


# ---------------------------------------------------------------------------
# Payer
# ---------------------------------------------------------------------------
def payer_payload(**overrides):
    """POST /pdn/payers - `weekly_hour_cap` is a JSON number."""
    return _merge(
        {
            "name": C.PAYER_NAME,
            "plan_type": PlanType.MEDICAID_MCO.value,
            "weekly_hour_cap": C.PAYER_WEEKLY_HOUR_CAP,
            "evv_required": True,
            "billing_edit_ruleset": BillingEditRuleset.STANDARD_15MIN.value,
            "appeal_window_days": C.PAYER_APPEAL_WINDOW_DAYS,
            "reduction_notice_days": C.PAYER_REDUCTION_NOTICE_DAYS,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Nurse and competency
# ---------------------------------------------------------------------------
def nurse_payload(**overrides):
    """POST /pdn/nurses - `license_expires_on` is a date, per PRD 2.4."""
    return _merge(
        {
            "full_name": C.NURSE_FULL_NAME,
            "license_type": LicenseType.RN.value,
            "license_number": C.NURSE_LICENSE_NUMBER,
            "license_expires_on": C.NURSE_LICENSE_EXPIRES_ON,
            "max_weekly_hours": C.NURSE_MAX_WEEKLY_HOURS,
        },
        overrides,
    )


def nurse_status_payload(status: str, **overrides):
    """POST /pdn/nurses/{id}/status"""
    return _merge({"status": status}, overrides)


def competency_payload(skill: str = Skill.TRACH.value, **overrides):
    """POST /pdn/nurses/{id}/competencies"""
    return _merge(
        {
            "skill": skill,
            "validated_on": C.COMPETENCY_VALIDATED_ON,
            "expires_on": C.COMPETENCY_EXPIRES_ON,
        },
        overrides,
    )


def revoke_competency_payload(reason: str = "Skills check failed", **overrides):
    """POST /pdn/nurse-competencies/{id}/revoke"""
    return _merge({"revoked_reason": reason}, overrides)


def continuity_score_params(case_id: str, basis: Optional[str] = None, **overrides):
    """GET /pdn/nurses/{id}/continuity-score query string."""
    params: Dict[str, Any] = {"case_id": case_id}
    if basis is not None:
        params["basis"] = basis
    return _merge(params, overrides)


# ---------------------------------------------------------------------------
# Patient
# ---------------------------------------------------------------------------
def patient_payload(payer_id: str, **overrides):
    """POST /pdn/patients - the canonical trach + vent child with parent backup."""
    return _merge(
        {
            "payer_id": payer_id,
            "full_name": C.PATIENT_NAME,
            "date_of_birth": C.PATIENT_DOB,
            "primary_diagnosis": "Chronic respiratory failure",
            "requires_trach": True,
            "requires_vent": True,
            "requires_feeding_tube": False,
            "parent_backup_available": True,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Plan of care
# ---------------------------------------------------------------------------
def plan_of_care_payload(patient_id: str, **overrides):
    """POST /pdn/plans-of-care - `requested_hours_per_week` is a JSON number."""
    return _merge(
        {
            "patient_id": patient_id,
            "requested_hours_per_week": C.POC_REQUESTED_HOURS,
            "start_date": C.POC_EFFECTIVE_START,
            "end_date": C.POC_EFFECTIVE_END,
            "ordering_physician_npi": C.POC_PHYSICIAN_NPI,
        },
        overrides,
    )


def return_plan_payload(reason: str = "Physician order missing", **overrides):
    """POST /pdn/plans-of-care/{id}/return"""
    return _merge({"return_reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------
def authorization_payload(
    plan_of_care_id: str, payer_id: str, expected_plan_of_care_version: int, **overrides
):
    """POST /pdn/authorizations - effective bounds are full ISO-8601 instants."""
    return _merge(
        {
            "plan_of_care_id": plan_of_care_id,
            "payer_id": payer_id,
            "approved_hours_per_week": C.AUTH_APPROVED_HOURS,
            "effective_start": C.AUTH_EFFECTIVE_START,
            "effective_end": C.AUTH_EFFECTIVE_END,
            "expected_plan_of_care_version": expected_plan_of_care_version,
        },
        overrides,
    )


def utilization_params(basis: Optional[str] = None, week_of: Optional[str] = None):
    """GET /pdn/authorizations/{id}/utilization query string."""
    params: Dict[str, Any] = {}
    if basis is not None:
        params["basis"] = basis
    if week_of is not None:
        params["week_of"] = week_of
    return params


def reduce_payload(noticed_hours_per_week: float, reason: str = "Utilization review", **overrides):
    """POST /pdn/authorizations/{id}/reduce"""
    return _merge(
        {
            "noticed_hours_per_week": noticed_hours_per_week,
            "reduction_reason": reason,
        },
        overrides,
    )


def renew_payload(effective_end: str, approved_hours_per_week: Optional[float] = None, **overrides):
    """POST /pdn/authorizations/{id}/renew"""
    payload: Dict[str, Any] = {"effective_end": effective_end}
    if approved_hours_per_week is not None:
        payload["approved_hours_per_week"] = approved_hours_per_week
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Disputes
# ---------------------------------------------------------------------------
def dispute_payload(authorization_id: str, requested_hours_per_week: float, **overrides):
    """POST /pdn/authorization-disputes"""
    return _merge(
        {
            "authorization_id": authorization_id,
            "dispute_type": DisputeType.REDUCTION_APPEAL.value,
            "requested_hours_per_week": requested_hours_per_week,
            "reason": "Medical necessity unchanged",
        },
        overrides,
    )


def decide_dispute_payload(outcome: str, decided_hours_per_week: Optional[float] = None, **overrides):
    """POST /pdn/authorization-disputes/{id}/decide"""
    payload: Dict[str, Any] = {"outcome": outcome, "decision_note": "Reviewed"}
    if decided_hours_per_week is not None:
        payload["decided_hours_per_week"] = decided_hours_per_week
    return _merge(payload, overrides)


# ---------------------------------------------------------------------------
# Cases and supervisory visits
# ---------------------------------------------------------------------------
def case_payload(
    patient_id: str,
    authorization_id: str,
    assigned_supervisor_user_id: str,
    **overrides,
):
    """POST /pdn/cases"""
    return _merge(
        {
            "patient_id": patient_id,
            "authorization_id": authorization_id,
            "assigned_supervisor_user_id": assigned_supervisor_user_id,
        },
        overrides,
    )


def hold_payload(hold_reason: str, **overrides):
    """POST /pdn/cases/{id}/hold"""
    return _merge({"hold_reason": hold_reason}, overrides)


def close_case_payload(reason: str = "Family relocated", **overrides):
    """POST /pdn/cases/{id}/close"""
    return _merge({"close_reason": reason}, overrides)


def supervisory_visit_payload(
    visit_at: str, outcome: str = VisitOutcome.PASS.value, **overrides
):
    """POST /pdn/cases/{id}/supervisory-visits - `visit_at` is a full instant."""
    return _merge(
        {
            "visit_at": visit_at,
            "outcome": outcome,
            "notes": "Routine supervisory visit",
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Incident reports
# ---------------------------------------------------------------------------
def incident_payload(
    case_id: str,
    occurred_at: str,
    category: str = IncidentCategory.HOSPITALIZATION.value,
    severity: str = IncidentSeverity.HIGH.value,
    **overrides,
):
    """POST /pdn/incident-reports - `occurred_at` is a full instant."""
    return _merge(
        {
            "case_id": case_id,
            "category": category,
            "severity": severity,
            "occurred_at": occurred_at,
            "narrative": "Child transported to hospital",
        },
        overrides,
    )


def close_incident_payload(patient_returned_home: bool, resolution: str = "Resolved", **overrides):
    """POST /pdn/incident-reports/{id}/close"""
    return _merge(
        {"resolution": resolution, "patient_returned_home": patient_returned_home},
        overrides,
    )


# ---------------------------------------------------------------------------
# Shifts
# ---------------------------------------------------------------------------
def shift_payload(
    case_id: str,
    start_at: str,
    end_at: str,
    required_skills: Optional[List[str]] = None,
    **overrides,
):
    """POST /pdn/shifts - `start_at` and `end_at` are full ISO-8601 instants."""
    return _merge(
        {
            "case_id": case_id,
            "start_at": start_at,
            "end_at": end_at,
            "required_skills": list(required_skills)
            if required_skills is not None
            else [Skill.TRACH.value, Skill.VENT.value],
        },
        overrides,
    )


def auto_staff_payload(expected_shift_version: int, **overrides):
    """POST /pdn/shifts/{id}/auto-staff"""
    return _merge({"expected_shift_version": expected_shift_version}, overrides)


def escalate_payload(reason: str = "No nurse available", **overrides):
    """POST /pdn/shifts/{id}/escalate"""
    return _merge({"escalation_reason": reason}, overrides)


def parent_backup_payload(note: str = "Mother covering the overnight", **overrides):
    """POST /pdn/shifts/{id}/parent-backup"""
    return _merge({"arrangement_note": note}, overrides)


def clock_in_payload(
    evv_method: str = EvvMethod.GPS.value, geo_verified: bool = True, **overrides
):
    """POST /pdn/shifts/{id}/clock-in"""
    return _merge({"evv_method": evv_method, "geo_verified": geo_verified}, overrides)


# ---------------------------------------------------------------------------
# Shift assignments
# ---------------------------------------------------------------------------
def assignment_payload(shift_id: str, nurse_id: str, expected_shift_version: int, **overrides):
    """POST /pdn/shift-assignments"""
    return _merge(
        {
            "shift_id": shift_id,
            "nurse_id": nurse_id,
            "expected_shift_version": expected_shift_version,
        },
        overrides,
    )


def cancel_assignment_payload(note: str = "Schedule change", **overrides):
    """POST /pdn/shift-assignments/{id}/cancel"""
    return _merge({"cancel_note": note}, overrides)


# ---------------------------------------------------------------------------
# Timesheets
# ---------------------------------------------------------------------------
def correct_timesheet_payload(
    edit_reason: str = "Corrected clock times",
    clock_in_at: Optional[str] = None,
    clock_out_at: Optional[str] = None,
    **overrides,
):
    """PATCH /pdn/timesheets/{id} - both instants are full ISO-8601 instants."""
    payload: Dict[str, Any] = {"edit_reason": edit_reason}
    if clock_in_at is not None:
        payload["clock_in_at"] = clock_in_at
    if clock_out_at is not None:
        payload["clock_out_at"] = clock_out_at
    return _merge(payload, overrides)


def billing_decision_payload(decision: str, rejection_reason: Optional[str] = None, **overrides):
    """POST /pdn/timesheets/{id}/billing-decision"""
    payload: Dict[str, Any] = {"decision": decision}
    if rejection_reason is not None:
        payload["rejection_reason"] = rejection_reason
    return _merge(payload, overrides)


def void_timesheet_payload(reason: str = "Duplicate capture", **overrides):
    """POST /pdn/timesheets/{id}/void"""
    return _merge({"void_reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Query-string helpers
# ---------------------------------------------------------------------------
def pagination(limit: Optional[Any] = None, offset: Optional[Any] = None, **overrides):
    """A `limit`/`offset` query string, omitting whichever bound is None."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    return _merge(params, overrides)
