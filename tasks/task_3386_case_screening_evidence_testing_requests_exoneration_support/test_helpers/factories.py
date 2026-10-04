"""Payload factories - one per creatable entity, input fields only.

Optional fields are OMITTED unless explicitly supplied, so server-side
defaults (and null-until-stamped fields) are exercised by default; pass the
key explicitly to set it. Intake defaults use the PRD's worked screening
anchor inputs (STRONG / LIKELY_STORED / 7 years / CRITICAL) so an unadorned
RECOMMEND stores the pinned 66.55 / 71.07 scores.
"""
from typing import Any, Dict, List, Optional

from . import constants as C


def _v(value: Any) -> Any:
    """Coerce enum members to their string value; pass everything else through."""
    return getattr(value, "value", value)


def _put(payload: Dict[str, Any], key: str, value: Any) -> None:
    """Set payload[key] only when the caller actually supplied a value."""
    if value is not None:
        payload[key] = _v(value)


# =============================================================================
# Clock
# =============================================================================

def clock_payload(to_iso8601: str) -> Dict[str, Any]:
    return {"to_iso8601": to_iso8601}


# =============================================================================
# Jurisdiction
# =============================================================================

def create_jurisdiction_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "state_code": "NY",
        "name": "New York",
        "has_post_conviction_dna_statute": True,
        "clemency_available": True,
        "compensation_statute_exists": True,
    }
    # Optional statute fields: omitted unless supplied (null deadline / null
    # cap / 0 enhancement are the server-side defaults).
    for key in (
        "post_conviction_deadline_years",
        "compensation_cap_cents",
        "actual_innocence_enhancement_pct",
    ):
        if key in overrides:
            payload[key] = overrides.pop(key)
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


# =============================================================================
# Client
# =============================================================================

def create_client_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": "Jordan Avery",
        "inmate_number": "DOC-0001",
    }
    if "facility_name" in overrides:
        payload["facility_name"] = overrides.pop("facility_name")
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


# =============================================================================
# Intake request
# =============================================================================

def create_intake_request_payload(
    client_id: str, jurisdiction_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "client_id": client_id,
        "jurisdiction_id": jurisdiction_id,
        "conviction_date": "2019-05-01T00:00:00Z",
        "conviction_summary": "Conviction resting on eyewitness identification",
        "claim_of_actual_innocence": True,
        "claim_strength": C.ANCHOR_CLAIM_STRENGTH,
        "evidence_potential": C.ANCHOR_EVIDENCE_POTENTIAL,
        "years_served": C.ANCHOR_YEARS_SERVED,
        "health_urgency": C.ANCHOR_HEALTH_URGENCY,
    }
    if "expedited_review" in overrides:
        payload["expedited_review"] = overrides.pop("expedited_review")
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def intake_advance_payload(event: Any, recommendation: Optional[Any] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "recommendation", recommendation)
    return payload


def submit_supplement_payload(supplement_notes: str) -> Dict[str, Any]:
    return {"supplement_notes": supplement_notes}


def decide_payload(
    decision: Any,
    assigned_attorney_id: Optional[str] = None,
    rejection_reason: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": _v(decision)}
    _put(payload, "assigned_attorney_id", assigned_attorney_id)
    _put(payload, "rejection_reason", rejection_reason)
    return payload


# =============================================================================
# Case
# =============================================================================

def case_update_payload(
    expected_case_version: int,
    strategy_notes: Optional[str] = None,
    theory_of_case: Optional[str] = None,
    assigned_attorney_id: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"expected_case_version": expected_case_version}
    _put(payload, "strategy_notes", strategy_notes)
    _put(payload, "theory_of_case", theory_of_case)
    _put(payload, "assigned_attorney_id", assigned_attorney_id)
    return payload


def case_advance_payload(
    event: Any,
    resolution: Optional[Any] = None,
    housing_arranged: Optional[bool] = None,
    id_documents_ready: Optional[bool] = None,
    transportation_arranged: Optional[bool] = None,
    scheduled_release_date: Optional[str] = None,
) -> Dict[str, Any]:
    """The checklist keys map onto the case's release_*_ready flags; an absent
    key leaves its flag unchanged, so keys are included only when supplied."""
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "resolution", resolution)
    _put(payload, "housing_arranged", housing_arranged)
    _put(payload, "id_documents_ready", id_documents_ready)
    _put(payload, "transportation_arranged", transportation_arranged)
    _put(payload, "scheduled_release_date", scheduled_release_date)
    return payload


def log_contact_payload(
    channel: str = "PHONE",
    expectation_setting: Any = "NEUTRAL",
    summary: Optional[str] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "channel": channel,
        "expectation_setting": _v(expectation_setting),
    }
    _put(payload, "summary", summary)
    return payload


# =============================================================================
# Evidence item
# =============================================================================

def create_evidence_item_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "description": "Rape kit swab, original collection",
        "evidence_type": "BIOLOGICAL_SWAB",
        "custodian_type": "CRIME_LAB",
        "initial_sample_ng": 25,
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def evidence_advance_payload(event: Any) -> Dict[str, Any]:
    return {"event": _v(event)}


# =============================================================================
# Records request
# =============================================================================

def create_records_request_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "agency_type": "POLICE",
        "agency_name": "Metro PD Property Unit",
        "request_summary": "All biological and physical evidence for the case",
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def revealed_item(evidence_item_id: str, disposition: Any) -> Dict[str, str]:
    """One items_revealed entry: {evidence_item_id, disposition}."""
    return {"evidence_item_id": evidence_item_id, "disposition": _v(disposition)}


def records_advance_payload(
    event: Any,
    disposition: Optional[Any] = None,
    items_revealed: Optional[List[Dict[str, str]]] = None,
) -> Dict[str, Any]:
    """RECORD_RESPONSE carries disposition plus the reveal array; a DENIED
    response must carry an absent or empty items_revealed, so the key is
    included only when supplied."""
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "disposition", disposition)
    if items_revealed is not None:
        payload["items_revealed"] = items_revealed
    return payload


# =============================================================================
# Testing authorization
# =============================================================================

def create_testing_authorization_payload(
    case_id: str, evidence_item_id: str, kind: Any = "AGREEMENT", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "evidence_item_id": evidence_item_id,
        "kind": _v(kind),
        "terms": "Negotiated testing terms (scope, lab, cost split)",
    }
    if "proposed_test_types" in overrides:
        payload["proposed_test_types"] = overrides.pop("proposed_test_types")
    if "terms" in overrides:
        payload["terms"] = overrides.pop("terms")
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def authorization_advance_payload(event: Any, ruling: Optional[Any] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "ruling", ruling)
    return payload


def amendment_payload(
    expected_testing_authorization_version: int,
    terms: Optional[str] = None,
    proposed_test_types: Optional[List[str]] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_testing_authorization_version": expected_testing_authorization_version
    }
    _put(payload, "terms", terms)
    _put(payload, "proposed_test_types", proposed_test_types)
    return payload


# =============================================================================
# Lab analysis
# =============================================================================

def create_lab_analysis_payload(
    evidence_item_id: str, authorization_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_item_id": evidence_item_id,
        "authorization_id": authorization_id,
        "lab_name": "LabPrime",
        "test_type": "DNA_STR",
        "required_sample_ng": 5,
        "scheduled_start": "2026-10-01T09:00:00Z",
        "scheduled_end": "2026-10-05T17:00:00Z",
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def lab_advance_payload(event: Any, **fields: Any) -> Dict[str, Any]:
    """Generic lab advance: event plus whichever event-specific fields apply
    (outcome / actual_consumed_ng / profile_obtained / expert_name /
    expert_interpretation / database_name / comparison_result /
    matched_subject_name). Fields left as None are omitted."""
    payload: Dict[str, Any] = {"event": _v(event)}
    for key, value in fields.items():
        _put(payload, key, value)
    return payload


def lab_result_payload(outcome: Any, actual_consumed_ng: int, profile_obtained: bool) -> Dict[str, Any]:
    return lab_advance_payload(
        "RECORD_RESULT",
        outcome=outcome,
        actual_consumed_ng=actual_consumed_ng,
        profile_obtained=profile_obtained,
    )


def expert_interpretation_payload(expert_name: str, expert_interpretation: Any) -> Dict[str, Any]:
    return lab_advance_payload(
        "RECORD_EXPERT_INTERPRETATION",
        expert_name=expert_name,
        expert_interpretation=expert_interpretation,
    )


def db_comparison_payload(
    database_name: str, comparison_result: Any, matched_subject_name: Optional[str] = None
) -> Dict[str, Any]:
    """A matched_subject_name is lawful only on a HIT; it is omitted unless
    supplied."""
    return lab_advance_payload(
        "RUN_DATABASE_COMPARISON",
        database_name=database_name,
        comparison_result=comparison_result,
        matched_subject_name=matched_subject_name,
    )


# =============================================================================
# Legal petition
# =============================================================================

def create_legal_petition_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "petition_type": "DIRECT_APPEAL",
        "court_name": "State Court of Appeals",
        "claim_basis": "PROCEDURAL",
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def petition_advance_payload(
    event: Any, decision: Optional[Any] = None, vacates_conviction: Optional[bool] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "decision", decision)
    _put(payload, "vacates_conviction", vacates_conviction)
    return payload


# =============================================================================
# Compensation claim
# =============================================================================

def create_compensation_claim_payload(case_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "years_incarcerated_claimed": C.ANCHOR_YEARS_CLAIMED,
    }
    if "documented_legal_fees_cents" in overrides:
        payload["documented_legal_fees_cents"] = overrides.pop("documented_legal_fees_cents")
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def claim_advance_payload(
    event: Any,
    decision: Optional[Any] = None,
    paid_amount_cents: Optional[int] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": _v(event)}
    _put(payload, "decision", decision)
    _put(payload, "paid_amount_cents", paid_amount_cents)
    return payload


# =============================================================================
# Reentry provider & referral
# =============================================================================

def create_reentry_provider_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": "FreshStart Housing",
        "service_type": "HOUSING",
        "total_capacity": 2,
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def create_reentry_referral_payload(case_id: str, provider_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "case_id": case_id,
        "provider_id": provider_id,
        "service_start": "2027-03-01T00:00:00Z",
        "service_end": "2027-03-10T00:00:00Z",
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def referral_advance_payload(event: Any) -> Dict[str, Any]:
    return {"event": _v(event)}


# =============================================================================
# Policy initiative
# =============================================================================

def create_policy_initiative_payload(jurisdiction_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jurisdiction_id": jurisdiction_id,
        "topic": "EVIDENCE_PRESERVATION",
        "title": "Mandate evidence retention inventories",
    }
    for key, value in overrides.items():
        payload[key] = _v(value)
    return payload


def policy_advance_payload(event: Any) -> Dict[str, Any]:
    return {"event": _v(event)}
