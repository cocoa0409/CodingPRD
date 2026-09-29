"""
Request-body factories.

Two shape rules are load-bearing and are enforced here rather than at each
call site. Money travels as an integer number of cents in a JSON number, never
as a string. And `claimed_conditions` is "between 1 and 8 elements, each an
object with a condition_code string and a claimed_rating_pct integer" — so the
factory always emits objects, never bare strings.
"""

import itertools
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from .constants import CLOCK_START_DATE

_counter = itertools.count(1)


def unique_suffix() -> int:
    """A per-process monotonically increasing discriminator."""
    return next(_counter)


# ─── Date and instant utilities ───────────────────────


def add_days(day: str, delta: int) -> str:
    """Shift a YYYY-MM-DD date by a whole number of days."""
    return (date.fromisoformat(day) + timedelta(days=delta)).isoformat()


def days_between(start: str, end: str) -> int:
    """Whole days from start to end, exclusive of the start."""
    return (date.fromisoformat(end) - date.fromisoformat(start)).days


def instant(day: str, time_of_day: str = "00:00:00") -> str:
    """An ISO 8601 UTC instant with exactly three fractional digits."""
    return f"{day}T{time_of_day}.000Z"


def add_minutes(value: str, minutes: int) -> str:
    """Shift an instant by whole minutes, preserving the wire format."""
    stamp = datetime.strptime(value[:19], "%Y-%m-%dT%H:%M:%S") + timedelta(
        minutes=minutes
    )
    return stamp.strftime("%Y-%m-%dT%H:%M:%S") + ".000Z"


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


# ─── Representatives ──────────────────────────────────


def representative_payload(
    full_name: Optional[str] = None,
    accreditation_number: Optional[str] = None,
    accreditation_type: str = "COUNTY_CVSO",
    accreditation_expires_on: str = "2027-12-31",
    **overrides: Any,
) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Officer {n}",
        "accreditation_number": accreditation_number or f"ACC-{n:05d}",
        "accreditation_type": accreditation_type,
        "accreditation_expires_on": accreditation_expires_on,
    }
    payload.update(overrides)
    return payload


def accreditation_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def activate_action() -> Dict[str, Any]:
    return {"action": "ACTIVATE"}


def lapse_action() -> Dict[str, Any]:
    return {"action": "LAPSE"}


def renew_action(
    ce_credits: int = 12, accreditation_expires_on: str = "2028-12-31"
) -> Dict[str, Any]:
    return {
        "action": "RENEW",
        "ce_credits": ce_credits,
        "accreditation_expires_on": accreditation_expires_on,
    }


def revoke_accreditation_action(reason: str = "Registry misconduct") -> Dict[str, Any]:
    return {"action": "REVOKE", "reason": reason}


# ─── Veterans ─────────────────────────────────────────


def veteran_payload(
    full_name: Optional[str] = None,
    date_of_birth: str = "1980-03-15",
    service_start_date: str = "2001-09-11",
    service_end_date: str = "2005-09-10",
    household_income_cents: int = 1500000,
    net_worth_cents: int = 5000000,
    dependent_count: Optional[int] = None,
    homeless_status: Optional[str] = None,
    referral_source: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name or f"Veteran {unique_suffix()}",
        "date_of_birth": date_of_birth,
        "service_start_date": service_start_date,
        "service_end_date": service_end_date,
        "household_income_cents": household_income_cents,
        "net_worth_cents": net_worth_cents,
    }
    if dependent_count is not None:
        payload["dependent_count"] = dependent_count
    if homeless_status is not None:
        payload["homeless_status"] = homeless_status
    if referral_source is not None:
        payload["referral_source"] = referral_source
    payload.update(overrides)
    return payload


def veteran_status_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def deactivate_action(reason: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "DEACTIVATE"}
    if reason is not None:
        payload["reason"] = reason
    return payload


def reactivate_action() -> Dict[str, Any]:
    return {"action": "REACTIVATE"}


def record_death_action(
    date_of_death: str = CLOCK_START_DATE, reason: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "RECORD_DEATH", "date_of_death": date_of_death}
    if reason is not None:
        payload["reason"] = reason
    return payload


# ─── Discharge documents ──────────────────────────────


def discharge_document_payload(
    document_type: str = "DD214",
    source: str = "VETERAN_PROVIDED",
    claimed_service_start: str = "2001-09-11",
    claimed_service_end: str = "2005-09-10",
    claimed_character_of_service: str = "HONORABLE",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "document_type": document_type,
        "source": source,
        "claimed_service_start": claimed_service_start,
        "claimed_service_end": claimed_service_end,
        "claimed_character_of_service": claimed_character_of_service,
    }
    payload.update(overrides)
    return payload


def verify_document_action() -> Dict[str, Any]:
    return {"action": "VERIFY"}


def hold_discrepancy_action(reason: str = "Dates disagree with the file") -> Dict[str, Any]:
    return {"action": "HOLD_DISCREPANCY", "reason": reason}


def reject_document_action(reason: str = "Copy is not legible") -> Dict[str, Any]:
    return {"action": "REJECT", "reason": reason}


def resubmit_document_payload(**fields: Any) -> Dict[str, Any]:
    return dict(fields)


# ─── Designations ─────────────────────────────────────


def poa_payload(
    veteran_id: str,
    representative_id: str,
    form_type: str = "VA_21_22",
    scope: str = "ALL_BENEFITS",
    executed_on: str = "2026-07-15",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "representative_id": representative_id,
        "form_type": form_type,
        "scope": scope,
        "executed_on": executed_on,
    }
    payload.update(overrides)
    return payload


def accept_poa_payload(expected_veteran_version: Any) -> Dict[str, Any]:
    return {"expected_veteran_version": expected_veteran_version}


def revoke_poa_payload(reason: str = "Veteran changed representation") -> Dict[str, Any]:
    return {"reason": reason}


def assign_representative_payload(
    representative_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Omitting representative_id is what invokes the automatic selector."""
    return {} if representative_id is None else {"representative_id": representative_id}


# ─── Claims ───────────────────────────────────────────


def condition(
    condition_code: str = "tinnitus", claimed_rating_pct: int = 10
) -> Dict[str, Any]:
    """One element of claimed_conditions, as the object shape the PRD declares."""
    return {"condition_code": condition_code, "claimed_rating_pct": claimed_rating_pct}


def conditions(*codes: str, claimed_rating_pct: int = 10) -> List[Dict[str, Any]]:
    """A claimed_conditions list built from condition codes."""
    return [condition(code, claimed_rating_pct) for code in codes]


def claim_payload(
    veteran_id: str,
    poa_id: str,
    claim_type: str = "DISABILITY_COMPENSATION",
    claimed_conditions: Optional[List[Dict[str, Any]]] = None,
    intent_to_file_date: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "poa_id": poa_id,
        "claim_type": claim_type,
        "claimed_conditions": claimed_conditions or [condition()],
    }
    if intent_to_file_date is not None:
        payload["intent_to_file_date"] = intent_to_file_date
    payload.update(overrides)
    return payload


def claim_transition(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def open_evidence_development_action() -> Dict[str, Any]:
    return {"action": "OPEN_EVIDENCE_DEVELOPMENT"}


def submit_for_review_action(reviewer_representative_id: str) -> Dict[str, Any]:
    return {
        "action": "SUBMIT_FOR_REVIEW",
        "reviewer_representative_id": reviewer_representative_id,
    }


def return_for_rework_action(rework_note: str = "Add the nexus opinion") -> Dict[str, Any]:
    return {"action": "RETURN_FOR_REWORK", "rework_note": rework_note}


def mark_ready_action() -> Dict[str, Any]:
    return {"action": "MARK_READY"}


def file_claim_action(filed_on: str = CLOCK_START_DATE) -> Dict[str, Any]:
    return {"action": "FILE", "filed_on": filed_on}


def withdraw_claim_action(reason: str = "Veteran withdrew the claim") -> Dict[str, Any]:
    return {"action": "WITHDRAW", "reason": reason}


def record_decision_payload(
    decision_outcome: str = "GRANTED",
    awarded_rating_pct: int = 30,
    decided_on: str = CLOCK_START_DATE,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "decision_outcome": decision_outcome,
        "awarded_rating_pct": awarded_rating_pct,
        "decided_on": decided_on,
    }
    payload.update(overrides)
    return payload


# ─── Evidence ─────────────────────────────────────────


def evidence_item_payload(
    evidence_type: str = "SERVICE_TREATMENT_RECORD",
    provider_name: Optional[str] = None,
    nexus_opinion_strength: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "evidence_type": evidence_type,
        "provider_name": provider_name or f"Custodian {unique_suffix()}",
    }
    if nexus_opinion_strength is not None:
        payload["nexus_opinion_strength"] = nexus_opinion_strength
    payload.update(overrides)
    return payload


def evidence_status_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def receive_evidence_action() -> Dict[str, Any]:
    return {"action": "RECEIVE"}


def mark_insufficient_action(reason: str = "Record is incomplete") -> Dict[str, Any]:
    return {"action": "MARK_INSUFFICIENT", "reason": reason}


def re_request_evidence_action() -> Dict[str, Any]:
    return {"action": "RE_REQUEST"}


def waive_evidence_action(reason: str = "Custodian cannot produce it") -> Dict[str, Any]:
    return {"action": "WAIVE", "reason": reason}


# ─── Examination sites and appointments ───────────────


def exam_site_payload(
    name: Optional[str] = None,
    county_code: str = "CV",
    concurrent_capacity: Optional[int] = None,
    buffer_minutes: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name or f"Contract Site {unique_suffix()}",
        "county_code": county_code,
    }
    if concurrent_capacity is not None:
        payload["concurrent_capacity"] = concurrent_capacity
    if buffer_minutes is not None:
        payload["buffer_minutes"] = buffer_minutes
    payload.update(overrides)
    return payload


def exam_appointment_payload(
    claim_id: str,
    exam_site_id: str,
    starts_at: str,
    ends_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "claim_id": claim_id,
        "exam_site_id": exam_site_id,
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    payload.update(overrides)
    return payload


def appointment_status_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def complete_prep_action() -> Dict[str, Any]:
    return {"action": "COMPLETE_PREP"}


def complete_appointment_action(completed_on: str = CLOCK_START_DATE) -> Dict[str, Any]:
    return {"action": "COMPLETE", "completed_on": completed_on}


def no_show_action() -> Dict[str, Any]:
    return {"action": "NO_SHOW"}


def cancel_appointment_action(reason: str = "Veteran rescheduled") -> Dict[str, Any]:
    return {"action": "CANCEL", "reason": reason}


# ─── Decision reviews ─────────────────────────────────


def decision_review_payload(
    claim_id: str, review_lane: str = "HIGHER_LEVEL_REVIEW", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"claim_id": claim_id, "review_lane": review_lane}
    payload.update(overrides)
    return payload


def review_status_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def elect_review_action(
    elected_on: str = CLOCK_START_DATE, review_lane: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": "ELECT", "elected_on": elected_on}
    if review_lane is not None:
        payload["review_lane"] = review_lane
    return payload


def file_review_action(filed_on: str = CLOCK_START_DATE) -> Dict[str, Any]:
    return {"action": "FILE", "filed_on": filed_on}


def withdraw_review_action(reason: str = "Veteran dropped the appeal") -> Dict[str, Any]:
    return {"action": "WITHDRAW", "reason": reason}


# ─── State programs and applications ──────────────────


def state_program_payload(
    program_code: Optional[str] = None,
    program_name: Optional[str] = None,
    program_type: str = "PROPERTY_TAX_EXEMPTION",
    fiscal_year: int = 2026,
    annual_pool_cents: int = 100000000,
    min_rating_pct: int = 0,
    requires_wartime: bool = False,
    max_award_cents: int = 100000000,
    **overrides: Any,
) -> Dict[str, Any]:
    n = unique_suffix()
    payload: Dict[str, Any] = {
        "program_code": program_code or f"PRG-{n:05d}",
        "program_name": program_name or f"Program {n}",
        "program_type": program_type,
        "fiscal_year": fiscal_year,
        "annual_pool_cents": annual_pool_cents,
        "min_rating_pct": min_rating_pct,
        "requires_wartime": requires_wartime,
        "max_award_cents": max_award_cents,
    }
    payload.update(overrides)
    return payload


def benefit_application_payload(
    veteran_id: str,
    program_id: str,
    fiscal_year: int,
    expected_program_version: Any,
    assessed_property_value_cents: Optional[int] = None,
    tuition_credits_requested: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "veteran_id": veteran_id,
        "program_id": program_id,
        "fiscal_year": fiscal_year,
        "expected_program_version": expected_program_version,
    }
    if assessed_property_value_cents is not None:
        payload["assessed_property_value_cents"] = assessed_property_value_cents
    if tuition_credits_requested is not None:
        payload["tuition_credits_requested"] = tuition_credits_requested
    payload.update(overrides)
    return payload


def determination_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def approve_application_action() -> Dict[str, Any]:
    return {"action": "APPROVE"}


def deny_application_action(reason: str = "Not eligible this year") -> Dict[str, Any]:
    return {"action": "DENY", "reason": reason}


def disbursement_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def issue_action(issued_on: str = CLOCK_START_DATE) -> Dict[str, Any]:
    return {"action": "ISSUE", "issued_on": issued_on}


def claw_back_action(reason: str = "Recovered by the operator") -> Dict[str, Any]:
    return {"action": "CLAW_BACK", "reason": reason}


# ─── Outreach ─────────────────────────────────────────


def outreach_event_payload(
    assigned_representative_id: str,
    starts_at: str,
    ends_at: str,
    event_type: str = "RURAL_CLINIC",
    location_name: Optional[str] = None,
    underserved_flag: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "assigned_representative_id": assigned_representative_id,
        "event_type": event_type,
        "location_name": location_name or f"Venue {unique_suffix()}",
        "starts_at": starts_at,
        "ends_at": ends_at,
    }
    if underserved_flag is not None:
        payload["underserved_flag"] = underserved_flag
    payload.update(overrides)
    return payload


def outreach_status_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def hold_outreach_action(
    veterans_contacted: int = 10, veterans_enrolled: int = 4
) -> Dict[str, Any]:
    return {
        "action": "HOLD",
        "veterans_contacted": veterans_contacted,
        "veterans_enrolled": veterans_enrolled,
    }


def cancel_outreach_action(reason: str = "Venue withdrew") -> Dict[str, Any]:
    return {"action": "CANCEL", "reason": reason}


# ─── Outcome reports ──────────────────────────────────


def outcome_report_payload(fiscal_quarter: str = "2026Q2", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"fiscal_quarter": fiscal_quarter}
    payload.update(overrides)
    return payload


def compute_report_payload(weighting_basis: str = "CLAIM_WEIGHTED") -> Dict[str, Any]:
    return {"weighting_basis": weighting_basis}


def report_review_action(action: str, **fields: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    payload.update(fields)
    return payload


def accept_report_action() -> Dict[str, Any]:
    return {"action": "ACCEPT"}


def return_report_action(reason: str = "Recompute under veteran weighting") -> Dict[str, Any]:
    return {"action": "RETURN", "reason": reason}


__all__ = [
    "unique_suffix",
    "add_days",
    "days_between",
    "instant",
    "add_minutes",
    "clock_payload",
    "representative_payload",
    "accreditation_action",
    "activate_action",
    "lapse_action",
    "renew_action",
    "revoke_accreditation_action",
    "veteran_payload",
    "veteran_status_action",
    "deactivate_action",
    "reactivate_action",
    "record_death_action",
    "discharge_document_payload",
    "verify_document_action",
    "hold_discrepancy_action",
    "reject_document_action",
    "resubmit_document_payload",
    "poa_payload",
    "accept_poa_payload",
    "revoke_poa_payload",
    "assign_representative_payload",
    "condition",
    "conditions",
    "claim_payload",
    "claim_transition",
    "open_evidence_development_action",
    "submit_for_review_action",
    "return_for_rework_action",
    "mark_ready_action",
    "file_claim_action",
    "withdraw_claim_action",
    "record_decision_payload",
    "evidence_item_payload",
    "evidence_status_action",
    "receive_evidence_action",
    "mark_insufficient_action",
    "re_request_evidence_action",
    "waive_evidence_action",
    "exam_site_payload",
    "exam_appointment_payload",
    "appointment_status_action",
    "complete_prep_action",
    "complete_appointment_action",
    "no_show_action",
    "cancel_appointment_action",
    "decision_review_payload",
    "review_status_action",
    "elect_review_action",
    "file_review_action",
    "withdraw_review_action",
    "state_program_payload",
    "benefit_application_payload",
    "determination_action",
    "approve_application_action",
    "deny_application_action",
    "disbursement_action",
    "issue_action",
    "claw_back_action",
    "outreach_event_payload",
    "outreach_status_action",
    "hold_outreach_action",
    "cancel_outreach_action",
    "outcome_report_payload",
    "compute_report_payload",
    "report_review_action",
    "accept_report_action",
    "return_report_action",
]
