"""
Payload factories for the Reentry Employment Services API.

Every factory returns a plain dict whose defaults already satisfy the PRD's
shape rules, so a test only names the fields its own rule is about. Overrides
are always applied by updating the built dict rather than by passing the same
keyword twice, so a derived factory can never raise a duplicate-keyword error.

Money is always a whole number of cents carried as a JSON number. Fields the
PRD declares as ISO 8601 UTC instants carry three fractional digits and a Z
suffix; fields it declares as calendar dates carry no time component at all.
"""

from typing import Any, Dict, List, Optional

from .constants import (
    CATEGORY_TOOLS,
    DOC_MEDICAID_APPLICATION,
    DOC_BIRTH_CERTIFICATE,
    DOC_SSN_CARD,
    DOC_STATE_ID,
    DOC_WORK_HISTORY,
    HEALTH_MEDICAID,
    HOUSING_TRANSITIONAL_HOUSING,
    INDUSTRY_LOGISTICS,
    RECORD_PROPERTY_OFFENSE,
    REPORT_VARIANT_COHORT,
    SUBSIDY_TRACK_SUBSIDIZED,
    SUPERVISION_PAROLE,
    SESSION_TYPE_DISCLOSURE_COACHING,
    TRANSPORT_TRANSIT_PASS,
)


def _merged(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """
    Apply overrides onto a freshly built payload.

    A key whose override value is the sentinel string "__omit__" is removed from
    the payload entirely, which is how a test asks for a missing required field.
    """
    result = dict(base)
    for key, value in overrides.items():
        if value == "__omit__":
            result.pop(key, None)
        else:
            result[key] = value
    return result


# ---------------------------------------------------------------------------
# Participants
# ---------------------------------------------------------------------------


def participant_payload(**overrides) -> Dict[str, Any]:
    """
    A valid participant intake payload.

    `facility_state` is exactly two uppercase letters, and both arrays are
    non-empty with no repeated value.
    """
    base = {
        "full_name": "Marcus Reed",
        "facility_name": "Northgate Correctional",
        "facility_state": "OH",
        "expected_release_date": "2026-08-10",
        "record_categories": [RECORD_PROPERTY_OFFENSE],
        "required_document_types": [
            DOC_STATE_ID,
            DOC_SSN_CARD,
            DOC_BIRTH_CERTIFICATE,
            DOC_WORK_HISTORY,
            DOC_MEDICAID_APPLICATION,
        ],
        "assigned_case_manager_user_id": "cm-1",
    }
    return _merged(base, overrides)


def assessment_payload(
    housing: int = 3,
    transportation: int = 2,
    health: int = 1,
    work_history: int = 4,
    documentation: int = 2,
) -> Dict[str, Any]:
    """
    The five barrier-domain scores.

    The default set is the PRD's own worked example: 3, 2, 1, 4 and 2 weight to
    a raw 2.65 and normalise to a `barrier_score` of 66.3.
    """
    return {
        "assessment_domain_scores": {
            "housing_score": housing,
            "transportation_score": transportation,
            "health_score": health,
            "work_history_score": work_history,
            "documentation_score": documentation,
        }
    }


def raw_assessment_payload(scores: Any) -> Dict[str, Any]:
    """An assessment write whose domain-score object is supplied verbatim."""
    return {"assessment_domain_scores": scores}


def document_verification_payload(document_type: str) -> Dict[str, Any]:
    return {"document_type": document_type}


def release_plan_payload(expected_participant_version: int, **overrides) -> Dict[str, Any]:
    """A release-plan revision, optimistic-concurrency guarded on the participant."""
    base = {
        "expected_participant_version": expected_participant_version,
        "housing_plan_type": HOUSING_TRANSITIONAL_HOUSING,
        "transportation_plan_type": TRANSPORT_TRANSIT_PASS,
        "health_coverage_target": HEALTH_MEDICAID,
        "planned_release_date": "2026-08-10",
    }
    return _merged(base, overrides)


def release_payload(actual_release_date: str = "2026-08-01") -> Dict[str, Any]:
    return {"actual_release_date": actual_release_date}


def suspension_payload(to_status: str, reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    if reason is not None:
        payload["suspension_reason"] = reason
    return payload


def license_relief_payload(
    to_status: str, occupation_code: Optional[str] = None, note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    if occupation_code is not None:
        payload["occupation_code"] = occupation_code
    if note is not None:
        payload["note"] = note
    return payload


def exit_payload(exit_reason: str, exit_date: str = "2026-08-01") -> Dict[str, Any]:
    return {"exit_reason": exit_reason, "exit_date": exit_date}


# ---------------------------------------------------------------------------
# Supervision cases
# ---------------------------------------------------------------------------


def supervision_case_payload(
    participant_id: str, officer_user_id: str, **overrides
) -> Dict[str, Any]:
    base = {
        "participant_id": participant_id,
        "officer_user_id": officer_user_id,
        "officer_name": "M. Ruiz",
        "supervision_type": SUPERVISION_PAROLE,
        "expected_discharge_date": "2027-08-01",
    }
    return _merged(base, overrides)


def case_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def work_authorization_payload(
    decision: str,
    start_minute: Optional[int] = None,
    end_minute: Optional[int] = None,
) -> Dict[str, Any]:
    """
    A work-authorisation decision.

    The two window minutes are only meaningful alongside an approval, so they
    are omitted unless supplied.
    """
    payload: Dict[str, Any] = {"decision": decision}
    if start_minute is not None:
        payload["approved_window_start_minute"] = start_minute
    if end_minute is not None:
        payload["approved_window_end_minute"] = end_minute
    return payload


# ---------------------------------------------------------------------------
# Employer partnerships and job openings
# ---------------------------------------------------------------------------


def partnership_payload(**overrides) -> Dict[str, Any]:
    base = {
        "employer_name": "Northgate Logistics",
        "industry": INDUSTRY_LOGISTICS,
        "max_concurrent_placements": 2,
    }
    return _merged(base, overrides)


def partnership_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def bonding_agreement_payload(
    bond_coverage_cents: int = 500000, bond_effective_date: str = "2026-08-01"
) -> Dict[str, Any]:
    return {
        "bond_coverage_cents": bond_coverage_cents,
        "bond_effective_date": bond_effective_date,
    }


def job_opening_payload(partnership_id: str, **overrides) -> Dict[str, Any]:
    """
    A job opening posting.

    `hourly_wage_cents` defaults above the 725-cent floor and `weekly_hours`
    inside the 0-to-60 band.
    """
    base = {
        "partnership_id": partnership_id,
        "title": "Warehouse Associate",
        "occupation_code": "53-7062",
        "hourly_wage_cents": 1850,
        "weekly_hours": 35,
        "openings_count": 2,
        "barred_record_categories": [],
        "requires_license": False,
        "requires_fidelity_bond": False,
        "transit_accessible": True,
    }
    return _merged(base, overrides)


# ---------------------------------------------------------------------------
# Readiness sessions and enrollments
# ---------------------------------------------------------------------------


def readiness_session_payload(
    coach_user_id: str = "coach-1",
    starts_at: str = "2026-08-05T14:00:00.000Z",
    ends_at: str = "2026-08-05T16:00:00.000Z",
    **overrides,
) -> Dict[str, Any]:
    base = {
        "session_type": SESSION_TYPE_DISCLOSURE_COACHING,
        "coach_user_id": coach_user_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
        "seat_capacity": 3,
    }
    return _merged(base, overrides)


def session_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def enrollment_payload(
    participant_id: str, disclosure_script_reviewed: Optional[bool] = None
) -> Dict[str, Any]:
    """
    A session enrollment. `session_id` comes from the path, never the body.
    """
    payload: Dict[str, Any] = {"participant_id": participant_id}
    if disclosure_script_reviewed is not None:
        payload["disclosure_script_reviewed"] = disclosure_script_reviewed
    return payload


def enrollment_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


# ---------------------------------------------------------------------------
# Placements, offers, shifts, separation, retention
# ---------------------------------------------------------------------------


def placement_payload(
    participant_id: str,
    job_opening_id: str,
    expected_job_opening_version: int,
    grant_id: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    A placement create payload on the subsidised track.

    `grant_id` is required while `subsidy_track` is SUBSIDIZED_WORK_EXPERIENCE
    and must be null on the unsubsidised track.
    """
    base = {
        "participant_id": participant_id,
        "job_opening_id": job_opening_id,
        "grant_id": grant_id,
        "subsidy_track": SUBSIDY_TRACK_SUBSIDIZED,
        "expected_job_opening_version": expected_job_opening_version,
        "start_date": "2026-08-03",
    }
    return _merged(base, overrides)


def offer_response_payload(response: str) -> Dict[str, Any]:
    return {"response": response}


def work_shift_payload(starts_at: str, ends_at: str) -> Dict[str, Any]:
    """A work shift. `placement_id` comes from the path, never the body."""
    return {"starts_at": starts_at, "ends_at": ends_at}


def shift_status_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def separation_payload(
    separation_reason: str, separation_date: str
) -> Dict[str, Any]:
    return {
        "separation_reason": separation_reason,
        "separation_date": separation_date,
    }


def placement_bonding_payload(to_status: str) -> Dict[str, Any]:
    return {"to_status": to_status}


def retention_check_payload(
    milestone_days: int, outcome: str, recidivism_event: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "milestone_days": milestone_days,
        "outcome": outcome,
    }
    if recidivism_event is not None:
        payload["recidivism_event"] = recidivism_event
    return payload


# ---------------------------------------------------------------------------
# Grants and support requests
# ---------------------------------------------------------------------------


def grant_payload(**overrides) -> Dict[str, Any]:
    """
    A funder grant.

    `authorized_cents` and `per_participant_cap_cents` are whole numbers of
    cents and `retention_benchmark_pct` is expressed to one decimal place.
    """
    base = {
        "funder_name": "Reentry Workforce Fund",
        "program_year": 2026,
        "authorized_cents": 100000,
        "allowed_categories": [
            "TOOLS",
            "UNIFORM",
            "TRANSIT_PASS",
            "ID_FEE",
            "LICENSE_FEE",
            "WAGE_SUBSIDY",
        ],
        "per_participant_cap_cents": 50000,
        "retention_benchmark_pct": 50.0,
    }
    return _merged(base, overrides)


def line_item(description: str, unit_cost_cents: int, quantity: int = 1) -> Dict[str, Any]:
    """One support-request line. Costs are whole cents; quantity is 1 through 20."""
    return {
        "description": description,
        "unit_cost_cents": unit_cost_cents,
        "quantity": quantity,
    }


def support_request_payload(
    participant_id: str,
    grant_id: str,
    expected_grant_version: int,
    line_items: Optional[List[Dict[str, Any]]] = None,
    **overrides,
) -> Dict[str, Any]:
    """
    A supportive-services request, optimistic-concurrency guarded on the grant.

    The default single line prices at the TOOLS coverage rate of 0.85.
    """
    base = {
        "participant_id": participant_id,
        "grant_id": grant_id,
        "category": CATEGORY_TOOLS,
        "expected_grant_version": expected_grant_version,
        "line_items": (
            list(line_items)
            if line_items is not None
            else [line_item("Steel-toe boots", 4550)]
        ),
        "justification": "Boots and hand tools required for the warehouse role.",
    }
    return _merged(base, overrides)


def review_payload(decision: str, review_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


def resubmit_payload(
    line_items: Optional[List[Dict[str, Any]]] = None,
    justification: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if line_items is not None:
        payload["line_items"] = list(line_items)
    if justification is not None:
        payload["justification"] = justification
    return payload


def settle_payload(
    to_status: str, settlement_note: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    if settlement_note is not None:
        payload["settlement_note"] = settlement_note
    return payload


def outcome_report_params(variant: Optional[str] = REPORT_VARIANT_COHORT) -> Dict[str, Any]:
    """Query parameters for the funder outcome report."""
    return {} if variant is None else {"variant": variant}


def page_params(limit: Optional[Any] = None, offset: Optional[Any] = None, **filters):
    """Query parameters for a paginated collection read."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    params.update(filters)
    return params
