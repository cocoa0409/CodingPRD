"""Request-payload builders.

Conventions that every builder honours:

* Numeric fields are sent as real JSON numbers -- never as strings.
  ``complexity_multiplier`` and ``qualification_points_required`` are floats;
  every day count, evidence count and version token is an int.
* Fields the PRD types as a *date* carry a date-only literal
  (``2026-09-07``); fields the PRD types as an *instant* carry a full
  ISO 8601 UTC instant (``2026-09-07T08:00:00Z``).
* Optional fields are omitted entirely unless a value is supplied, so that a
  builder never sends an explicit ``null`` the PRD did not ask for. The one
  exception is spelled out at its call site.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    ACTIVITY_CALIBRATION,
    CASE_KIND_COMPLAINT,
    CYCLE_INITIAL,
    DELIVERY_ON_SITE,
    EMPLOYMENT_INTERNAL,
    NOTICE_DAYS_DEFAULT,
    PLAN_MODE_HYBRID,
    ROLE_TYPE_LEAD_ASSESSOR,
    STANDARD_REF_17025,
)

# The rule set every design instance opens with: a calibration programme
# whose complexity multiplier is deliberately not 1.0000 so that the
# per-line fee rounding of section 2.7 is observable.
SCHEME_RULESET = {
    "name": "Calibration laboratories",
    "standard_ref": STANDARD_REF_17025,
    "complexity_multiplier": 1.0725,
    "witness_min_count": 2,
    "qualification_points_required": 60.0,
    "surveillance_interval_days": 365,
    "reassessment_interval_days": 1460,
    "critical_nc_close_days": 30,
    "major_nc_close_days": 60,
    "minor_nc_close_days": 90,
    "unannounced_authority": True,
    "remote_assessment_allowed": True,
}

DEFAULT_SCOPE_LINES = [
    "Mass 1kg-20kg",
    "Temperature -20C-200C",
    "Pressure 0-10MPa",
]


def _without_none(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {key: value for key, value in payload.items() if value is not None}


# --- Schemes -------------------------------------------------------------


def scheme_payload(program_code: str, **overrides: Any) -> Dict[str, Any]:
    """A full rule set. Pass ``field=None`` to drop an optional field."""
    payload = {"program_code": program_code}
    payload.update(SCHEME_RULESET)
    payload.update(overrides)
    return _without_none(payload)


def minimal_scheme_payload(program_code: str, **overrides: Any) -> Dict[str, Any]:
    """Only the three mandatory inputs, so every default is exercised."""
    payload = {
        "program_code": program_code,
        "name": "Calibration laboratories",
        "standard_ref": STANDARD_REF_17025,
    }
    payload.update(overrides)
    return _without_none(payload)


def scheme_status_payload(
    to_status: str, revision_note: Optional[str] = None
) -> Dict[str, Any]:
    return _without_none({"to_status": to_status, "revision_note": revision_note})


# --- Assessors -----------------------------------------------------------


def assessor_payload(
    full_name: str,
    email: str,
    employment_type: str = EMPLOYMENT_INTERNAL,
    annual_witness_capacity_days: Optional[int] = 20,
) -> Dict[str, Any]:
    return _without_none(
        {
            "full_name": full_name,
            "email": email,
            "employment_type": employment_type,
            "annual_witness_capacity_days": annual_witness_capacity_days,
        }
    )


def assessor_status_payload(
    to_status: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    return _without_none({"to_status": to_status, "reason": reason})


# --- Qualifications ------------------------------------------------------


def qualification_payload(
    scheme_id: str,
    role_type: str = ROLE_TYPE_LEAD_ASSESSOR,
    years_experience: int = 8,
    declared_witness_days: int = 6,
    declared_training_modules: int = 3,
    last_witness_on: Optional[str] = "2026-05-10",
) -> Dict[str, Any]:
    return _without_none(
        {
            "scheme_id": scheme_id,
            "role_type": role_type,
            "years_experience": years_experience,
            "declared_witness_days": declared_witness_days,
            "declared_training_modules": declared_training_modules,
            "last_witness_on": last_witness_on,
        }
    )


def verify_evidence_payload(
    verified_years_experience: int,
    verified_witness_days: int,
    verified_training_modules: int,
) -> Dict[str, Any]:
    return {
        "verified_years_experience": verified_years_experience,
        "verified_witness_days": verified_witness_days,
        "verified_training_modules": verified_training_modules,
    }


# --- Impartiality declarations ------------------------------------------


def declaration_payload(
    organization_id: str,
    relationship_type: str,
    started_on: str,
    ended_on: Optional[str] = None,
    detail: Optional[str] = None,
) -> Dict[str, Any]:
    return _without_none(
        {
            "organization_id": organization_id,
            "relationship_type": relationship_type,
            "started_on": started_on,
            "ended_on": ended_on,
            "detail": detail,
        }
    )


# --- Organizations -------------------------------------------------------


def organization_payload(
    legal_name: str,
    country_code: str = "DE",
    contact_email: str = "qa@acme.test",
) -> Dict[str, Any]:
    return {
        "legal_name": legal_name,
        "country_code": country_code,
        "contact_email": contact_email,
    }


# --- Assessment cycles ---------------------------------------------------


def application_payload(
    organization_id: str,
    scheme_id: str,
    cycle_type: str = CYCLE_INITIAL,
    requested_scope_lines: Optional[List[str]] = None,
    notice_days: Optional[int] = NOTICE_DAYS_DEFAULT,
) -> Dict[str, Any]:
    return _without_none(
        {
            "organization_id": organization_id,
            "scheme_id": scheme_id,
            "cycle_type": cycle_type,
            "requested_scope_lines": (
                list(DEFAULT_SCOPE_LINES)
                if requested_scope_lines is None
                else requested_scope_lines
            ),
            "notice_days": notice_days,
        }
    )


def surveillance_application_payload(
    cycle_type: str,
    requested_scope_lines: Optional[List[str]] = None,
    notice_days: Optional[int] = NOTICE_DAYS_DEFAULT,
) -> Dict[str, Any]:
    return _without_none(
        {
            "cycle_type": cycle_type,
            "requested_scope_lines": requested_scope_lines,
            "notice_days": notice_days,
        }
    )


# --- Team assignments ----------------------------------------------------


def team_assignment_payload(assessor_id: str, role_type: str) -> Dict[str, Any]:
    return {"assessor_id": assessor_id, "role_type": role_type}


def recusal_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


# --- Assessment plans ----------------------------------------------------


def plan_payload(
    expected_application_version: int,
    on_site_days: int,
    remote_days: int,
    mode: str = PLAN_MODE_HYBRID,
    planned_start: str = "2026-09-07",
    planned_end: str = "2026-09-18",
) -> Dict[str, Any]:
    return {
        "expected_application_version": expected_application_version,
        "mode": mode,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "on_site_days": on_site_days,
        "remote_days": remote_days,
    }


def return_to_draft_payload(revision_note: str) -> Dict[str, Any]:
    return {"revision_note": revision_note}


# --- Witness sessions ----------------------------------------------------


def witness_session_payload(
    assessor_id: str,
    starts_at: str,
    ends_at: str,
    activity_type: str = ACTIVITY_CALIBRATION,
    site_ref: str = "ACME-LAB-1",
    delivery_mode: str = DELIVERY_ON_SITE,
) -> Dict[str, Any]:
    return {
        "assessor_id": assessor_id,
        "activity_type": activity_type,
        "site_ref": site_ref,
        "delivery_mode": delivery_mode,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }


def session_outcome_payload(
    result_status: str,
    outcome: Optional[str] = None,
    evidence_note: Optional[str] = None,
) -> Dict[str, Any]:
    return _without_none(
        {
            "result_status": result_status,
            "outcome": outcome,
            "evidence_note": evidence_note,
        }
    )


# --- Nonconformities -----------------------------------------------------


def nonconformity_payload(
    clause_ref: str, classification: str, statement: str
) -> Dict[str, Any]:
    return {
        "clause_ref": clause_ref,
        "classification": classification,
        "statement": statement,
    }


def response_payload(
    expected_nonconformity_version: int, root_cause: str, action_plan: str
) -> Dict[str, Any]:
    return {
        "expected_nonconformity_version": expected_nonconformity_version,
        "root_cause": root_cause,
        "action_plan": action_plan,
    }


def review_payload(outcome: str, review_note: str) -> Dict[str, Any]:
    return {"outcome": outcome, "review_note": review_note}


def effectiveness_payload(
    outcome: str, verified_evidence_count: int
) -> Dict[str, Any]:
    return {"outcome": outcome, "verified_evidence_count": verified_evidence_count}


def reopen_payload(reason: str) -> Dict[str, Any]:
    return {"reason": reason}


# --- Decision panel ------------------------------------------------------


def vote_payload(vote: str, rationale: str) -> Dict[str, Any]:
    return {"vote": vote, "rationale": rationale}


def finalize_payload(
    granted_scope_lines: Optional[List[str]] = None,
) -> Dict[str, Any]:
    return _without_none({"granted_scope_lines": granted_scope_lines})


# --- Scopes --------------------------------------------------------------


def scope_status_payload(
    to_status: str, reason: Optional[str] = None
) -> Dict[str, Any]:
    return _without_none({"to_status": to_status, "reason": reason})


# --- Complaints and appeals ---------------------------------------------


def complaint_payload(
    organization_id: str,
    summary: str,
    filed_by_name: str,
    kind: str = CASE_KIND_COMPLAINT,
    application_id: Optional[str] = None,
) -> Dict[str, Any]:
    return _without_none(
        {
            "kind": kind,
            "organization_id": organization_id,
            "application_id": application_id,
            "summary": summary,
            "filed_by_name": filed_by_name,
        }
    )


def complaint_review_payload(reviewer_assessor_id: str) -> Dict[str, Any]:
    return {"reviewer_assessor_id": reviewer_assessor_id}


def complaint_resolution_payload(
    outcome: str, resolution_note: str
) -> Dict[str, Any]:
    return {"outcome": outcome, "resolution_note": resolution_note}


def mra_escalation_payload(mra_body: str) -> Dict[str, Any]:
    return {"mra_body": mra_body}
